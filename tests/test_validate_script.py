"""Tests for the schema validation helper script."""

import hashlib
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts import validate as validate_script

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = ROOT / "schemas"
PROJECT_RECORD_EXAMPLE = validate_script.EXAMPLES_DIR / "project-record-v1-example.yaml"
PROJECT_RECORD_FIXTURE = validate_script.EXAMPLES_DIR / "project-record-v1-fixture"


def run_main(monkeypatch, capsys, *args):
    monkeypatch.setattr(sys, "argv", ["validate.py", *(str(arg) for arg in args)])
    exit_code = validate_script.main()
    return exit_code, capsys.readouterr()


def test_detect_schema_prefers_seed_v11_before_seed_v1():
    schema = validate_script.detect_schema(Path("seed-v1.1-example.yaml"))

    assert schema is not None
    assert schema.name == "seed-v1.1.schema.json"


def test_detect_schema_returns_none_for_unknown_file():
    assert validate_script.detect_schema(Path("unmapped-contract.json")) is None


def test_load_data_reads_json_and_yaml(tmp_path):
    json_file = tmp_path / "sample.json"
    yaml_file = tmp_path / "sample.yaml"
    json_file.write_text(json.dumps({"kind": "json"}))
    yaml_file.write_text("kind: yaml\ncount: 2\n")

    assert validate_script.load_data(json_file) == {"kind": "json"}
    assert validate_script.load_data(yaml_file) == {"kind": "yaml", "count": 2}


def test_load_data_exits_when_yaml_dependency_is_missing(tmp_path, monkeypatch, capsys):
    yaml_file = tmp_path / "sample.yaml"
    yaml_file.write_text("kind: yaml\n")
    monkeypatch.setattr(validate_script, "yaml", None)

    with pytest.raises(SystemExit) as excinfo:
        validate_script.load_data(yaml_file)

    assert excinfo.value.code == 1
    assert "pyyaml not installed" in capsys.readouterr().err


def test_validate_file_reports_unknown_schema(tmp_path):
    target = tmp_path / "unknown.json"
    target.write_text("{}")

    ok, errors = validate_script.validate_file(target)

    assert ok is False
    assert errors == ["Cannot detect schema for unknown.json"]


def test_validate_file_accepts_explicit_schema_override(tmp_path):
    target = tmp_path / "contract.json"
    target.write_text(
        json.dumps(
            {
                "event": "product.release",
                "source": {"organ": "ORGAN-II"},
                "target": {"organ": "ORGAN-IV"},
                "payload": {
                    "version": "1.0.0",
                    "repo": "organvm/schema-definitions",
                    "changelog_url": "https://example.test/changelog",
                },
            }
        )
    )

    ok, errors = validate_script.validate_file(
        target,
        SCHEMAS_DIR / "dispatch-payload.schema.json",
    )

    assert ok is True
    assert errors == []


def test_validate_file_formats_nested_errors_in_path_order(tmp_path):
    target = tmp_path / "dispatch-invalid.json"
    target.write_text(
        json.dumps(
            {
                "event": "theory.published",
                "source": {"organ": "ORGAN-I"},
                "target": {"organ": "ORGAN-II"},
                "payload": {
                    "artifact_id": "theory-001",
                    "title": "Foundational Theory",
                    "source_repo": "recursive-engine",
                },
                "metadata": {
                    "priority": "urgent",
                    "ttl_seconds": -1,
                },
            }
        )
    )

    ok, errors = validate_script.validate_file(target)

    assert ok is False
    assert len(errors) == 2
    assert errors[0].startswith("  metadata.priority:")
    assert "'urgent'" in errors[0]
    assert errors[1].startswith("  metadata.ttl_seconds:")
    assert "less than the minimum" in errors[1]


def test_project_record_semantics_reject_duplicate_route_modes_and_paths(tmp_path):
    example = validate_script.EXAMPLES_DIR / "project-record-v1-example.yaml"
    baseline = validate_script.load_data(example)

    duplicate_mode = json.loads(json.dumps(baseline))
    duplicate_mode["audience_routes"][1]["mode"] = duplicate_mode[
        "audience_routes"
    ][0]["mode"]

    duplicate_path = json.loads(json.dumps(baseline))
    duplicate_path["audience_routes"][1]["path"] = duplicate_path[
        "audience_routes"
    ][0]["path"]

    for name, candidate, expected in (
        ("mode", duplicate_mode, "duplicate mode values: general"),
        (
            "path",
            duplicate_path,
            "duplicate path values: docs/audiences/general.md",
        ),
    ):
        target = tmp_path / f"project-record-duplicate-{name}.json"
        target.write_text(json.dumps(candidate))

        ok, errors = validate_script.validate_file(target)

        assert ok is False
        assert any(expected in error for error in errors)


