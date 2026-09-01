#!/usr/bin/env python3
"""Validate JSON/YAML files against their corresponding JSON Schema.

Usage:
    python scripts/validate.py registry-v2.json
    python scripts/validate.py seed.yaml
    python scripts/validate.py --all-examples
    python scripts/validate.py --ignore-missing optional-example.json
"""

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

try:
    import jsonschema
except ImportError:
    print("ERROR: jsonschema not installed. Run: pip install jsonschema", file=sys.stderr)
    sys.exit(1)

try:
    import yaml
except ImportError:
    yaml = None

if __package__:
    from .schema_formats import FORMAT_CHECKER
    from .validate_governance_memory import (
        validate_document as validate_governance_document,
    )
else:
    from schema_formats import FORMAT_CHECKER
    from validate_governance_memory import (
        validate_document as validate_governance_document,
    )

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"
EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"
PROJECT_RECORD_EXAMPLE = EXAMPLES_DIR / "project-record-v1-example.yaml"
PROJECT_RECORD_FIXTURE_ROOT = EXAMPLES_DIR / "project-record-v1-fixture"
PROJECT_RECORD_SCHEMA_ID = (
    "https://organvm-iv-taxis.github.io/schema-definitions/"
    "project-record-v1.schema.json"
)
_REPOSITORY_SLUG = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_DEPLOYMENT_POSTURES = {
    "pilot": frozenset({"implemented", "partial"}),
    "public": frozenset({"implemented", "partial"}),
    "retired": frozenset({"implemented", "partial", "contradicted"}),
}

# Map file name patterns to schemas
SCHEMA_MAP = {
    "project-record": "project-record-v1.schema.json",
    "governance-snapshot-bundle": "governance-snapshot-bundle.v1.schema.json",
    "governance-cadence-receipt": "governance-cadence-receipt.v1.schema.json",
    "governance-stage-receipt": "governance-stage-receipt.v1.schema.json",
    "governance-atlas-receipt": "governance-atlas-receipt.v1.schema.json",
    "normalization-parity-receipt": "normalization-parity-receipt.v1.schema.json",
    "node-self-image-set": "node-self-image-set.v1.schema.json",
    "ideal-form-register": "ideal-form-register.v1.schema.json",
    "normalized-event": "normalized-event.v1.schema.json",
    "source-census": "source-census.v1.schema.json",
    "iceberg-atlas": "iceberg-atlas.v1.schema.json",
    "owner-reference": "owner-reference.v1.schema.json",
    "parameter-contract": "parameter-contract.v1.schema.json",
    "source-envelope": "source-envelope.v1.schema.json",
    "assertion-evidence": "assertion-evidence.v1.schema.json",
    "lineage-graph": "lineage-graph.v1.schema.json",
    "governance-testament": "governance-testament.v1.schema.json",
    "node-self-image": "node-self-image.v1.schema.json",
    "coverage-receipt": "coverage-receipt.v1.schema.json",
    "ammoi": "ammoi-v1.schema.json",
    "evolution-policy": "evolution-policy.schema.json",
    "pulse-event": "pulse-event.schema.json",
    "sensing-signal": "sensing-signal.schema.json",
    "state-snapshot": "state-snapshot.schema.json",
    "testament-artifact": "testament-artifact.schema.json",
    "surface-manifest": "conversation-corpus-surface-manifest.schema.json",
    "mcp-context": "conversation-corpus-mcp-context.schema.json",
    "surface-bundle": "conversation-corpus-surface-bundle.schema.json",
    "system-organism": "system-organism.schema.json",
    "pillar-dna": "pillar-dna-v1.schema.json",
    "ecosystem": "ecosystem-v1.schema.json",
    "registry": "registry-v2.schema.json",
    "seed-v1.1": "seed-v1.1.schema.json",
    "seed": "seed-v1.schema.json",
    "governance": "governance-rules.schema.json",
    "dispatch": "dispatch-payload.schema.json",
    "soak": "soak-test.schema.json",
    "daily": "soak-test.schema.json",
    "metrics": "system-metrics.schema.json",
    "entity-identity": "entity-identity.schema.json",
    "name-record": "name-record.schema.json",
    "ontologia-event": "ontologia-event.schema.json",
    "organ-definitions": "organ-definitions.schema.json",
    "excavation-report": "excavation-report.schema.json",
    "workspace-manifest": "workspace-manifest-v1.schema.json",
    "uaks-assembly-recipe": "uaks-assembly-recipe.schema.json",
    "uaks-code-atom": "uaks-code-atom.schema.json",
    "uaks-source-object": "uaks-source-object.schema.json",
    "uaks-text-atom": "uaks-text-atom.schema.json",
    "uaks-validation-event": "uaks-validation-event.schema.json",
    "storefront": "storefront-v1.schema.json",
}


