"""Test JSON Schema definitions against example files."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from scripts.schema_formats import FORMAT_CHECKER

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"
EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


def load_schema(name: str) -> dict:
    with open(SCHEMAS_DIR / name) as f:
        return json.load(f)


def validate(data: Any, schema: dict) -> list[str]:
    validator = jsonschema.Draft202012Validator(
        schema,
        format_checker=FORMAT_CHECKER,
    )
    return [e.message for e in validator.iter_errors(data)]


def _patterns(value: Any):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "pattern" and isinstance(item, str):
                yield item
            yield from _patterns(item)
    elif isinstance(value, list):
        for item in value:
            yield from _patterns(item)


def test_all_anchored_schema_patterns_require_absolute_end_of_input():
    hardened_suffix = r"$(?![\s\S])"
    anchored_patterns = []
    for schema_path in SCHEMAS_DIR.glob("*.json"):
        anchored_patterns.extend(
            pattern for pattern in _patterns(load_schema(schema_path.name)) if "$" in pattern
        )
    assert anchored_patterns
    assert all(pattern.endswith(hardened_suffix) for pattern in anchored_patterns)


def test_digest_patterns_reject_final_newlines_across_contracts():
    source = json.loads((EXAMPLES_DIR / "source-envelope-v1-example.json").read_text())
    source["body_hash"] += "\n"
    assert validate(source, load_schema("source-envelope.v1.schema.json"))

    coverage = json.loads(
        (EXAMPLES_DIR / "coverage-receipt-v1-example.json").read_text()
    )
    coverage["receipt_hash"] += "\n"
    assert validate(coverage, load_schema("coverage-receipt.v1.schema.json"))


class TestRegistrySchema:
    def test_example_validates(self):
        schema = load_schema("registry-v2.schema.json")
        with open(EXAMPLES_DIR / "registry-minimal.json") as f:
            data = json.load(f)
        assert validate(data, schema) == []

    def test_missing_version_fails(self):
        schema = load_schema("registry-v2.schema.json")
        data = {"organs": {}}
        errors = validate(data, schema)
        assert any("version" in e for e in errors)

    def test_invalid_organ_key_fails(self):
        schema = load_schema("registry-v2.schema.json")
        data = {
            "version": "2.0",
            "schema_version": "0.5",
            "organs": {
                "BAD-KEY": {"name": "Bad", "repositories": []}
            },
        }
        errors = validate(data, schema)
        assert len(errors) > 0

    def test_repo_missing_required_fails(self):
        schema = load_schema("registry-v2.schema.json")
        data = {
            "version": "2.0",
            "schema_version": "0.5",
            "organs": {
                "ORGAN-I": {
                    "name": "Theory",
                    "repositories": [{"name": "test"}],
                }
            },
        }
        errors = validate(data, schema)
        assert len(errors) > 0


class TestProjectRecordSchema:
    def test_schema_is_valid_draft_2020_12(self):
        jsonschema.Draft202012Validator.check_schema(
            load_schema("project-record-v1.schema.json"),
        )

    def test_implementation_status_definitions_are_normative(self):
        schema = load_schema("project-record-v1.schema.json")
        statuses = {
            item["const"]: item["description"]
            for item in schema["properties"]["implementation_status"]["oneOf"]
        }
        assert set(statuses) == {
            "ACTIVE",
            "PROTOTYPE",
            "SKELETON",
            "DESIGN_ONLY",
            "ARCHIVED",
        }
        assert "does not imply deployment" in statuses["ACTIVE"]
        assert "little substantive domain behavior" in statuses["SKELETON"]
        assert "without substantive executable domain behavior" in statuses["DESIGN_ONLY"]

    def test_claim_scope_vocabulary_is_normative(self):
        schema = load_schema("project-record-v1.schema.json")
        scopes = {
            item["const"]: item["description"]
            for item in schema["$defs"]["claim_reference"]["properties"]["scope"][
                "oneOf"
            ]
        }
        assert set(scopes) == {
            "identity",
            "status",
            "capability",
            "authorship",
            "deployment",
            "adoption",
            "performance",
            "outcome",
            "limitation",
            "rights",
            "provenance",
        }

    def test_example_validates(self):
        schema = load_schema("project-record-v1.schema.json")
        with open(EXAMPLES_DIR / "project-record-v1-example.yaml") as f:
            data = yaml.safe_load(f)
        assert validate(data, schema) == []

    def test_class_a_requires_all_five_routes(self):
        schema = load_schema("project-record-v1.schema.json")
        with open(EXAMPLES_DIR / "project-record-v1-example.yaml") as f:
            data = yaml.safe_load(f)
        data["documentation_class"] = "A"
        assert validate(data, schema)

    def test_deployed_industry_requires_claim_reference(self):
        schema = load_schema("project-record-v1.schema.json")
        with open(EXAMPLES_DIR / "project-record-v1-example.yaml") as f:
            data = yaml.safe_load(f)
        data["industries"] = [{"name": "Education", "status": "deployed"}]
        errors = validate(data, schema)
        assert any("claim_references" in error for error in errors)

    def test_invalid_uri_and_timestamps_fail_format_validation(self):
        schema = load_schema("project-record-v1.schema.json")
        with open(EXAMPLES_DIR / "project-record-v1-example.yaml") as f:
            data = yaml.safe_load(f)
        data["links"]["project_page"] = "not a URI"
        data["generated_at"] = "not a timestamp"
        data["verified_at"] = "2026-08-31"

        errors = validate(data, schema)
        assert any("uri" in error for error in errors)
        assert sum("date-time" in error for error in errors) == 2

    def test_malformed_uri_authority_is_a_validation_error_not_an_exception(self):
        schema = load_schema("project-record-v1.schema.json")
        with open(EXAMPLES_DIR / "project-record-v1-example.yaml") as f:
            data = yaml.safe_load(f)
        data["links"]["project_page"] = "http://["

        assert any("uri" in error for error in validate(data, schema))

    def test_generic_uri_accepts_authority_without_a_path(self):
        schema = {"type": "string", "format": "uri"}

        for value in ("custom://registry", "file://registry-host"):
            assert validate(value, schema) == []

    def test_generic_uri_rejects_malformed_authority_ports(self):
        schema = {"type": "string", "format": "uri"}

        for value in (
            "custom://registry:notaport",
            "custom://registry:99999",
        ):
            assert validate(value, schema), value

    def test_uri_rejects_controls_and_malformed_component_escapes(self):
        schema = {"type": "string", "format": "uri"}

        for value in (
            "https://example.test/\x00artifact",
            "https://example.test/\x1fartifact",
            "https://example.test/%ZZ",
            "https://example.test/%0",
            "https://exa|mple.test/artifact",
            "https://user@@example.test/artifact",
        ):
            assert validate(value, schema), value

        assert validate(
            "https://example.test/%7Eartifact?separator=%20",
            schema,
        ) == []
        assert validate(
            "https://user%40domain@example.test/artifact",
            schema,
        ) == []

    def test_timestamps_require_the_documented_rfc3339_subset(self):
        schema = load_schema("project-record-v1.schema.json")
        with open(EXAMPLES_DIR / "project-record-v1-example.yaml") as f:
            baseline = yaml.safe_load(f)

        for invalid in (
            "20260831T200000Z",
            "2026-08-31 20:00:00Z",
            "2026-08-31T20:00:00+0000",
            "2026-02-30T20:00:00Z",
        ):
            candidate = yaml.safe_load(yaml.safe_dump(baseline))
            candidate["generated_at"] = invalid
            assert any("date-time" in error for error in validate(candidate, schema)), invalid

    def test_project_identifiers_and_local_paths_reject_final_newlines(self):
        schema = load_schema("project-record-v1.schema.json")
        with open(EXAMPLES_DIR / "project-record-v1-example.yaml") as f:
            baseline = yaml.safe_load(f)

        candidates = []
        project_id = yaml.safe_load(yaml.safe_dump(baseline))
        project_id["project_id"] += "\n"
        candidates.append(project_id)

        claim_id = yaml.safe_load(yaml.safe_dump(baseline))
        claim_id["claim_references"][0]["id"] += "\n"
        candidates.append(claim_id)

        repository = yaml.safe_load(yaml.safe_dump(baseline))
        repository["canonical_repository"] += "\n"
        candidates.append(repository)

        route_path = yaml.safe_load(yaml.safe_dump(baseline))
        route_path["audience_routes"][0]["path"] += "\n"
        candidates.append(route_path)

        repository_link = yaml.safe_load(yaml.safe_dump(baseline))
        repository_link["links"]["repository"] += "\n"
        candidates.append(repository_link)

        documentation_link = yaml.safe_load(yaml.safe_dump(baseline))
        documentation_link["links"]["documentation"] = (
            "https://docs.example.test/project\n"
        )
        candidates.append(documentation_link)

        demo_link = yaml.safe_load(yaml.safe_dump(baseline))
        demo_link["links"]["demo"] = "https://demo.example.test/project\n"
        candidates.append(demo_link)

        for candidate in candidates:
            assert validate(candidate, schema)

    def test_class_a_requires_evidence_link(self):
        schema = load_schema("project-record-v1.schema.json")
        with open(EXAMPLES_DIR / "project-record-v1-example.yaml") as f:
            data = yaml.safe_load(f)
        data["documentation_class"] = "A"
        data["audience_routes"] = [
            *data["audience_routes"],
            {
                "mode": "humanities",
                "path": "docs/audiences/humanities.md",
                "primary_question": "What concepts and traditions does it engage?",
                "surface": "public",
            },
            {
                "mode": "business",
                "path": "docs/audiences/business.md",
                "primary_question": "What operational problem does it address?",
                "surface": "public",
            },
        ]
        del data["links"]["evidence"]

        assert any("evidence" in error for error in validate(data, schema))

    def test_class_b_requires_evidence_link(self):
        schema = load_schema("project-record-v1.schema.json")
        with open(EXAMPLES_DIR / "project-record-v1-example.yaml") as f:
            data = yaml.safe_load(f)
        del data["links"]["evidence"]

        assert any("evidence" in error for error in validate(data, schema))

    def test_link_policy_allows_local_or_http_docs_and_rejects_other_schemes(self):
        schema = load_schema("project-record-v1.schema.json")
        with open(EXAMPLES_DIR / "project-record-v1-example.yaml") as f:
            baseline = yaml.safe_load(f)

        for key in ("documentation", "evidence"):
            for invalid in ("javascript:alert(1)", "mailto:docs@example.test", "/tmp/doc.md"):
                candidate = yaml.safe_load(yaml.safe_dump(baseline))
                candidate["links"][key] = invalid
                assert validate(candidate, schema), (key, invalid)

        remote = yaml.safe_load(yaml.safe_dump(baseline))
        remote["links"]["documentation"] = "https://docs.example.test/project"
        remote["links"]["evidence"] = "http://evidence.example.test/record"
        assert validate(remote, schema) == []

        invalid_web = yaml.safe_load(yaml.safe_dump(baseline))
        invalid_web["links"]["project_page"] = "urn:project:example"
        invalid_web["redirect"] = {
            "status": "planned",
            "target": "javascript:alert(1)",
        }
        errors = validate(invalid_web, schema)
        assert len(errors) >= 2

    def test_class_d_and_deployment_role_require_redirect(self):
        schema = load_schema("project-record-v1.schema.json")
        with open(EXAMPLES_DIR / "project-record-v1-example.yaml") as f:
            baseline = yaml.safe_load(f)
        class_d = {
            **baseline,
            "repository_role": "deployment-artifact",
            "documentation_class": "D",
            "audience_routes": [],
        }
        for candidate in (
            class_d,
            {**baseline, "repository_role": "deployment-artifact"},
        ):
            assert any("redirect" in error for error in validate(candidate, schema))

        class_d["redirect"] = {
            "status": "active",
            "target": "https://github.com/organvm/example-project",
        }
        assert validate(class_d, schema) == []

        canonical_class_d = {**class_d, "repository_role": "canonical"}
        assert any("canonical" in error for error in validate(canonical_class_d, schema))

    def test_class_f_requires_provenance_and_status_claims(self):
        schema = load_schema("project-record-v1.schema.json")
        with open(EXAMPLES_DIR / "project-record-v1-example.yaml") as f:
            data = yaml.safe_load(f)
        data["documentation_class"] = "F"
        data["audience_routes"] = []

        errors = validate(data, schema)
        assert len([error for error in errors if "does not contain" in error]) >= 1

        data["claim_references"] = []
        for scope in ("provenance", "status"):
            claim = {
                **yaml.safe_load(
                    (EXAMPLES_DIR / "project-record-v1-example.yaml").read_text(),
                )["claim_references"][0],
                "id": f"archive-{scope}",
                "scope": scope,
            }
            data["claim_references"].append(claim)
        assert "redirect" not in data
        assert validate(data, schema) == []

    def test_classes_d_and_f_reject_separate_audience_routes(self):
        schema = load_schema("project-record-v1.schema.json")
        with open(EXAMPLES_DIR / "project-record-v1-example.yaml") as f:
            baseline = yaml.safe_load(f)
        for doc_class in ("D", "F"):
            candidate = {**baseline, "documentation_class": doc_class}
            assert any("expected to be empty" in error for error in validate(candidate, schema))

    def test_remote_assertion_reference_fails(self):
        schema = load_schema("project-record-v1.schema.json")
        with open(EXAMPLES_DIR / "project-record-v1-example.yaml") as f:
            data = yaml.safe_load(f)
        data["claim_references"][0]["assertion_ref"] = (
            "https://example.invalid/assertion.json"
        )

        assert validate(data, schema)

    def test_local_references_reject_cross_platform_traversal(self):
        schema = load_schema("project-record-v1.schema.json")
        with open(EXAMPLES_DIR / "project-record-v1-example.yaml") as f:
            baseline = yaml.safe_load(f)

        for invalid in (
            "../status.json",
            "docs/../status.json",
            r"..\status.json",
            r"docs\..\status.json",
            "docs/./status.json",
            "docs//status.json",
            "docs/evidence/\x00status.json",
        ):
            candidate = yaml.safe_load(yaml.safe_dump(baseline))
            candidate["claim_references"][0]["assertion_ref"] = invalid
            assert validate(candidate, schema), invalid

    def test_exact_duplicate_audience_routes_fail_schema_validation(self):
        schema = load_schema("project-record-v1.schema.json")
        with open(EXAMPLES_DIR / "project-record-v1-example.yaml") as f:
            data = yaml.safe_load(f)
        data["audience_routes"][1] = dict(data["audience_routes"][0])

        assert any("non-unique" in error for error in validate(data, schema))

    def test_claim_posture_is_required_and_bounded(self):
        schema = load_schema("project-record-v1.schema.json")
        with open(EXAMPLES_DIR / "project-record-v1-example.yaml") as f:
            baseline = yaml.safe_load(f)
        del baseline["claim_references"][0]["claim_posture"]
        assert any("claim_posture" in error for error in validate(baseline, schema))

        with open(EXAMPLES_DIR / "project-record-v1-example.yaml") as f:
            invalid = yaml.safe_load(f)
        invalid["claim_references"][0]["claim_posture"] = "verified"
        assert any("one of" in error for error in validate(invalid, schema))

    def test_status_deployment_and_evaluator_claim_coverage(self):
        schema = load_schema("project-record-v1.schema.json")
        with open(EXAMPLES_DIR / "project-record-v1-example.yaml") as f:
            baseline = yaml.safe_load(f)

        no_status = yaml.safe_load(yaml.safe_dump(baseline))
        no_status["claim_references"] = [
            claim for claim in no_status["claim_references"] if claim["scope"] != "status"
        ]
        assert validate(no_status, schema)

        public = yaml.safe_load(yaml.safe_dump(baseline))
        public["deployment_status"] = "public"
        assert validate(public, schema)

        no_authorship = yaml.safe_load(yaml.safe_dump(baseline))
        no_authorship["claim_references"] = [
            claim
            for claim in no_authorship["claim_references"]
            if claim["scope"] != "authorship"
        ]
        assert validate(no_authorship, schema)

    def test_deployment_lifecycle_requires_a_bounded_claim_posture(self):
        schema = load_schema("project-record-v1.schema.json")
        with open(EXAMPLES_DIR / "project-record-v1-example.yaml") as f:
            baseline = yaml.safe_load(f)

        def candidate(status: str, posture: str) -> dict:
            data = yaml.safe_load(yaml.safe_dump(baseline))
            deployment_claim = {
                **data["claim_references"][0],
                "id": "deployment-lifecycle",
                "scope": "deployment",
                "claim_posture": posture,
            }
            data["deployment_status"] = status
            data["claim_references"].append(deployment_claim)
            return data

        for status in ("pilot", "public"):
            assert validate(candidate(status, "proposed"), schema)
            assert validate(candidate(status, "unknown"), schema)
            assert validate(candidate(status, "partial"), schema) == []
            assert validate(candidate(status, "implemented"), schema) == []

        assert validate(candidate("retired", "proposed"), schema)
        assert validate(candidate("retired", "unknown"), schema)
        for posture in ("implemented", "partial", "contradicted"):
            assert validate(candidate("retired", posture), schema) == []

    def test_role_class_matrix_is_conservative(self):
        schema = load_schema("project-record-v1.schema.json")
        with open(EXAMPLES_DIR / "project-record-v1-example.yaml") as f:
            baseline = yaml.safe_load(f)
        for role, required_class in (
            ("mirror", "D"),
            ("deployment-artifact", "D"),
            ("archive", "F"),
            ("upstream-fork", "F"),
            ("contribution", "F"),
        ):
            candidate = yaml.safe_load(yaml.safe_dump(baseline))
            candidate["repository_role"] = role
            assert any(required_class in error for error in validate(candidate, schema)), role

    def test_limitation_assertion_id_and_reference_are_paired(self):
        schema = load_schema("project-record-v1.schema.json")
        with open(EXAMPLES_DIR / "project-record-v1-example.yaml") as f:
            baseline = yaml.safe_load(f)
        for field, value in (
            ("assertion_ref", "docs/evidence/claims/status.json"),
            ("assertion_id", "project_record_fixture_status"),
        ):
            candidate = yaml.safe_load(yaml.safe_dump(baseline))
            candidate["limitations"][0][field] = value
            assert validate(candidate, schema)

    def test_example_fixture_paths_and_evidence_hash_resolve(self):
        fixture_root = EXAMPLES_DIR / "project-record-v1-fixture"
        with open(EXAMPLES_DIR / "project-record-v1-example.yaml") as f:
            data = yaml.safe_load(f)
        for route in data["audience_routes"]:
            assert (fixture_root / route["path"]).is_file()
        assert (fixture_root / data["links"]["documentation"]).is_file()
        assert (fixture_root / data["links"]["evidence"]).is_file()

        for claim in data["claim_references"]:
            assertion_path = fixture_root / claim["assertion_ref"]
            assertion = json.loads(assertion_path.read_text(encoding="utf-8"))
            assert assertion["assertion_id"] == claim["assertion_id"]
            for evidence in assertion["evidence_references"]:
                evidence_path = fixture_root / evidence["reference"]
                digest = "sha256:" + hashlib.sha256(evidence_path.read_bytes()).hexdigest()
                assert evidence["body_hash"] == digest


class TestSeedSchema:
    def test_example_validates(self):
        schema = load_schema("seed-v1.schema.json")
        with open(EXAMPLES_DIR / "seed-minimal.yaml") as f:
            data = yaml.safe_load(f)
        assert validate(data, schema) == []

    def test_missing_organ_fails(self):
        schema = load_schema("seed-v1.schema.json")
        data = {"schema_version": "1.0", "repo": "x", "org": "y"}
        errors = validate(data, schema)
        assert any("organ" in e for e in errors)


class TestDispatchSchema:
    def test_example_validates(self):
        schema = load_schema("dispatch-payload.schema.json")
        with open(EXAMPLES_DIR / "dispatch-example.json") as f:
            data = json.load(f)
        assert validate(data, schema) == []

    def test_missing_event_fails(self):
        schema = load_schema("dispatch-payload.schema.json")
        data = {
            "source": {"organ": "ORGAN-I"},
            "target": {"organ": "ORGAN-II"},
            "payload": {},
        }
        errors = validate(data, schema)
        assert any("event" in e for e in errors)


class TestSoakTestSchema:
    def test_minimal_validates(self):
        schema = load_schema("soak-test.schema.json")
        data = {
            "date": "2026-02-17",
            "collected_at": "2026-02-17T12:00:00Z",
            "validation": {
                "registry_pass": True,
                "dependency_pass": True,
            },
            "ci": {
                "total_checked": 71,
                "passing": 53,
                "failing": 18,
            },
        }
        assert validate(data, schema) == []


class TestSystemMetricsSchema:
    def test_minimal_validates(self):
        schema = load_schema("system-metrics.schema.json")
        data = {
            "schema_version": "1.0",
            "generated": "2026-02-17T12:00:00Z",
            "computed": {
                "total_repos": 97,
                "active_repos": 87,
                "archived_repos": 10,
                "total_organs": 8,
                "operational_organs": 8,
            },
            "manual": {},
        }
        assert validate(data, schema) == []


class TestGovernanceRulesSchema:
    def test_minimal_validates(self):
        schema = load_schema("governance-rules.schema.json")
        data = {
            "version": "1.0",
            "dependency_rules": {
                "max_transitive_depth": 4,
                "no_circular_dependencies": True,
                "no_back_edges": True,
            },
            "promotion_rules": {},
            "state_machine": {
                "states": ["LOCAL", "CANDIDATE"],
                "transitions": {"LOCAL": ["CANDIDATE"]},
            },
            "audit_thresholds": {},
        }
        assert validate(data, schema) == []


class TestEcosystemSchema:
    def test_example_validates(self):
        schema = load_schema("ecosystem-v1.schema.json")
        with open(EXAMPLES_DIR / "ecosystem-example.yaml") as f:
            data = yaml.safe_load(f)
        assert validate(data, schema) == []

    def test_missing_repo_fails(self):
        schema = load_schema("ecosystem-v1.schema.json")
        data = {"schema_version": "1.0", "organ": "III"}
        errors = validate(data, schema)
        assert any("repo" in e for e in errors)

    def test_missing_status_in_arm_fails(self):
        schema = load_schema("ecosystem-v1.schema.json")
        data = {
            "schema_version": "1.0",
            "repo": "x",
            "organ": "III",
            "delivery": [{"platform": "web_app"}],
        }
        errors = validate(data, schema)
        assert any("status" in e for e in errors)

    def test_invalid_status_fails(self):
        schema = load_schema("ecosystem-v1.schema.json")
        data = {
            "schema_version": "1.0",
            "repo": "x",
            "organ": "III",
            "delivery": [{"platform": "web_app", "status": "INVALID"}],
        }
        errors = validate(data, schema)
        assert len(errors) > 0

    def test_custom_pillar_accepted(self):
        schema = load_schema("ecosystem-v1.schema.json")
        data = {
            "schema_version": "1.0",
            "repo": "x",
            "organ": "III",
            "partnerships": [{"platform": "aws", "status": "planned"}],
        }
        assert validate(data, schema) == []

    def test_additional_arm_properties_accepted(self):
        schema = load_schema("ecosystem-v1.schema.json")
        data = {
            "schema_version": "1.0",
            "repo": "x",
            "organ": "III",
            "revenue": [
                {"platform": "subscription", "status": "live", "stripe_id": "prod_123"},
            ],
        }
        assert validate(data, schema) == []


class TestSystemOrganismSchema:
    def test_example_validates(self):
        schema = load_schema("system-organism.schema.json")
        with open(EXAMPLES_DIR / "system-organism-example.json") as f:
            data = json.load(f)
        assert validate(data, schema) == []

    def test_missing_organs_fails(self):
        schema = load_schema("system-organism.schema.json")
        data = {"total_repos": 1, "sys_pct": 50, "generated": "2026-03-06T12:00:00+00:00"}
        errors = validate(data, schema)
        assert any("organs" in e for e in errors)

    def test_missing_generated_fails(self):
        schema = load_schema("system-organism.schema.json")
        data = {"total_repos": 1, "sys_pct": 50, "organs": []}
        errors = validate(data, schema)
        assert any("generated" in e for e in errors)

    def test_invalid_sys_pct_fails(self):
        schema = load_schema("system-organism.schema.json")
        data = {
            "total_repos": 1,
            "sys_pct": 200,
            "organs": [],
            "generated": "2026-03-06T12:00:00+00:00",
        }
        errors = validate(data, schema)
        assert len(errors) > 0


class TestPulseEventSchema:
    def test_example_validates(self):
        schema = load_schema("pulse-event.schema.json")
        with open(EXAMPLES_DIR / "pulse-event-example.json") as f:
            data = json.load(f)
        assert validate(data, schema) == []

    def test_ontologia_event_validates(self):
        """Pulse event schema is a superset of ontologia events."""
        schema = load_schema("pulse-event.schema.json")
        with open(EXAMPLES_DIR / "ontologia-event-example.json") as f:
            data = json.load(f)
        assert validate(data, schema) == []

    def test_invalid_event_type_fails(self):
        schema = load_schema("pulse-event.schema.json")
        data = {
            "event_type": "not.a.real.event",
            "source": "test",
            "timestamp": "2026-03-13T10:00:00Z",
        }
        errors = validate(data, schema)
        assert len(errors) > 0


class TestConversationCorpusSurfaceManifestSchema:
    def test_example_validates(self):
        schema = load_schema("conversation-corpus-surface-manifest.schema.json")
        with open(EXAMPLES_DIR / "conversation-corpus-surface-manifest-example.json") as f:
            data = json.load(f)
        assert validate(data, schema) == []

    def test_missing_registry_fails(self):
        schema = load_schema("conversation-corpus-surface-manifest.schema.json")
        data = {
            "contract_name": "conversation-corpus-engine-surface-manifest-v1",
            "contract_version": 1,
            "generated_at": "2026-03-21T12:00:00Z",
            "engine": {
                "package": "conversation-corpus-engine",
                "version": "0.1.0",
                "repo_root": "/tmp/cce",
            },
            "project": {
                "project_root": "/tmp/cce",
                "source_drop_root": "/tmp/source-drop",
                "organ": "ORGAN-I",
                "system_role": "conversation-corpus-engine",
            },
            "schemas": [],
            "cli_surfaces": [],
            "providers": [],
            "artifacts": {
                "registry_path": "/tmp/cce/state/corpus-registry.json",
                "promotion_policy_path": "/tmp/cce/state/promotion-policy.json",
                "federation_summary_path": "/tmp/cce/federation/federation-summary.md",
                "policy_replay_latest_json_path": "/tmp/cce/state/policy-replay-latest.json",
                "policy_candidate_latest_json_path": "/tmp/cce/state/policy-candidate-latest.json",
                "policy_application_latest_json_path": "/tmp/cce/state/policy-application-latest.json",
                "corpus_candidate_latest_json_path": "/tmp/cce/state/corpus-candidate-latest.json",
                "corpus_promotion_latest_json_path": "/tmp/cce/state/corpus-promotion-latest.json",
                "corpus_live_pointer_path": "/tmp/cce/state/corpus-live-pointer.json",
                "source_policy_paths": {},
                "provider_refresh_latest_json_paths": {},
            },
        }
        errors = validate(data, schema)
        assert any("registry" in e for e in errors)


class TestConversationCorpusMcpContextSchema:
    def test_example_validates(self):
        schema = load_schema("conversation-corpus-mcp-context.schema.json")
        with open(EXAMPLES_DIR / "conversation-corpus-mcp-context-example.json") as f:
            data = json.load(f)
        assert validate(data, schema) == []

    def test_missing_summary_field_fails(self):
        schema = load_schema("conversation-corpus-mcp-context.schema.json")
        data = {
            "contract_name": "conversation-corpus-engine-mcp-context-v1",
            "contract_version": 1,
            "generated_at": "2026-03-21T12:00:00Z",
            "project_root": "/tmp/cce",
            "source_drop_root": "/tmp/source-drop",
            "summary": {
                "registered_corpus_count": 1,
                "active_corpus_count": 1,
                "provider_count": 1,
                "healthy_provider_count": 1,
                "refresh_recommended_count": 0,
            },
            "registry": {"default_corpus_id": None, "corpora": []},
            "providers": [],
            "governance": {
                "promotion_policy": {},
                "latest_policy_replay": None,
                "latest_policy_candidate": None,
                "latest_policy_application": None,
                "latest_corpus_candidate": None,
                "latest_corpus_promotion": None,
            },
            "latest_events": {
                "latest_corpus_live_pointer": None,
                "latest_policy_live_pointer": None,
                "latest_provider_refreshes": {},
            },
            "review_queue": {"open_count": 0, "items": []},
            "schema_catalog": [],
        }
        errors = validate(data, schema)
        assert any("open_review_count" in e for e in errors)


class TestConversationCorpusSurfaceBundleSchema:
    def test_example_validates(self):
        schema = load_schema("conversation-corpus-surface-bundle.schema.json")
        with open(EXAMPLES_DIR / "conversation-corpus-surface-bundle-example.json") as f:
            data = json.load(f)
        assert validate(data, schema) == []

    def test_missing_context_fails(self):
        schema = load_schema("conversation-corpus-surface-bundle.schema.json")
        data = {
            "contract_name": "conversation-corpus-engine-surface-bundle-v1",
            "contract_version": 1,
            "generated_at": "2026-03-21T12:00:00Z",
            "project_root": "/tmp/cce",
            "source_drop_root": "/tmp/source-drop",
            "summary": {"valid": True, "error_count": 0},
            "manifest": {
                "schema_name": "surface-manifest",
                "path": "/tmp/cce/reports/surfaces/surface-manifest.json",
                "markdown_path": "/tmp/cce/reports/surfaces/surface-manifest.md",
                "valid": True,
                "error_count": 0,
                "errors": [],
            },
        }
        errors = validate(data, schema)
        assert any("context" in e for e in errors)

    def test_missing_source_fails(self):
        schema = load_schema("pulse-event.schema.json")
        data = {
            "event_type": "pulse.heartbeat",
            "timestamp": "2026-03-13T10:00:00Z",
        }
        errors = validate(data, schema)
        assert any("source" in e for e in errors)


class TestAmmoiSchema:
    def test_example_validates(self):
        schema = load_schema("ammoi-v1.schema.json")
        with open(EXAMPLES_DIR / "ammoi-example.json") as f:
            data = json.load(f)
        assert validate(data, schema) == []

    def test_missing_organs_fails(self):
        schema = load_schema("ammoi-v1.schema.json")
        data = {
            "timestamp": "2026-03-13T15:00:00Z",
            "system_density": 0.5,
            "total_entities": 10,
        }
        errors = validate(data, schema)
        assert any("organs" in e for e in errors)

    def test_density_out_of_range_fails(self):
        schema = load_schema("ammoi-v1.schema.json")
        data = {
            "timestamp": "2026-03-13T15:00:00Z",
            "system_density": 1.5,
            "total_entities": 10,
            "organs": {},
        }
        errors = validate(data, schema)
        assert len(errors) > 0

    def test_minimal_organ_validates(self):
        schema = load_schema("ammoi-v1.schema.json")
        data = {
            "timestamp": "2026-03-13T15:00:00Z",
            "system_density": 0.5,
            "total_entities": 10,
            "organs": {
                "ORGAN-I": {
                    "organ_id": "ORGAN-I",
                    "organ_name": "Theory",
                }
            },
        }
        assert validate(data, schema) == []

    def test_organ_extra_fields_rejected(self):
        schema = load_schema("ammoi-v1.schema.json")
        data = {
            "timestamp": "2026-03-13T15:00:00Z",
            "system_density": 0.5,
            "total_entities": 10,
            "organs": {
                "ORGAN-I": {
                    "organ_id": "ORGAN-I",
                    "organ_name": "Theory",
                    "bogus_field": 99,
                }
            },
        }
        errors = validate(data, schema)
        assert len(errors) > 0


class TestOrganDefinitionsSchema:
    def test_example_validates(self):
        schema = load_schema("organ-definitions.schema.json")
        with open(EXAMPLES_DIR / "organ-definitions-example.json") as f:
            data = json.load(f)
        assert validate(data, schema) == []

    def test_missing_organs_fails(self):
        schema = load_schema("organ-definitions.schema.json")
        data = {"schema_version": "1.0"}
        errors = validate(data, schema)
        assert any("organs" in e for e in errors)

    def test_invalid_organ_key_fails(self):
        schema = load_schema("organ-definitions.schema.json")
        data = {
            "schema_version": "1.0",
            "organs": {
                "BAD-KEY": {
                    "name": "Bad",
                    "domain_boundary": "x" * 25,
                    "inclusion_criteria": ["a", "b", "c"],
                    "exclusion_criteria": [
                        {"condition": "x", "redirect": "y"},
                        {"condition": "z", "redirect": "w"},
                    ],
                    "canonical_repo_types": ["a", "b"],
                    "boundary_tests": [
                        {"question": "q?", "expected": True},
                        {"question": "r?", "expected": False},
                    ],
                }
            },
        }
        errors = validate(data, schema)
        assert len(errors) > 0

    def test_missing_required_organ_fields_fails(self):
        schema = load_schema("organ-definitions.schema.json")
        data = {
            "schema_version": "1.0",
            "organs": {
                "ORGAN-I": {"name": "Theory"},
            },
        }
        errors = validate(data, schema)
        assert len(errors) > 0


class TestExcavationReportSchema:
    def test_example_validates(self):
        schema = load_schema("excavation-report.schema.json")
        with open(EXAMPLES_DIR / "excavation-report-example.json") as f:
            data = json.load(f)
        assert validate(data, schema) == []

    def test_missing_findings_fails(self):
        schema = load_schema("excavation-report.schema.json")
        data = {"scanned_repos": 10, "total_findings": 0}
        errors = validate(data, schema)
        assert any("findings" in e for e in errors)

    def test_invalid_entity_type_fails(self):
        schema = load_schema("excavation-report.schema.json")
        data = {
            "scanned_repos": 1,
            "total_findings": 1,
            "findings": [
                {
                    "repo": "test",
                    "organ": "ORGAN-I",
                    "entity_path": "x",
                    "entity_type": "invalid_type",
                    "severity": "warning",
                },
            ],
        }
        errors = validate(data, schema)
        assert len(errors) > 0


class TestUaksSourceObjectSchema:
    def test_example_validates(self):
        schema = load_schema("uaks-source-object.schema.json")
        with open(EXAMPLES_DIR / "uaks-source-object-example.json") as f:
            data = json.load(f)
        assert validate(data, schema) == []

    def test_missing_checksum_fails(self):
        schema = load_schema("uaks-source-object.schema.json")
        data = {
            "sourceId": "src_test",
            "sourceType": "raw_text",
            "origin": "/tmp/test.md",
            "ingestedAt": "2026-04-23T00:00:00Z",
            "mimeType": "text/markdown",
            "rawArchiveRef": "cas_abc123",
        }
        errors = validate(data, schema)
        assert any("checksum" in e for e in errors)

    def test_invalid_source_type_fails(self):
        schema = load_schema("uaks-source-object.schema.json")
        data = {
            "sourceId": "src_test",
            "sourceType": "invalid_type",
            "origin": "/tmp/test.md",
            "ingestedAt": "2026-04-23T00:00:00Z",
            "checksum": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "mimeType": "text/markdown",
            "rawArchiveRef": "cas_abc123",
        }
        errors = validate(data, schema)
        assert len(errors) > 0


class TestUaksTextAtomSchema:
    def test_example_validates(self):
        schema = load_schema("uaks-text-atom.schema.json")
        with open(EXAMPLES_DIR / "uaks-text-atom-example.json") as f:
            data = json.load(f)
        assert validate(data, schema) == []

    def test_missing_content_fails(self):
        schema = load_schema("uaks-text-atom.schema.json")
        data = {
            "atomId": "ta_test",
            "atomFamily": "text",
            "atomClass": "claim",
            "contentHash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "sourceRef": "src_test",
            "validationState": "DRAFT",
            "createdAt": "2026-04-23T00:00:00Z",
        }
        errors = validate(data, schema)
        assert any("content" in e for e in errors)

    def test_invalid_validation_state_fails(self):
        schema = load_schema("uaks-text-atom.schema.json")
        data = {
            "atomId": "ta_test",
            "atomFamily": "text",
            "atomClass": "claim",
            "content": "Test content",
            "contentHash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "sourceRef": "src_test",
            "validationState": "INVALID_STATE",
            "createdAt": "2026-04-23T00:00:00Z",
        }
        errors = validate(data, schema)
        assert len(errors) > 0


class TestUaksCodeAtomSchema:
    def test_example_validates(self):
        schema = load_schema("uaks-code-atom.schema.json")
        with open(EXAMPLES_DIR / "uaks-code-atom-example.json") as f:
            data = json.load(f)
        assert validate(data, schema) == []

    def test_wrong_atom_family_fails(self):
        schema = load_schema("uaks-code-atom.schema.json")
        data = {
            "atomId": "ca_test",
            "atomFamily": "text",
            "codeKind": "function",
            "content": "def foo(): pass",
            "contentHash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "sourceRef": "src_test",
            "validationState": "DRAFT",
            "createdAt": "2026-04-23T00:00:00Z",
        }
        errors = validate(data, schema)
        assert len(errors) > 0


class TestUaksAssemblyRecipeSchema:
    def test_example_validates(self):
        schema = load_schema("uaks-assembly-recipe.schema.json")
        with open(EXAMPLES_DIR / "uaks-assembly-recipe-example.json") as f:
            data = json.load(f)
        assert validate(data, schema) == []

    def test_empty_atom_sequence_fails(self):
        schema = load_schema("uaks-assembly-recipe.schema.json")
        data = {
            "recipeId": "rcp_test",
            "recipeType": "summary",
            "atomSequence": [],
            "resolutionLevel": "standard",
            "createdAt": "2026-04-23T00:00:00Z",
        }
        errors = validate(data, schema)
        assert len(errors) > 0


class TestUaksValidationEventSchema:
    def test_example_validates(self):
        schema = load_schema("uaks-validation-event.schema.json")
        with open(EXAMPLES_DIR / "uaks-validation-event-example.json") as f:
            data = json.load(f)
        assert validate(data, schema) == []

    def test_missing_reviewer_fails(self):
        schema = load_schema("uaks-validation-event.schema.json")
        data = {
            "eventId": "vev_test",
            "atomId": "ta_test",
            "fromState": "DRAFT",
            "toState": "DISTILLED",
            "timestamp": "2026-04-23T00:00:00Z",
        }
        errors = validate(data, schema)
        assert any("reviewer" in e for e in errors)


class TestValidateScriptAutoDetect:
    def test_detects_system_organism_and_pillar_dna_examples(self):
        script = Path(__file__).resolve().parent.parent / "scripts" / "validate.py"
        organism = EXAMPLES_DIR / "system-organism-example.json"
        pillar = EXAMPLES_DIR / "pillar-dna-example.yaml"
        result = subprocess.run(
            [sys.executable, str(script), str(organism), str(pillar)],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert "PASS system-organism-example.json" in result.stdout
        assert "PASS pillar-dna-example.yaml" in result.stdout