def test_project_record_semantics_reject_duplicate_claim_ids(tmp_path):
    baseline = validate_script.load_data(PROJECT_RECORD_EXAMPLE)
    baseline["claim_references"][1]["id"] = baseline["claim_references"][0]["id"]
    target = tmp_path / "project-record-duplicate-claim.json"
    target.write_text(json.dumps(baseline))

    ok, errors = validate_script.validate_file(target)

    assert ok is False
    assert any("duplicate id values: project-status" in error for error in errors)


def test_project_record_semantics_reject_duplicate_limitation_ids(tmp_path):
    baseline = validate_script.load_data(PROJECT_RECORD_EXAMPLE)
    baseline["limitations"].append(json.loads(json.dumps(baseline["limitations"][0])))
    target = tmp_path / "project-record-duplicate-limitation.json"
    target.write_text(json.dumps(baseline))

    ok, errors = validate_script.validate_file(
        target,
        repository_root=PROJECT_RECORD_FIXTURE,
    )

    assert ok is False
    assert any("limitations: duplicate id values: example-only" in error for error in errors)


def test_project_record_semantics_reject_duplicate_industry_names(tmp_path):
    baseline = validate_script.load_data(PROJECT_RECORD_EXAMPLE)
    baseline["industries"] = [
        {"name": "Education", "status": "proposed"},
        {
            "name": "Education",
            "status": "piloted",
            "claim_references": ["project-status"],
        },
    ]
    target = tmp_path / "project-record-duplicate-industry.json"
    target.write_text(json.dumps(baseline))

    ok, errors = validate_script.validate_file(
        target,
        repository_root=PROJECT_RECORD_FIXTURE,
    )

    assert ok is False
    assert any("industries: duplicate name values: Education" in error for error in errors)

    baseline["industries"][1]["name"] = "education"
    target.write_text(json.dumps(baseline))
    ok, errors = validate_script.validate_file(
        target,
        repository_root=PROJECT_RECORD_FIXTURE,
    )
    assert ok is False
    assert any("industries: duplicate name values: Education" in error for error in errors)


def test_former_repository_identities_are_disjoint_and_case_unique(tmp_path):
    baseline = validate_script.load_data(PROJECT_RECORD_EXAMPLE)
    target = tmp_path / "project-record-former-repositories.json"

    for former in (
        ["ORGANVM/EXAMPLE-PROJECT"],
        ["organvm/old-project", "ORGANVM/OLD-PROJECT"],
    ):
        baseline["former_repositories"] = former
        target.write_text(json.dumps(baseline))
        ok, errors = validate_script.validate_file(
            target,
            repository_root=PROJECT_RECORD_FIXTURE,
        )
        assert ok is False
        assert any("former_repositories" in error for error in errors)


def test_project_record_semantics_reject_duplicate_search_intents(tmp_path):
    baseline = validate_script.load_data(PROJECT_RECORD_EXAMPLE)
    baseline["search_intents"].append(
        {"intent": "informational", "terms": ["different terms"]}
    )
    target = tmp_path / "project-record-duplicate-search-intent.json"
    target.write_text(json.dumps(baseline))

    ok, errors = validate_script.validate_file(
        target,
        repository_root=PROJECT_RECORD_FIXTURE,
    )

    assert ok is False
    assert any(
        "search_intents: duplicate intent values: informational" in error
        for error in errors
    )


def test_project_record_semantics_resolve_industry_claim_ids(tmp_path):
    baseline = validate_script.load_data(PROJECT_RECORD_EXAMPLE)
    baseline["industries"] = [
        {
            "name": "Education",
            "status": "proposed",
            "claim_references": ["missing-claim"],
        }
    ]
    target = tmp_path / "project-record-industry-claim.json"
    target.write_text(json.dumps(baseline))

    ok, errors = validate_script.validate_file(target)

    assert ok is False
    assert any(
        "industries[0].claim_references[0] must resolve to exactly one"
        in error
        for error in errors
    )