def detect_schema(filepath: Path) -> Path | None:
    """Auto-detect which schema to use based on filename."""
    name = filepath.stem.lower()
    for key, schema_file in SCHEMA_MAP.items():
        if key in name:
            return SCHEMAS_DIR / schema_file
    return None


def load_data(filepath: Path) -> dict:
    """Load JSON or YAML file."""
    suffix = filepath.suffix.lower()
    with open(filepath) as f:
        if suffix in (".yaml", ".yml"):
            if yaml is None:
                print("ERROR: pyyaml not installed. Run: pip install pyyaml", file=sys.stderr)
                sys.exit(1)
            return yaml.safe_load(f)
        return json.load(f)


def _duplicate_strings(values: list[str]) -> list[str]:
    """Return duplicate strings once each, in deterministic order."""
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def _github_repository_slug(value: object) -> str | None:
    """Return owner/name for one canonical GitHub repository URL."""
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.netloc != "github.com"
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.query
        or parsed.fragment
    ):
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2:
        return None
    owner, name = parts
    name = name.removesuffix(".git")
    repository = f"{owner}/{name}"
    return repository if _REPOSITORY_SLUG.fullmatch(repository) else None


def _contained_file(root: Path, reference: str) -> Path | None:
    """Resolve a repository-relative file without permitting root escape."""
    try:
        candidate = (root / reference).resolve()
        candidate.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return None
    return candidate if candidate.is_file() else None


def _load_mapping(path: Path) -> Mapping[str, object]:
    """Load one JSON/YAML mapping without terminating the validation batch."""
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        if yaml is None:
            raise ValueError("pyyaml is required to load YAML assertions")
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValueError(f"invalid YAML: {exc}") from exc
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise TypeError("document is not a mapping")
    return data


def _assertion_target(
    *,
    root: Path,
    reference: str,
    assertion_id: str,
    label: str,
) -> tuple[Mapping[str, object] | None, list[str]]:
    """Load, validate, and byte-bind one local assertion target."""
    candidate = _contained_file(root, reference)
    if candidate is None:
        return None, [f"  {label} assertion path does not exist or escapes root: {reference}"]
    try:
        assertion = _load_mapping(candidate)
    except (OSError, TypeError, UnicodeError, ValueError) as exc:
        return None, [f"  {label} cannot load assertion {reference}: {exc}"]

    errors: list[str] = []
    contract_matches = assertion.get("contract_name") == "assertion-evidence.v1"
    id_matches = assertion.get("assertion_id") == assertion_id
    if not contract_matches:
        errors.append(f"  {label} target is not assertion-evidence.v1: {reference}")
    if not id_matches:
        errors.append(f"  {label} assertion_id does not match {reference}")

    if contract_matches:
        schema_errors, semantic_errors = validate_governance_document(assertion)
        errors.extend(
            f"  assertion {reference}: schema: {error}" for error in schema_errors
        )
        errors.extend(
            f"  assertion {reference}: semantic: {error}"
            for error in semantic_errors
        )

        evidence = assertion.get("evidence_references")
        if isinstance(evidence, list):
            for index, item in enumerate(evidence):
                if not isinstance(item, Mapping):
                    continue
                evidence_reference = item.get("reference")
                body_hash = item.get("body_hash")
                evidence_label = (
                    f"assertion {reference} evidence_references[{index}]"
                )
                if not isinstance(evidence_reference, str):
                    continue
                evidence_path = _contained_file(root, evidence_reference)
                if evidence_path is None:
                    errors.append(
                        f"  {evidence_label} path does not exist or escapes root: "
                        f"{evidence_reference}"
                    )
                    continue
                try:
                    evidence_bytes = evidence_path.read_bytes()
                except OSError as exc:
                    errors.append(f"  {evidence_label} cannot read bytes: {exc}")
                    continue
                digest = "sha256:" + hashlib.sha256(evidence_bytes).hexdigest()
                if body_hash != digest:
                    errors.append(
                        f"  {evidence_label} body_hash does not match raw bytes"
                    )

    if not contract_matches or not id_matches:
        return None, errors
    return assertion, errors