def test_deployed_industry_requires_relevant_substantiated_evidence(tmp_path):
    repository_root = tmp_path / "repository"
    shutil.copytree(PROJECT_RECORD_FIXTURE, repository_root)
    baseline = validate_script.load_data(PROJECT_RECORD_EXAMPLE)
    baseline["industries"] = [
        {
            "name": "Education",
            "status": "deployed",
            "claim_references": ["authorship-boundary"],
        }
    ]
    target = tmp_path / "project-record-deployed-industry.json"
    target.write_text(json.dumps(baseline))

    ok, errors = validate_script.validate_file(
        target,
        repository_root=repository_root,
    )
    assert ok is False
    assert any("current_state industry_status fact" in error for error in errors)

    owner_reference = "docs/evidence/sources/education-owner.txt"
    owner_bytes = b"The owner reports the Education deployment.\n"
    (repository_root / owner_reference).write_bytes(owner_bytes)
    verifier_reference = "docs/evidence/sources/education-verifier.txt"
    verifier_bytes = b"The verifier confirms the Education deployment.\n"
    (repository_root / verifier_reference).write_bytes(verifier_bytes)
    assertion_reference = "docs/evidence/claims/education-deployment.json"
    assertion_path = repository_root / assertion_reference
    assertion = {
        "contract_name": "assertion-evidence.v1",
        "contract_version": 1,
        "assertion_id": "project_record_fixture_education_deployment",
        "assertion_class": "current_state",
        "statement": "The project is deployed for the Education industry.",
        "fact": {
            "predicate": "industry_status",
            "subject": "Education",
            "project_repository": baseline["canonical_repository"],
            "value": "deployed",
        },
        "verification_state": "verified",
        "freshness": {
            "verified_at": datetime.now(UTC).isoformat(),
            "max_age_seconds": 3600,
            "status": "fresh",
        },
        "evidence_references": [
            {
                "evidence_id": "project_record_fixture_education_owner",
                "independence_group": "project-record-fixture-education-owner",
                "evidence_type": "owner_record",
                "reference": owner_reference,
                "body_hash": "sha256:" + hashlib.sha256(owner_bytes).hexdigest(),
            },
            {
                "evidence_id": "project_record_fixture_education_verifier",
                "independence_group": "project-record-fixture-education-verifier",
                "evidence_type": "fresh_verifier_receipt",
                "reference": verifier_reference,
                "body_hash": "sha256:" + hashlib.sha256(verifier_bytes).hexdigest(),
            },
        ],
    }
    assertion["evidence_references"][1]["observed_at"] = assertion["freshness"][
        "verified_at"
    ]
    assertion_path.write_text(json.dumps(assertion))
    baseline["claim_references"].append(
        {
            "id": "education-deployment",
            "assertion_contract": "assertion-evidence.v1",
            "assertion_id": assertion["assertion_id"],
            "assertion_ref": assertion_reference,
            "scope": "adoption",
            "claim_posture": "implemented",
        }
    )
    baseline["industries"][0]["claim_references"] = ["education-deployment"]
    target.write_text(json.dumps(baseline))

    ok, errors = validate_script.validate_file(
        target,
        repository_root=repository_root,
    )
    assert ok is True
    assert errors == []

    wrong_subject = json.loads(json.dumps(assertion))
    wrong_subject["fact"]["subject"] = "Healthcare"
    assertion_path.write_text(json.dumps(wrong_subject))
    ok, errors = validate_script.validate_file(
        target,
        repository_root=repository_root,
    )
    assert ok is False
    assert any("current_state industry_status fact" in error for error in errors)

    wrong_project = json.loads(json.dumps(assertion))
    wrong_project["fact"]["project_repository"] = "organvm/different-project"
    assertion_path.write_text(json.dumps(wrong_project))
    ok, errors = validate_script.validate_file(
        target,
        repository_root=repository_root,
    )
    assert ok is False
    assert any("current_state industry_status fact" in error for error in errors)


def test_strict_project_record_checks_industry_paths(tmp_path):
    repository_root = tmp_path / "repository"
    shutil.copytree(PROJECT_RECORD_FIXTURE, repository_root)
    baseline = validate_script.load_data(PROJECT_RECORD_EXAMPLE)
    baseline["industries"] = [
        {
            "name": "Education",
            "status": "proposed",
            "path": "docs/industries/education.md",
        }
    ]
    target = tmp_path / "project-record-industry-path.json"
    target.write_text(json.dumps(baseline))

    ok, errors = validate_script.validate_file(
        target,
        repository_root=repository_root,
    )
    assert ok is False
    assert any("industries[0].path does not exist" in error for error in errors)

    industry_path = repository_root / "docs/industries/education.md"
    industry_path.parent.mkdir(parents=True)
    industry_path.write_text("# Education\n")
    ok, errors = validate_script.validate_file(
        target,
        repository_root=repository_root,
    )
    assert ok is True
    assert errors == []


def test_strict_project_record_example_binds_nested_fixture_bytes():
    ok, errors = validate_script.validate_file(
        PROJECT_RECORD_EXAMPLE,
        repository_root=PROJECT_RECORD_FIXTURE,
    )

    assert ok is True
    assert errors == []


def test_authorship_requires_a_matching_bound_fact(tmp_path):
    for field, replacement in (
        ("owner", "Unrelated Owner"),
        ("role", "unrelated role"),
        ("contributions", ["unrelated contribution"]),
        ("collaborators", ["Unrelated Collaborator"]),
        ("generated", ["unrelated generated artifact"]),
        ("inherited", ["unrelated inherited artifact"]),
        ("external", ["unrelated external artifact"]),
    ):
        candidate = validate_script.load_data(PROJECT_RECORD_EXAMPLE)
        candidate["authorship"][field] = replacement
        target = tmp_path / f"project-record-wrong-authorship-{field}.json"
        target.write_text(json.dumps(candidate))

        ok, errors = validate_script.validate_file(
            target,
            repository_root=PROJECT_RECORD_FIXTURE,
        )

        assert ok is False
        assert any("verified fact matching the canonical project" in error for error in errors)


def test_strict_checkout_binds_actual_to_canonical_repository(tmp_path):
    target = tmp_path / "project-record.yaml"
    target.write_text(PROJECT_RECORD_EXAMPLE.read_text())

    ok, errors = validate_script.validate_file(
        target,
        repository_root=PROJECT_RECORD_FIXTURE,
        actual_repository="organvm/unrelated-checkout",
    )

    assert ok is False
    assert any("must match actual_repository" in error for error in errors)


def test_project_timestamps_cannot_be_in_the_future(tmp_path):
    baseline = validate_script.load_data(PROJECT_RECORD_EXAMPLE)
    baseline["generated_at"] = "9999-12-30T00:00:00Z"
    baseline["verified_at"] = "9999-12-31T00:00:00Z"
    target = tmp_path / "project-record-future.json"
    target.write_text(json.dumps(baseline))

    ok, errors = validate_script.validate_file(
        target,
        repository_root=PROJECT_RECORD_FIXTURE,
    )

    assert ok is False
    assert any("generated_at cannot be in the future" in error for error in errors)
    assert any("verified_at cannot be in the future" in error for error in errors)

    baseline["generated_at"] = "2026-08-31T20:00:01Z"
    baseline["verified_at"] = "2026-08-31T20:00:00Z"
    target.write_text(json.dumps(baseline))
    ok, errors = validate_script.validate_file(
        target,
        repository_root=PROJECT_RECORD_FIXTURE,
    )
    assert ok is False
    assert any("generated_at must not be later" in error for error in errors)


def test_project_timestamp_overflow_does_not_abort_later_batch_target(
    tmp_path,
    monkeypatch,
    capsys,
):
    baseline = validate_script.load_data(PROJECT_RECORD_EXAMPLE)
    boundary = json.loads(json.dumps(baseline))
    boundary["verified_at"] = "9999-12-31T23:59:59-23:59"
    boundary_path = tmp_path / "project-record-boundary-time.json"
    valid_path = tmp_path / "project-record-valid.json"
    boundary_path.write_text(json.dumps(boundary))
    valid_path.write_text(json.dumps(baseline))

    exit_code, captured = run_main(
        monkeypatch,
        capsys,
        "--repository-root",
        PROJECT_RECORD_FIXTURE,
        boundary_path,
        valid_path,
    )

    assert exit_code == 1
    assert "FAIL project-record-boundary-time.json" in captured.out
    assert "normalizes safely" in captured.out
    assert "PASS project-record-valid.json" in captured.out


def test_absolute_assertion_evidence_path_is_rejected(tmp_path):
    repository_root = tmp_path / "repository"
    shutil.copytree(PROJECT_RECORD_FIXTURE, repository_root)
    baseline = validate_script.load_data(PROJECT_RECORD_EXAMPLE)
    assertion_path = repository_root / baseline["claim_references"][1]["assertion_ref"]
    assertion = json.loads(assertion_path.read_text())
    relative_reference = assertion["evidence_references"][0]["reference"]
    assertion["evidence_references"][0]["reference"] = str(
        (repository_root / relative_reference).resolve()
    )
    assertion_path.write_text(json.dumps(assertion))
    target = tmp_path / "project-record-absolute-evidence.json"
    target.write_text(json.dumps(baseline))

    ok, errors = validate_script.validate_file(
        target,
        repository_root=repository_root,
    )

    assert ok is False
    assert any("path does not exist or escapes root" in error for error in errors)


def test_windows_drive_evidence_path_is_rejected_on_posix(tmp_path):
    repository_root = tmp_path / "repository"
    shutil.copytree(PROJECT_RECORD_FIXTURE, repository_root)
    baseline = validate_script.load_data(PROJECT_RECORD_EXAMPLE)
    assertion_path = repository_root / baseline["claim_references"][0]["assertion_ref"]
    assertion = json.loads(assertion_path.read_text())
    original = repository_root / assertion["evidence_references"][0]["reference"]
    spoof = repository_root / "C:" / "status-record.txt"
    spoof.parent.mkdir()
    spoof.write_bytes(original.read_bytes())
    assertion["evidence_references"][0]["reference"] = "C:/status-record.txt"
    assertion_path.write_text(json.dumps(assertion))
    target = tmp_path / "project-record-windows-drive.json"
    target.write_text(json.dumps(baseline))

    ok, errors = validate_script.validate_file(target, repository_root=repository_root)
    assert ok is False
    assert any("path does not exist or escapes root" in error for error in errors)


def test_limitation_assertion_must_bind_the_limitation_fact(tmp_path):
    baseline = validate_script.load_data(PROJECT_RECORD_EXAMPLE)
    authorship_claim = baseline["claim_references"][1]
    baseline["limitations"][0].update(
        {
            "assertion_id": authorship_claim["assertion_id"],
            "assertion_ref": authorship_claim["assertion_ref"],
        }
    )
    target = tmp_path / "project-record-unrelated-limitation.json"
    target.write_text(json.dumps(baseline))

    ok, errors = validate_script.validate_file(
        target,
        repository_root=PROJECT_RECORD_FIXTURE,
    )
    assert ok is False
    assert any("limitation id, and statement" in error for error in errors)