def _validate_local_file(
    root: Path,
    reference: object,
    label: str,
    errors: list[str],
) -> None:
    if isinstance(reference, str) and _contained_file(root, reference) is None:
        errors.append(f"  {label} does not exist or escapes root: {reference}")


def _verified_fact_matches(
    assertion: Mapping[str, object] | None,
    *,
    predicate: str,
    value: str,
    subject: str | None = None,
    project_repository: str | None = None,
    require_current_state: bool = False,
) -> bool:
    """Return whether verified evidence asserts one exact machine fact."""
    if assertion is None or assertion.get("verification_state") != "verified":
        return False
    if require_current_state and assertion.get("assertion_class") != "current_state":
        return False
    fact = assertion.get("fact")
    return (
        isinstance(fact, Mapping)
        and fact.get("predicate") == predicate
        and fact.get("value") == value
        and (subject is None or fact.get("subject") == subject)
        and (
            project_repository is None
            or fact.get("project_repository") == project_repository
        )
    )


def project_record_semantic_errors(
    data: object,
    *,
    repository_root: str | Path | None = None,
    actual_repository: str | None = None,
) -> list[str]:
    """Validate project-record invariants JSON Schema cannot express."""
    if not isinstance(data, dict):
        return []
    routes = data.get("audience_routes")
    if not isinstance(routes, list):
        routes = []

    modes = [
        route["mode"]
        for route in routes
        if isinstance(route, dict) and isinstance(route.get("mode"), str)
    ]
    paths = [
        route["path"]
        for route in routes
        if isinstance(route, dict) and isinstance(route.get("path"), str)
    ]

    errors: list[str] = []
    duplicate_modes = _duplicate_strings(modes)
    if duplicate_modes:
        errors.append(
            "  audience_routes: duplicate mode values: "
            + ", ".join(duplicate_modes)
        )
    duplicate_paths = _duplicate_strings(paths)
    if duplicate_paths:
        errors.append(
            "  audience_routes: duplicate path values: "
            + ", ".join(duplicate_paths)
        )

    claims = data.get("claim_references")
    if not isinstance(claims, list):
        claims = []
    claim_ids = [
        claim["id"]
        for claim in claims
        if isinstance(claim, dict) and isinstance(claim.get("id"), str)
    ]
    duplicate_claim_ids = _duplicate_strings(claim_ids)
    if duplicate_claim_ids:
        errors.append(
            "  claim_references: duplicate id values: "
            + ", ".join(duplicate_claim_ids)
        )

    industries = data.get("industries")
    if not isinstance(industries, list):
        industries = []
    industry_names = [
        industry["name"]
        for industry in industries
        if isinstance(industry, dict) and isinstance(industry.get("name"), str)
    ]
    duplicate_industry_names = _duplicate_strings(industry_names)
    if duplicate_industry_names:
        errors.append(
            "  industries: duplicate name values: "
            + ", ".join(duplicate_industry_names)
        )
    claim_id_counts = Counter(claim_ids)
    claim_indexes_by_id = {
        claim["id"]: index
        for index, claim in enumerate(claims)
        if isinstance(claim, dict)
        and isinstance(claim.get("id"), str)
        and claim_id_counts[claim["id"]] == 1
    }
    for industry_index, industry in enumerate(industries):
        if not isinstance(industry, dict):
            continue
        industry_claims = industry.get("claim_references")
        if not isinstance(industry_claims, list):
            continue
        for reference_index, reference in enumerate(industry_claims):
            if isinstance(reference, str) and claim_id_counts[reference] != 1:
                errors.append(
                    f"  industries[{industry_index}].claim_references"
                    f"[{reference_index}] must resolve to exactly one top-level "
                    f"claim_reference id: {reference}"
                )

    documentation_class = data.get("documentation_class")
    repository_role = data.get("repository_role")
    canonical_repository = data.get("canonical_repository")
    links = data.get("links")
    if repository_role == "canonical" and isinstance(canonical_repository, str):
        repository_link = links.get("repository") if isinstance(links, dict) else None
        linked_repository = _github_repository_slug(repository_link)
        if (
            linked_repository is None
            or linked_repository.casefold() != canonical_repository.casefold()
        ):
            errors.append(
                "  links.repository must resolve to canonical_repository for a "
                "canonical repository role"
            )
    class_d_delivery = documentation_class == "D" or (
        isinstance(repository_role, str)
        and repository_role in {"mirror", "deployment-artifact"}
    )
    if class_d_delivery:
        redirect = data.get("redirect")
        target = redirect.get("target") if isinstance(redirect, dict) else None
        target_repository = _github_repository_slug(target)
        if target_repository is None:
            errors.append(
                "  class D redirect.target must be a canonical HTTPS GitHub repository URL"
            )
        elif (
            isinstance(canonical_repository, str)
            and target_repository.casefold() != canonical_repository.casefold()
        ):
            errors.append(
                "  class D redirect.target must resolve to canonical_repository"
            )
        if actual_repository is None:
            errors.append(
                "  class D validation requires actual_repository owner/name context"
            )
        elif _REPOSITORY_SLUG.fullmatch(actual_repository) is None:
            errors.append("  actual_repository must use owner/name form")
        elif (
            isinstance(canonical_repository, str)
            and canonical_repository.casefold() == actual_repository.casefold()
        ):
            errors.append(
                "  class D canonical_repository must differ from actual_repository"
            )

    root: Path | None = None
    if repository_root is not None:
        root = Path(repository_root).resolve()
        if not root.is_dir():
            errors.append(f"  repository_root is not a directory: {root}")
            root = None

    resolved_assertions: dict[int, Mapping[str, object]] = {}
    if root is not None:
        for index, route in enumerate(routes):
            if isinstance(route, dict):
                _validate_local_file(
                    root,
                    route.get("path"),
                    f"audience_routes[{index}].path",
                    errors,
                )

        for index, industry in enumerate(industries):
            if isinstance(industry, dict) and "path" in industry:
                _validate_local_file(
                    root,
                    industry.get("path"),
                    f"industries[{index}].path",
                    errors,
                )

        if isinstance(links, dict):
            for key in ("documentation", "evidence"):
                reference = links.get(key)
                if isinstance(reference, str) and _github_repository_slug(reference) is None:
                    try:
                        is_remote = bool(urlsplit(reference).scheme)
                    except ValueError:
                        is_remote = True
                    if not is_remote:
                        _validate_local_file(root, reference, f"links.{key}", errors)

        for index, claim in enumerate(claims):
            if not isinstance(claim, dict):
                continue
            reference = claim.get("assertion_ref")
            assertion_id = claim.get("assertion_id")
            if not isinstance(reference, str) or not isinstance(assertion_id, str):
                continue
            assertion, assertion_errors = _assertion_target(
                root=root,
                reference=reference,
                assertion_id=assertion_id,
                label=f"claim_references[{index}]",
            )
            errors.extend(assertion_errors)
            if assertion is not None and not assertion_errors:
                resolved_assertions[index] = assertion

        limitations = data.get("limitations")
        if isinstance(limitations, list):
            for index, limitation in enumerate(limitations):
                if not isinstance(limitation, dict):
                    continue
                reference = limitation.get("assertion_ref")
                assertion_id = limitation.get("assertion_id")
                if not isinstance(reference, str) or not isinstance(assertion_id, str):
                    continue
                _assertion, assertion_errors = _assertion_target(
                    root=root,
                    reference=reference,
                    assertion_id=assertion_id,
                    label=f"limitations[{index}]",
                )
                errors.extend(assertion_errors)

    for industry_index, industry in enumerate(industries):
        if not isinstance(industry, dict):
            continue
        industry_status = industry.get("status")
        if not isinstance(industry_status, str) or industry_status not in {
            "deployed",
            "piloted",
        }:
            continue
        industry_name = industry.get("name")
        industry_claims = industry.get("claim_references")
        if not isinstance(industry_name, str) or not isinstance(industry_claims, list):
            continue
        if root is None:
            errors.append(
                f"  industries[{industry_index}] status {industry_status!r} "
                "requires repository_root to verify relevant assertion evidence"
            )
            continue
        qualifying_industry_claim = False
        for reference in industry_claims:
            if not isinstance(reference, str):
                continue
            claim_index = claim_indexes_by_id.get(reference)
            if claim_index is None:
                continue
            claim = claims[claim_index]
            if not isinstance(claim, dict):
                continue
            claim_scope = claim.get("scope")
            if not isinstance(claim_scope, str) or claim_scope not in {
                "deployment",
                "adoption",
            }:
                continue
            claim_posture = claim.get("claim_posture")
            if not isinstance(claim_posture, str) or claim_posture not in {
                "implemented",
                "partial",
            }:
                continue
            if _verified_fact_matches(
                resolved_assertions.get(claim_index),
                predicate="industry_status",
                subject=industry_name,
                project_repository=(
                    canonical_repository
                    if isinstance(canonical_repository, str)
                    else ""
                ),
                value=industry_status,
                require_current_state=True,
            ):
                qualifying_industry_claim = True
                break
        if not qualifying_industry_claim:
            errors.append(
                f"  industries[{industry_index}] status {industry_status!r} requires "
                "an implemented or partial deployment/adoption claim backed by a "
                "verified fresh current_state industry_status fact for that industry"
            )

    implementation_status = data.get("implementation_status")
    if isinstance(implementation_status, str):
        qualifying_status_claims = [
            index
            for index, claim in enumerate(claims)
            if isinstance(claim, dict)
            and claim.get("scope") == "status"
            and isinstance(claim.get("claim_posture"), str)
            and claim.get("claim_posture") in {"implemented", "partial"}
        ]
        if root is None:
            errors.append(
                f"  implementation_status {implementation_status!r} requires "
                "repository_root to verify assertion evidence"
            )
        elif not isinstance(canonical_repository, str) or not any(
            _verified_fact_matches(
                resolved_assertions.get(index),
                predicate="implementation_status",
                subject=canonical_repository,
                value=implementation_status,
            )
            for index in qualifying_status_claims
        ):
            errors.append(
                f"  implementation_status {implementation_status!r} requires at "
                "least one implemented or partial status claim backed by a verified "
                "assertion whose fact matches the canonical project identity and "
                "implementation_status"
            )

    deployment_status = data.get("deployment_status")
    allowed_postures = (
        _DEPLOYMENT_POSTURES.get(deployment_status)
        if isinstance(deployment_status, str)
        else None
    )
    if allowed_postures is not None and isinstance(deployment_status, str):
        qualifying = [
            index
            for index, claim in enumerate(claims)
            if isinstance(claim, dict)
            and claim.get("scope") == "deployment"
            and isinstance(claim.get("claim_posture"), str)
            and claim.get("claim_posture") in allowed_postures
        ]
        if root is None:
            errors.append(
                f"  deployment_status {deployment_status!r} requires repository_root "
                "to verify assertion evidence"
            )
        elif not any(
            _verified_fact_matches(
                resolved_assertions.get(index),
                predicate="deployment_status",
                subject=(
                    canonical_repository
                    if isinstance(canonical_repository, str)
                    else ""
                ),
                value=deployment_status,
                require_current_state=deployment_status in {"pilot", "public"},
            )
            for index in qualifying
        ):
            if deployment_status in {"pilot", "public"}:
                errors.append(
                    f"  deployment_status {deployment_status!r} requires at least one "
                    "qualifying deployment claim backed by a verified fresh "
                    "current_state assertion whose fact exactly matches deployment_status"
                )
            else:
                errors.append(
                    f"  deployment_status {deployment_status!r} requires at least one "
                    "qualifying deployment claim that resolves to a verified assertion "
                    "whose fact exactly matches deployment_status"
                )
    return errors