def test_inference_assertions_cannot_prove_project_facts(tmp_path):
    for claim_index, expected in (
        (0, "implementation_status"),
        (1, "authorship requires"),
    ):
        repository_root = tmp_path / f"repository-{claim_index}"
        shutil.copytree(PROJECT_RECORD_FIXTURE, repository_root)
        baseline = validate_script.load_data(PROJECT_RECORD_EXAMPLE)
        claim = baseline["claim_references"][claim_index]
        assertion_path = repository_root / claim["assertion_ref"]
        assertion = json.loads(assertion_path.read_text())
        assertion["assertion_class"] = "inference"
        assertion["inference_label"] = "test inference"
        assertion_path.write_text(json.dumps(assertion))
        target = tmp_path / f"project-record-inference-{claim_index}.json"
        target.write_text(json.dumps(baseline))

        ok, errors = validate_script.validate_file(
            target,
            repository_root=repository_root,
        )
        assert ok is False
        assert any(expected in error for error in errors)


def test_implementation_status_requires_a_matching_bound_fact(tmp_path):
    baseline = validate_script.load_data(PROJECT_RECORD_EXAMPLE)
    target = tmp_path / "project-record-active.json"
    baseline["implementation_status"] = "ACTIVE"
    target.write_text(json.dumps(baseline))

    ok, errors = validate_script.validate_file(
        target,
        repository_root=PROJECT_RECORD_FIXTURE,
    )

    assert ok is False
    assert any("fact matches the canonical project identity" in error for error in errors)


def test_canonical_repository_link_must_match_identity(tmp_path):
    baseline = validate_script.load_data(PROJECT_RECORD_EXAMPLE)
    baseline["links"]["repository"] = "https://github.com/another-owner/project"
    target = tmp_path / "project-record-wrong-repository-link.json"
    target.write_text(json.dumps(baseline))

    ok, errors = validate_script.validate_file(
        target,
        repository_root=PROJECT_RECORD_FIXTURE,
    )

    assert ok is False
    assert any(
        "links.repository must resolve to canonical_repository" in error
        for error in errors
    )


def test_renamed_project_schema_still_runs_project_semantics(tmp_path):
    renamed_schema = tmp_path / "vendored-contract.json"
    renamed_schema.write_text(
        (SCHEMAS_DIR / "project-record-v1.schema.json").read_text()
    )
    baseline = validate_script.load_data(PROJECT_RECORD_EXAMPLE)
    baseline["implementation_status"] = "ACTIVE"
    target = tmp_path / "record.json"
    target.write_text(json.dumps(baseline))

    ok, errors = validate_script.validate_file(
        target,
        renamed_schema,
        repository_root=PROJECT_RECORD_FIXTURE,
    )

    assert ok is False
    assert any("implementation_status 'ACTIVE' requires" in error for error in errors)


def test_lifecycle_state_requires_a_bound_verified_assertion(tmp_path):
    repository_root = tmp_path / "repository"
    shutil.copytree(PROJECT_RECORD_FIXTURE, repository_root)
    baseline = validate_script.load_data(PROJECT_RECORD_EXAMPLE)
    deployment_claim = json.loads(json.dumps(baseline["claim_references"][0]))
    owner_reference = "docs/evidence/sources/deployment-public-owner.txt"
    owner_bytes = b"The owner records the fixture deployment as public.\n"
    (repository_root / owner_reference).write_bytes(owner_bytes)
    verifier_reference = "docs/evidence/sources/deployment-public-verifier.txt"
    verifier_bytes = b"The verifier confirms the fixture deployment is public.\n"
    (repository_root / verifier_reference).write_bytes(verifier_bytes)
    assertion_reference = "docs/evidence/claims/deployment-public.json"
    assertion_path = repository_root / assertion_reference
    assertion = {
        "contract_name": "assertion-evidence.v1",
        "contract_version": 1,
        "assertion_id": "project_record_fixture_deployment_public",
        "assertion_class": "current_state",
        "statement": "At fixture generation, the project deployment was public.",
        "fact": {
            "predicate": "deployment_status",
            "subject": baseline["canonical_repository"],
            "value": "public",
        },
        "verification_state": "verified",
        "freshness": {
            "verified_at": datetime.now(UTC).isoformat(),
            "max_age_seconds": 3600,
            "status": "fresh",
        },
        "evidence_references": [
            {
                "evidence_id": "project_record_fixture_deployment_public_owner",
                "independence_group": "project-record-fixture-owner",
                "evidence_type": "owner_record",
                "reference": owner_reference,
                "body_hash": "sha256:" + hashlib.sha256(owner_bytes).hexdigest(),
            },
            {
                "evidence_id": "project_record_fixture_deployment_public_verifier",
                "independence_group": "project-record-fixture-verifier",
                "evidence_type": "fresh_verifier_receipt",
                "reference": verifier_reference,
                "body_hash": "sha256:" + hashlib.sha256(verifier_bytes).hexdigest(),
            },
        ],
    }
    assertion["evidence_references"][1]["observed_at"] = assertion["freshness"][
        "verified_at"
    ]
    assertion_path.write_text(json.dumps(assertion))
    deployment_claim.update(
        {
            "id": "deployment-lifecycle",
            "assertion_id": assertion["assertion_id"],
            "assertion_ref": assertion_reference,
            "scope": "deployment",
            "claim_posture": "implemented",
        }
    )
    baseline["claim_references"].append(deployment_claim)
    baseline["deployment_status"] = "public"
    target = tmp_path / "project-record-public.json"
    target.write_text(json.dumps(baseline))

    ok, errors = validate_script.validate_file(
        target,
        repository_root=repository_root,
    )
    assert ok is True
    assert errors == []

    aliased_source = json.loads(json.dumps(assertion))
    aliased_source["evidence_references"][1]["reference"] = owner_reference.replace(
        "deployment-public-owner.txt", "./deployment-public-owner.txt"
    )
    aliased_source["evidence_references"][1]["body_hash"] = aliased_source[
        "evidence_references"
    ][0]["body_hash"]
    assertion_path.write_text(json.dumps(aliased_source))
    ok, errors = validate_script.validate_file(
        target,
        repository_root=repository_root,
    )
    assert ok is False
    assert any("distinct source files" in error for error in errors)
    assertion_path.write_text(json.dumps(assertion))

    wrong_project = json.loads(json.dumps(assertion))
    wrong_project["fact"]["subject"] = "organvm/different-project"
    assertion_path.write_text(json.dumps(wrong_project))
    ok, errors = validate_script.validate_file(
        target,
        repository_root=repository_root,
    )
    assert ok is False
    assert any("fact exactly matches deployment_status" in error for error in errors)
    assertion_path.write_text(json.dumps(assertion))

    mismatched = json.loads(json.dumps(assertion))
    mismatched["fact"]["value"] = "not-deployed"
    assertion_path.write_text(json.dumps(mismatched))
    ok, errors = validate_script.validate_file(
        target,
        repository_root=repository_root,
    )
    assert ok is False
    assert any("fact exactly matches deployment_status" in error for error in errors)
    assertion_path.write_text(json.dumps(assertion))

    historical = json.loads(json.dumps(assertion))
    historical["assertion_class"] = "historical_record"
    del historical["freshness"]
    assertion_path.write_text(json.dumps(historical))
    ok, errors = validate_script.validate_file(
        target,
        repository_root=repository_root,
    )
    assert ok is False
    assert any("verified fresh current_state" in error for error in errors)

    retired_record = json.loads(json.dumps(historical))
    retired_record["fact"]["value"] = "retired"
    assertion_path.write_text(json.dumps(retired_record))
    retired = json.loads(json.dumps(baseline))
    retired["deployment_status"] = "retired"
    retired["claim_references"][-1]["claim_posture"] = "contradicted"
    target.write_text(json.dumps(retired))
    ok, errors = validate_script.validate_file(
        target,
        repository_root=repository_root,
    )
    assert ok is True
    assert errors == []

    retired_inference = json.loads(json.dumps(retired_record))
    retired_inference["assertion_class"] = "inference"
    retired_inference["inference_label"] = "retirement inference"
    assertion_path.write_text(json.dumps(retired_inference))
    ok, errors = validate_script.validate_file(
        target,
        repository_root=repository_root,
    )
    assert ok is False
    assert any("fact exactly matches deployment_status" in error for error in errors)

    assertion_path.write_text(json.dumps(assertion))
    target.write_text(json.dumps(baseline))

    missing = json.loads(json.dumps(baseline))
    missing["claim_references"][-1]["assertion_ref"] = (
        "docs/evidence/claims/missing.json"
    )
    target.write_text(json.dumps(missing))
    ok, errors = validate_script.validate_file(
        target,
        repository_root=repository_root,
    )
    assert ok is False
    assert any("assertion path does not exist" in error for error in errors)
    assert any("verified fresh current_state" in error for error in errors)

    assertion["verification_state"] = "unverified"
    assertion_path.write_text(json.dumps(assertion))
    target.write_text(json.dumps(baseline))
    ok, errors = validate_script.validate_file(
        target,
        repository_root=repository_root,
    )
    assert ok is False
    assert any("verified fresh current_state" in error for error in errors)

    assertion["verification_state"] = "verified"
    assertion["assertion_id"] = "different-assertion"
    assertion_path.write_text(json.dumps(assertion))
    ok, errors = validate_script.validate_file(
        target,
        repository_root=repository_root,
    )
    assert ok is False
    assert any("assertion_id does not match" in error for error in errors)

    assertion["assertion_id"] = deployment_claim["assertion_id"]
    assertion["contract_name"] = "different-contract.v1"
    assertion_path.write_text(json.dumps(assertion))
    ok, errors = validate_script.validate_file(
        target,
        repository_root=repository_root,
    )
    assert ok is False
    assert any("target is not assertion-evidence.v1" in error for error in errors)