def validate_file(
    filepath: Path,
    schema_path: Path | None = None,
    *,
    repository_root: str | Path | None = None,
    actual_repository: str | None = None,
) -> tuple[bool, list[str]]:
    """Validate a file against a JSON Schema. Returns (pass, errors)."""
    if schema_path is None:
        schema_path = detect_schema(filepath)
    if schema_path is None:
        return False, [f"Cannot detect schema for {filepath.name}"]

    data = load_data(filepath)
    with open(schema_path) as f:
        schema = json.load(f)

    validator = jsonschema.Draft202012Validator(
        schema,
        format_checker=FORMAT_CHECKER,
    )
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))

    messages = []
    for err in errors:
        path = ".".join(str(p) for p in err.absolute_path) or "(root)"
        messages.append(f"  {path}: {err.message}")

    if schema.get("$id") == PROJECT_RECORD_SCHEMA_ID:
        messages.extend(
            project_record_semantic_errors(
                data,
                repository_root=repository_root,
                actual_repository=actual_repository,
            )
        )

    return len(messages) == 0, messages


def main():
    parser = argparse.ArgumentParser(description="Validate files against JSON Schema")
    parser.add_argument("files", nargs="*", help="Files to validate")
    parser.add_argument("--schema", type=str, default=None,
                        help="Explicit schema file to use")
    parser.add_argument("--all-examples", action="store_true",
                        help="Validate all example files")
    parser.add_argument(
        "--ignore-missing",
        action="store_true",
        help="Skip missing explicit paths instead of failing validation",
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=None,
        help="Repository root for strict local project-record integrity checks",
    )
    parser.add_argument(
        "--actual-repository",
        default=None,
        help="Checked-out GitHub owner/name for canonical redirect identity checks",
    )
    args = parser.parse_args()

    targets = []
    if args.all_examples:
        targets.extend(sorted(EXAMPLES_DIR.glob("*.json")))
        targets.extend(sorted(EXAMPLES_DIR.glob("*.yaml")))
    targets.extend(Path(f) for f in args.files)

    if not targets:
        parser.print_help()
        return 0

    schema_override = Path(args.schema) if args.schema else None
    total_pass = 0
    total_fail = 0

    for filepath in targets:
        if not filepath.exists():
            if args.ignore_missing:
                print(f"SKIP {filepath}: not found")
            else:
                print(f"FAIL {filepath}: not found")
                total_fail += 1
            continue

        repository_root = args.repository_root
        if (
            repository_root is None
            and filepath.resolve() == PROJECT_RECORD_EXAMPLE.resolve()
        ):
            repository_root = PROJECT_RECORD_FIXTURE_ROOT
        ok, errors = validate_file(
            filepath,
            schema_override,
            repository_root=repository_root,
            actual_repository=args.actual_repository,
        )
        status = "PASS" if ok else "FAIL"
        print(f"{status} {filepath.name}")

        if not ok:
            for err in errors:
                print(err)
            total_fail += 1
        else:
            total_pass += 1

    print(f"\n{total_pass} passed, {total_fail} failed")
    return 1 if total_fail > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