def test_class_d_redirect_binds_canonical_and_actual_repository(tmp_path):
    record = validate_script.load_data(PROJECT_RECORD_EXAMPLE)
    record["documentation_class"] = "D"
    record["repository_role"] = "deployment-artifact"
    record["audience_routes"] = []
    record["redirect"] = {
        "status": "active",
        "target": "https://github.com/organvm/example-project",
    }
    target = tmp_path / "project-record-deployment.json"
    target.write_text(json.dumps(record))

    ok, errors = validate_script.validate_file(
        target,
        repository_root=PROJECT_RECORD_FIXTURE,
        actual_repository="organvm/example-deployment",
    )
    assert ok is True
    assert errors == []

    record["links"]["repository"] = "https://github.com/organvm/unrelated"
    target.write_text(json.dumps(record))
    ok, errors = validate_script.validate_file(
        target,
        repository_root=PROJECT_RECORD_FIXTURE,
        actual_repository="organvm/example-deployment",
    )
    assert ok is False
    assert any("links.repository must resolve to canonical_repository" in error for error in errors)
    record["links"]["repository"] = "https://github.com/organvm/example-project"
    target.write_text(json.dumps(record))

    ok, errors = validate_script.validate_file(
        target,
        repository_root=PROJECT_RECORD_FIXTURE,
        actual_repository="organvm/example-project",
    )
    assert ok is False
    assert any("must differ from actual_repository" in error for error in errors)

    record["redirect"]["target"] = "https://github.com/organvm/wrong-upstream"
    target.write_text(json.dumps(record))
    ok, errors = validate_script.validate_file(
        target,
        repository_root=PROJECT_RECORD_FIXTURE,
        actual_repository="organvm/example-deployment",
    )
    assert ok is False
    assert any("must resolve to canonical_repository" in error for error in errors)

    record["redirect"]["target"] = "https://github.com/organvm/example-project"
    target.write_text(json.dumps(record))
    ok, errors = validate_script.validate_file(
        target,
        repository_root=PROJECT_RECORD_FIXTURE,
    )
    assert ok is False
    assert any("requires actual_repository" in error for error in errors)

    record["redirect"]["target"] = (
        "https://github.com//organvm/example-project//"
    )
    target.write_text(json.dumps(record))
    ok, errors = validate_script.validate_file(
        target,
        repository_root=PROJECT_RECORD_FIXTURE,
        actual_repository="organvm/example-deployment",
    )
    assert ok is False
    assert any("canonical HTTPS GitHub" in error for error in errors)


def test_malformed_project_uri_does_not_abort_later_batch_targets(
    tmp_path,
    monkeypatch,
    capsys,
):
    example = validate_script.EXAMPLES_DIR / "project-record-v1-example.yaml"
    baseline = validate_script.load_data(example)
    malformed = json.loads(json.dumps(baseline))
    malformed["links"]["project_page"] = "http://["

    malformed_path = tmp_path / "project-record-malformed.json"
    valid_path = tmp_path / "project-record-valid.json"
    malformed_path.write_text(json.dumps(malformed))
    valid_path.write_text(json.dumps(baseline))

    exit_code, captured = run_main(
        monkeypatch,
        capsys,
        "--repository-root",
        PROJECT_RECORD_FIXTURE,
        malformed_path,
        valid_path,
    )

    assert exit_code == 1
    assert "FAIL project-record-malformed.json" in captured.out
    assert "is not a 'uri'" in captured.out
    assert "PASS project-record-valid.json" in captured.out


def test_malformed_project_enums_do_not_abort_later_batch_targets(
    tmp_path,
    monkeypatch,
    capsys,
):
    baseline = validate_script.load_data(PROJECT_RECORD_EXAMPLE)
    candidates = []

    malformed_role = json.loads(json.dumps(baseline))
    malformed_role["repository_role"] = ["canonical"]
    candidates.append(malformed_role)

    malformed_industry = json.loads(json.dumps(baseline))
    malformed_industry["industries"] = [
        {"name": "Education", "status": {"bad": "status"}}
    ]
    candidates.append(malformed_industry)

    malformed_status_posture = json.loads(json.dumps(baseline))
    malformed_status_posture["claim_references"][0]["claim_posture"] = {
        "bad": "posture"
    }
    candidates.append(malformed_status_posture)

    malformed_industry_scope = json.loads(json.dumps(baseline))
    malformed_industry_scope["claim_references"][0]["scope"] = ["deployment"]
    malformed_industry_scope["industries"] = [
        {
            "name": "Education",
            "status": "deployed",
            "claim_references": ["project-status"],
        }
    ]
    candidates.append(malformed_industry_scope)

    malformed_deployment_posture = json.loads(json.dumps(baseline))
    deployment_claim = json.loads(
        json.dumps(malformed_deployment_posture["claim_references"][0])
    )
    deployment_claim.update(
        {
            "id": "deployment-malformed",
            "scope": "deployment",
            "claim_posture": ["implemented"],
        }
    )
    malformed_deployment_posture["deployment_status"] = "public"
    malformed_deployment_posture["claim_references"].append(deployment_claim)
    candidates.append(malformed_deployment_posture)

    paths = []
    for index, candidate in enumerate(candidates):
        path = tmp_path / f"project-record-malformed-enum-{index}.json"
        path.write_text(json.dumps(candidate))
        paths.append(path)
    valid_path = tmp_path / "project-record-valid.json"
    valid_path.write_text(json.dumps(baseline))

    exit_code, captured = run_main(
        monkeypatch,
        capsys,
        "--repository-root",
        PROJECT_RECORD_FIXTURE,
        *paths,
        valid_path,
    )

    assert exit_code == 1
    for path in paths:
        assert f"FAIL {path.name}" in captured.out
    assert "PASS project-record-valid.json" in captured.out


def test_main_without_targets_prints_help_and_succeeds(monkeypatch, capsys):
    exit_code, captured = run_main(monkeypatch, capsys)

    assert exit_code == 0
    assert "Validate files against JSON Schema" in captured.out


def test_main_fails_missing_explicit_files_and_counts_existing_passes(
    tmp_path,
    monkeypatch,
    capsys,
):
    target = tmp_path / "contract.json"
    missing = tmp_path / "missing.json"
    target.write_text(
        json.dumps(
            {
                "event": "product.release",
                "source": {"organ": "ORGAN-II"},
                "target": {"organ": "ORGAN-IV"},
                "payload": {
                    "version": "1.0.0",
                    "repo": "organvm/schema-definitions",
                    "changelog_url": "https://example.test/changelog",
                },
            }
        )
    )

    exit_code, captured = run_main(
        monkeypatch,
        capsys,
        "--schema",
        SCHEMAS_DIR / "dispatch-payload.schema.json",
        target,
        missing,
    )

    assert exit_code == 1
    assert "PASS contract.json" in captured.out
    assert f"FAIL {missing}: not found" in captured.out
    assert "1 passed, 1 failed" in captured.out


def test_main_can_explicitly_ignore_missing_files(tmp_path, monkeypatch, capsys):
    missing = tmp_path / "optional.json"

    exit_code, captured = run_main(
        monkeypatch,
        capsys,
        "--ignore-missing",
        missing,
    )

    assert exit_code == 0
    assert f"SKIP {missing}: not found" in captured.out
    assert "0 passed, 0 failed" in captured.out


def test_main_returns_failure_and_prints_validation_errors(tmp_path, monkeypatch, capsys):
    target = tmp_path / "dispatch-invalid.json"
    target.write_text(
        json.dumps(
            {
                "event": "theory.published",
                "source": {"organ": "ORGAN-I"},
                "target": {"organ": "ORGAN-II"},
                "payload": {
                    "artifact_id": "theory-001",
                    "title": "Foundational Theory",
                    "source_repo": "recursive-engine",
                },
                "metadata": {"priority": "urgent"},
            }
        )
    )

    exit_code, captured = run_main(monkeypatch, capsys, target)

    assert exit_code == 1
    assert "FAIL dispatch-invalid.json" in captured.out
    assert "metadata.priority" in captured.out
    assert "0 passed, 1 failed" in captured.out


def test_main_all_examples_uses_json_and_yaml_globs(tmp_path, monkeypatch, capsys):
    dispatch = tmp_path / "dispatch-example.json"
    seed = tmp_path / "seed-minimal.yaml"
    dispatch.write_text(
        json.dumps(
            {
                "event": "product.release",
                "source": {"organ": "ORGAN-II"},
                "target": {"organ": "ORGAN-IV"},
                "payload": {
                    "version": "1.0.0",
                    "repo": "organvm/schema-definitions",
                    "changelog_url": "https://example.test/changelog",
                },
            }
        )
    )
    seed.write_text('schema_version: "1.0"\norgan: I\nrepo: seed\norg: meta-organvm\n')
    monkeypatch.setattr(validate_script, "EXAMPLES_DIR", tmp_path)

    exit_code, captured = run_main(monkeypatch, capsys, "--all-examples")

    assert exit_code == 0
    assert "PASS dispatch-example.json" in captured.out
    assert "PASS seed-minimal.yaml" in captured.out
    assert "2 passed, 0 failed" in captured.out


def test_main_all_examples_preserves_explicit_checkout_identity(monkeypatch, capsys):
    exit_code, captured = run_main(
        monkeypatch,
        capsys,
        "--all-examples",
        "--actual-repository",
        "organvm/unrelated-checkout",
    )

    assert exit_code == 1
    assert "FAIL project-record-v1-example.yaml" in captured.out
    assert "must match actual_repository" in captured.out
