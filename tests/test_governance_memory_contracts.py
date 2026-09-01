"""Regression tests for the governance-memory public contracts."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import rfc8785
from jsonschema import Draft202012Validator, FormatChecker

from scripts import validate_governance_memory as governance_validator
from scripts.validate_governance_memory import (
    CONTRACT_TO_SCHEMA,
    semantic_errors,
    validate_document,
)

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = ROOT / "schemas"
EXAMPLES_DIR = ROOT / "examples"
FIXTURES_DIR = ROOT / "tests" / "fixtures" / "governance-memory"

EXAMPLES = {
    "source-census.v1": "source-census-v1-example.json",
    "normalized-event.v1": "normalized-event-v1-example.json",
    "normalization-parity-receipt.v1": "normalization-parity-receipt-v1-example.json",
    "ideal-form-register.v1": "ideal-form-register-v1-example.json",
    "iceberg-atlas.v1": "iceberg-atlas-v1-example.json",
    "node-self-image-set.v1": "node-self-image-set-v1-example.json",
    "governance-stage-receipt.v1": "governance-stage-receipt-v1-example.json",
    "governance-cadence-receipt.v1": "governance-cadence-receipt-v1-example.json",
    "governance-atlas-receipt.v1": "governance-atlas-receipt-v1-example.json",
    "governance-snapshot-bundle.v1": "governance-snapshot-bundle-v1-example.json",
    "owner-reference.v1": "owner-reference-v1-example.json",
    "parameter-contract.v1": "parameter-contract-v1-example.json",
    "source-envelope.v1": "source-envelope-v1-example.json",
    "assertion-evidence.v1": "assertion-evidence-v1-example.json",
    "lineage-graph.v1": "lineage-graph-v1-example.json",
    "governance-testament.v1": "governance-testament-v1-example.json",
    "node-self-image.v1": "node-self-image-v1-example.json",
    "coverage-receipt.v1": "coverage-receipt-v1-example.json",
}


def load(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def test_all_governance_memory_schemas_are_valid_draft_202012():
    for schema_filename in CONTRACT_TO_SCHEMA.values():
        Draft202012Validator.check_schema(load(SCHEMAS_DIR / schema_filename))


def test_all_positive_examples_pass_schema_and_semantic_validation():
    for contract_name, example_filename in EXAMPLES.items():
        data = load(EXAMPLES_DIR / example_filename)
        assert data["contract_name"] == contract_name
        schema_errors, invariant_errors = validate_document(data)
        assert schema_errors == []
        assert invariant_errors == []


def test_provider_names_are_runtime_data_not_a_fixed_catalog():
    data = load(EXAMPLES_DIR / "source-envelope-v1-example.json")
    schema = load(SCHEMAS_DIR / "source-envelope.v1.schema.json")
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    for family, instance, adapter in (
        ("renamed-provider-2042", "desktop-rebrand", "adapter.rebrand.v9"),
        ("new-provider-never-seen", "account-001", "adapter.new.v1"),
    ):
        candidate = copy.deepcopy(data)
        candidate["source_family"] = family
        candidate["source_instance"] = instance
        candidate["format_adapter"] = adapter
        assert list(validator.iter_errors(candidate)) == []


def test_required_source_expectation_cannot_disappear_from_census():
    data = load(EXAMPLES_DIR / "source-census-v1-example.json")
    data["raw_units"] = [
        raw_unit
        for raw_unit in data["raw_units"]
        if raw_unit.get("expectation_id") != "expectation-owner-export"
    ]

    schema_errors, invariant_errors = validate_document(data)
    assert schema_errors == []
    assert any(
        "must be represented by exactly one raw_unit.expectation_id" in error
        for error in invariant_errors
    )


def test_required_source_expectation_is_represented_exactly_once():
    data = load(EXAMPLES_DIR / "source-census-v1-example.json")
    duplicate = copy.deepcopy(data["raw_units"][1])
    duplicate["raw_unit_id"] = "raw_fixture_expected_duplicate"
    data["raw_units"].append(duplicate)

    schema_errors, invariant_errors = validate_document(data)
    assert schema_errors == []
    assert any(
        "must be represented by exactly one raw_unit.expectation_id" in error
        for error in invariant_errors
    )


def test_expected_raw_unit_must_retain_configured_source_family():
    data = load(EXAMPLES_DIR / "source-census-v1-example.json")
    data["raw_units"][1]["source_family"] = "runtime-provider-mismatch"

    schema_errors, invariant_errors = validate_document(data)
    assert schema_errors == []
    assert any(
        "source_family must match seed expectation" in error
        for error in invariant_errors
    )


def test_required_provider_family_is_configuration_only_and_status_neutral():
    baseline = load(EXAMPLES_DIR / "source-census-v1-example.json")
    family = "provider-added-or-renamed-without-code-change"
    baseline["seed_expectations"][0]["source_family"] = family
    baseline["raw_units"][1]["source_family"] = family

    for status in ("inaccessible", "missing_expected", "blocked"):
        candidate = copy.deepcopy(baseline)
        candidate["raw_units"][1]["acquisition_status"] = status
        assert validate_document(candidate) == ([], [])


def test_assistant_plan_is_rejected_from_operator_intent_lane():
    data = load(EXAMPLES_DIR / "lineage-graph-v1-example.json")
    schema = load(SCHEMAS_DIR / "lineage-graph.v1.schema.json")
    data["nodes"][1]["lane"] = "operator_intent"
    data["nodes"][1]["authority_class"] = "operator_intent"

    errors = list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(data)
    )
    assert errors


def test_negative_semantic_fixtures_are_structurally_valid_but_rejected():
    fixtures = sorted(FIXTURES_DIR.glob("*.json"))
    assert fixtures
    for fixture in fixtures:
        data = load(fixture)
        schema_errors, invariant_errors = validate_document(data)
        assert schema_errors == [], fixture.name
        assert invariant_errors, fixture.name


def test_exact_coverage_can_retain_explicit_blocker_debt_without_being_ready():
    data = load(EXAMPLES_DIR / "coverage-receipt-v1-example.json")
    assert data["exact_all"] is True
    assert data["ready"] is False
    assert data["constitutional_scope"]["exact_all"] is True
    assert data["constitutional_scope"]["ready"] is True
    assert semantic_errors(data) == []


def test_coverage_requires_a_separately_typed_constitutional_scope():
    data = load(EXAMPLES_DIR / "coverage-receipt-v1-example.json")
    data.pop("constitutional_scope")

    schema_errors, _ = validate_document(data)
    assert schema_errors


def test_constitutional_scope_ready_is_schema_level_if_and_only_if():
    baseline = load(EXAMPLES_DIR / "coverage-receipt-v1-example.json")
    invalid_scopes = (
        {
            "scope_reference": "scope:constitutional:not-exact",
            "exact_all": False,
            "blocked_scopes": [],
            "missing_requirements": [],
            "ready": True,
        },
        {
            "scope_reference": "scope:constitutional:blocked",
            "exact_all": True,
            "blocked_scopes": ["scope:operator-authority"],
            "missing_requirements": [],
            "ready": True,
        },
        {
            "scope_reference": "scope:constitutional:missing",
            "exact_all": True,
            "blocked_scopes": [],
            "missing_requirements": ["requirement:ratification-evidence"],
            "ready": True,
        },
        {
            "scope_reference": "scope:constitutional:false-negative",
            "exact_all": True,
            "blocked_scopes": [],
            "missing_requirements": [],
            "ready": False,
        },
    )

    for scope in invalid_scopes:
        candidate = copy.deepcopy(baseline)
        candidate["constitutional_scope"] = scope
        schema_errors, _ = validate_document(candidate)
        assert schema_errors, scope["scope_reference"]


def test_constitutional_scope_non_ready_states_require_explicit_scope_debt():
    baseline = load(EXAMPLES_DIR / "coverage-receipt-v1-example.json")
    valid_scopes = (
        {
            "scope_reference": "scope:constitutional:not-exact",
            "exact_all": False,
            "blocked_scopes": [],
            "missing_requirements": [],
            "ready": False,
        },
        {
            "scope_reference": "scope:constitutional:blocked",
            "exact_all": True,
            "blocked_scopes": ["scope:operator-authority"],
            "missing_requirements": [],
            "ready": False,
        },
        {
            "scope_reference": "scope:constitutional:missing",
            "exact_all": True,
            "blocked_scopes": [],
            "missing_requirements": ["requirement:ratification-evidence"],
            "ready": False,
        },
    )

    for scope in valid_scopes:
        candidate = copy.deepcopy(baseline)
        candidate["constitutional_scope"] = scope
        assert validate_document(candidate) == ([], []), scope["scope_reference"]


def test_constitutional_scope_ready_does_not_weaken_global_ready():
    data = load(EXAMPLES_DIR / "coverage-receipt-v1-example.json")
    assert data["constitutional_scope"]["ready"] is True

    data["ready"] = True
    data["closure_status"] = "ready"
    _, invariant_errors = validate_document(data)
    assert any(
        "ready must be true exactly when exact_all is true and every source is parsed"
        in error
        for error in invariant_errors
    )


def test_coverage_allows_additional_owner_debt_without_aliasing_ready():
    data = load(EXAMPLES_DIR / "coverage-receipt-v1-example.json")
    data["unresolved_blockers"].append(
        "receipt:normalization-parity-fixture#/readiness/unresolved_blockers"
    )
    data["citation_debt"].append("assertion:candidate")
    data["incomplete_predicates"].append("IF-GOV-001")
    data["closure_status"] = "closed_with_owner_routed_debt"

    assert semantic_errors(data) == []
    data["ready"] = True
    data["closure_status"] = "ready"
    assert semantic_errors(data)


def test_all_parsed_coverage_is_exact_and_ready():
    data = load(EXAMPLES_DIR / "coverage-receipt-v1-example.json")
    data["sources"] = [data["sources"][0]]
    data["denominator"]["count"] = 1
    data["counts"]["owner_blocked"] = 0
    data["residual_owners"] = []
    data["unresolved_blockers"] = []
    data["closure_status"] = "ready"
    data["ready"] = True
    assert semantic_errors(data) == []


def test_verified_operator_directive_requires_source_event_and_ratification():
    data = load(EXAMPLES_DIR / "assertion-evidence-v1-example.json")
    data["assertion_class"] = "operator_directive"
    assert semantic_errors(data)


def test_duplicate_evidence_ids_fail_in_every_verification_state():
    baseline = load(EXAMPLES_DIR / "assertion-evidence-v1-example.json")
    baseline["evidence_references"][1]["evidence_id"] = baseline[
        "evidence_references"
    ][0]["evidence_id"]

    expected = "evidence_references contain duplicate evidence_id values"
    for state in ("unverified", "verified", "stale", "disputed"):
        candidate = copy.deepcopy(baseline)
        candidate["verification_state"] = state
        assert any(expected in error for error in semantic_errors(candidate)), state


def test_malformed_evidence_ids_do_not_abort_validation_batch(
    tmp_path,
    monkeypatch,
    capsys,
):
    malformed = load(EXAMPLES_DIR / "assertion-evidence-v1-example.json")
    malformed["verification_state"] = "unverified"
    malformed["evidence_references"][0]["evidence_id"] = {"bad": "id"}
    schema_errors, semantic_error_list = validate_document(malformed)
    assert any("evidence_id" in error for error in schema_errors)
    assert isinstance(semantic_error_list, list)

    malformed_path = tmp_path / "malformed-evidence-id.json"
    valid_path = tmp_path / "valid.json"
    malformed_path.write_text(json.dumps(malformed))
    valid_path.write_text(
        (EXAMPLES_DIR / "assertion-evidence-v1-example.json").read_text()
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "validate_governance_memory.py",
            str(malformed_path),
            str(valid_path),
        ],
    )

    assert governance_validator.main() == 1
    captured = capsys.readouterr().out
    assert f"FAIL {malformed_path}" in captured
    assert f"PASS {valid_path}" in captured


def test_assertion_fact_is_a_bounded_machine_readable_predicate_value():
    data = load(EXAMPLES_DIR / "assertion-evidence-v1-example.json")
    data["fact"] = {
        "predicate": "industry_status",
        "subject": "Education",
        "value": "deployed",
    }

    assert validate_document(data) == ([], [])

    del data["fact"]["value"]
    schema_errors, _semantic_errors = validate_document(data)
    assert any("value" in error for error in schema_errors)


def test_assertion_freshness_rejects_future_and_expired_receipts():
    baseline = load(EXAMPLES_DIR / "assertion-evidence-v1-example.json")
    validation_now = datetime(2026, 8, 31, 13, 0, tzinfo=UTC)

    baseline["freshness"] = {
        "verified_at": "2026-08-31T14:00:00Z",
        "max_age_seconds": 7200,
        "status": "fresh",
    }
    assert "freshness.verified_at cannot be in the future" in semantic_errors(
        baseline,
        now=validation_now,
    )

    baseline["freshness"] = {
        "verified_at": "2026-08-31T10:00:00Z",
        "max_age_seconds": 60,
        "status": "fresh",
    }
    assert "freshness.status 'fresh' is expired at validation time" in semantic_errors(
        baseline,
        now=validation_now,
    )


def test_assertion_freshness_accepts_lowercase_utc_suffix():
    data = load(EXAMPLES_DIR / "assertion-evidence-v1-example.json")
    data["freshness"] = {
        "verified_at": "2026-08-31T10:00:00z",
        "status": "not_applicable",
    }

    assert validate_document(data) == ([], [])
    assert semantic_errors(
        data,
        now=datetime(2026, 8, 31, 13, 0, tzinfo=UTC),
    ) == []


def test_assertion_freshness_rejects_utc_normalization_overflow_without_aborting(
    tmp_path,
    monkeypatch,
    capsys,
):
    boundary = load(EXAMPLES_DIR / "assertion-evidence-v1-example.json")
    boundary["freshness"] = {
        "verified_at": "0001-01-01T00:00:00+23:59",
        "status": "not_applicable",
    }
    _schema_errors, semantic_error_list = validate_document(boundary)
    assert any("ISO 8601 date-time" in error for error in semantic_error_list)

    boundary_path = tmp_path / "boundary-timestamp.json"
    valid_path = tmp_path / "valid.json"
    boundary_path.write_text(json.dumps(boundary))
    valid_path.write_text(
        (EXAMPLES_DIR / "assertion-evidence-v1-example.json").read_text()
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["validate_governance_memory.py", str(boundary_path), str(valid_path)],
    )

    assert governance_validator.main() == 1
    captured = capsys.readouterr().out
    assert f"FAIL {boundary_path}" in captured
    assert f"PASS {valid_path}" in captured


def test_assertion_freshness_rejects_unbounded_ages_without_aborting_batch(
    tmp_path,
    monkeypatch,
    capsys,
):
    huge = load(EXAMPLES_DIR / "assertion-evidence-v1-example.json")
    huge["freshness"] = {
        "verified_at": "2026-08-31T10:00:00Z",
        "max_age_seconds": 10**100,
        "status": "fresh",
    }
    schema_errors, semantic_error_list = validate_document(huge)
    assert any("greater than the maximum" in error for error in schema_errors)
    assert any("ten-year validation bound" in error for error in semantic_error_list)

    huge_path = tmp_path / "huge.json"
    valid_path = tmp_path / "valid.json"
    huge_path.write_text(json.dumps(huge))
    valid_path.write_text(
        (EXAMPLES_DIR / "assertion-evidence-v1-example.json").read_text()
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["validate_governance_memory.py", str(huge_path), str(valid_path)],
    )

    assert governance_validator.main() == 1
    captured = capsys.readouterr().out
    assert f"FAIL {huge_path}" in captured
    assert f"PASS {valid_path}" in captured


def test_ratified_operator_directive_accepts_event_bound_freshness():
    data = load(EXAMPLES_DIR / "assertion-evidence-v1-example.json")
    data["assertion_class"] = "operator_directive"
    data["evidence_references"][0]["evidence_type"] = "immutable_source_event"
    data["evidence_references"][1][
        "evidence_type"
    ] = "ratified_constitutional_record"
    data["freshness"] = {
        "verified_at": "2026-07-17T08:39:10Z",
        "status": "not_applicable",
    }
    assert validate_document(data) == ([], [])


def test_verified_operator_directive_rejects_missing_or_stale_freshness():
    data = load(EXAMPLES_DIR / "assertion-evidence-v1-example.json")
    data["assertion_class"] = "operator_directive"
    assert validate_document(data)[0]

    data["freshness"] = {
        "verified_at": "2026-07-17T08:39:10Z",
        "max_age_seconds": 1,
        "status": "stale",
    }
    assert semantic_errors(data)


def test_verified_current_state_requires_owner_fresh_verifier_and_freshness():
    data = load(EXAMPLES_DIR / "assertion-evidence-v1-example.json")
    data["assertion_class"] = "current_state"
    assert semantic_errors(data)


def test_stable_event_identity_excludes_snapshot_order_and_provider_display_data():
    baseline = load(EXAMPLES_DIR / "normalized-event-v1-example.json")
    event_id = baseline["event_id"]
    candidates = []

    changed_snapshot = copy.deepcopy(baseline)
    changed_snapshot["snapshot_id"] = "snapshot-reordered-fixture"
    candidates.append(changed_snapshot)

    changed_transport = copy.deepcopy(baseline)
    changed_transport["transport_metadata"] = {
        "line_number": 999,
        "source_order": 100,
        "provider_order": 1,
        "transport_position": "fork",
    }
    candidates.append(changed_transport)

    renamed_provider = copy.deepcopy(baseline)
    renamed_provider["source_family"] = "provider-display-name-after-rename"
    candidates.append(renamed_provider)

    for candidate in candidates:
        assert candidate["event_id"] == event_id
        schema_errors, invariant_errors = validate_document(candidate)
        assert schema_errors == []
        assert invariant_errors == []


def test_event_identity_basis_prohibits_snapshot_and_transport_position_fields():
    baseline = load(EXAMPLES_DIR / "normalized-event-v1-example.json")
    for forbidden_field, value in (
        ("snapshot_id", "snapshot-forbidden"),
        ("line_number", 17),
        ("source_order", 2),
        ("provider_order", 3),
        ("transport_position", "fork"),
    ):
        candidate = copy.deepcopy(baseline)
        candidate["identity_basis"][forbidden_field] = value
        schema_errors, _ = validate_document(candidate)
        assert schema_errors, forbidden_field


def test_event_id_is_recomputed_from_native_identity_role_and_content():
    data = load(EXAMPLES_DIR / "normalized-event-v1-example.json")
    data["identity_basis"]["native_identifiers"]["event_id"] = "different-native-event"
    schema_errors, invariant_errors = validate_document(data)
    assert schema_errors == []
    assert any("event_id must equal" in error for error in invariant_errors)


def test_event_identity_uses_rfc8785_unicode_key_order() -> None:
    data = load(EXAMPLES_DIR / "normalized-event-v1-example.json")
    identifiers = data["identity_basis"]["native_identifiers"]
    identifiers["\U0001f600"] = "supplementary-plane-key"
    identifiers["\ue000"] = "private-use-key"
    data["event_id"] = "evt_" + hashlib.sha256(
        rfc8785.dumps(data["identity_basis"])
    ).hexdigest()

    schema_errors, invariant_errors = validate_document(data)

    assert schema_errors == []
    assert invariant_errors == []


def test_normalization_parity_requires_every_census_unit_exactly_once():
    baseline = load(
        EXAMPLES_DIR / "normalization-parity-receipt-v1-example.json"
    )

    missing = copy.deepcopy(baseline)
    missing["promotions"].pop()
    assert semantic_errors(missing)

    duplicate = copy.deepcopy(baseline)
    duplicate["promotions"].append(copy.deepcopy(duplicate["promotions"][0]))
    assert semantic_errors(duplicate)

    extra = copy.deepcopy(baseline)
    extra["promotions"].append(
        {
            "raw_unit_id": "raw_not_in_census",
            "raw_unit_content_hash": None,
            "disposition": {
                "type": "ignored_transport_echo",
                "owner_reference": "owner_normalizer",
                "failed_predicate": "transport echo creates no authority event",
                "next_action": "Retain the reviewed echo disposition.",
                "evidence_references": ["receipt:echo-review"],
            },
        }
    )
    assert semantic_errors(extra)


def test_normalization_parity_binds_each_promotion_to_census_content_identity():
    baseline = load(
        EXAMPLES_DIR / "normalization-parity-receipt-v1-example.json"
    )

    mismatch = copy.deepcopy(baseline)
    mismatch["promotions"][0]["raw_unit_content_hash"] = (
        "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
    )
    schema_errors, invariant_errors = validate_document(mismatch)
    assert schema_errors == []
    assert any("do not match input_census.raw_units" in error for error in invariant_errors)

    duplicate = copy.deepcopy(baseline)
    duplicate["input_census"]["raw_units"].append(
        copy.deepcopy(duplicate["input_census"]["raw_units"][0])
    )
    assert semantic_errors(duplicate)


def test_promoted_contracts_require_raw_unit_content_identity():
    for example_name in (
        "source-envelope-v1-example.json",
        "normalized-event-v1-example.json",
    ):
        candidate = load(EXAMPLES_DIR / example_name)
        candidate.pop("raw_unit_content_hash")
        schema_errors, _ = validate_document(candidate)
        assert schema_errors, example_name

    parity = load(
        EXAMPLES_DIR / "normalization-parity-receipt-v1-example.json"
    )
    parity["promotions"][0].pop("raw_unit_content_hash")
    schema_errors, _ = validate_document(parity)
    assert schema_errors


def test_parity_owner_routed_debt_can_be_exact_but_never_ready():
    data = load(EXAMPLES_DIR / "normalization-parity-receipt-v1-example.json")
    assert data["readiness"]["exact_all"] is True
    assert data["readiness"]["ready"] is False
    assert semantic_errors(data) == []

    data["readiness"]["ready"] = True
    data["readiness"]["status"] = "ready"
    assert semantic_errors(data)


def test_ready_rejects_every_truth_first_debt_class():
    baseline = load(EXAMPLES_DIR / "governance-atlas-receipt-v1-example.json")
    for debt_field in (
        "unresolved_blockers",
        "quarantines",
        "missing_requirements",
        "citation_debt",
        "incomplete_predicates",
    ):
        candidate = copy.deepcopy(baseline)
        candidate["readiness"][debt_field] = [f"debt:{debt_field}"]
        assert semantic_errors(candidate), debt_field


def test_ideal_state_and_distance_are_recomputed_from_receipt_results():
    data = load(EXAMPLES_DIR / "ideal-form-register-v1-example.json")
    ideal = data["ideal_forms"][0]
    ideal["implementation_state"] = "partial"
    ideal["distance_to_ideal"]["classification"] = "partial"
    assert semantic_errors(data)


def test_self_image_set_requires_exactly_one_image_per_registered_node():
    data = load(EXAMPLES_DIR / "node-self-image-set-v1-example.json")
    data["registered_node_ids"].append("ent_repo_missing_self_image")
    data["counts"]["registered"] = 2
    assert semantic_errors(data)


def test_self_image_registry_denominator_is_public_and_recomputable():
    data = load(EXAMPLES_DIR / "node-self-image-set-v1-example.json")
    projection = data["registry_projection"]

    assert data["registry_reference"] == "#/registry_projection"
    assert data["registered_node_ids"] == [node["uid"] for node in projection]
    assert data["registry_digest"] == (
        "sha256:" + hashlib.sha256(rfc8785.dumps(projection)).hexdigest()
    )
    assert semantic_errors(data) == []


def test_self_image_registry_projection_tampering_fails_digest_binding():
    data = load(EXAMPLES_DIR / "node-self-image-set-v1-example.json")
    data["registry_projection"][0]["lifecycle_status"] = "archived"

    assert any(
        "registry_digest" in error
        for error in semantic_errors(data)
    )


def test_self_image_registry_projection_canonicalization_failure_is_reported():
    data = load(EXAMPLES_DIR / "node-self-image-set-v1-example.json")
    data["registry_projection"][0]["lifecycle_status"] = 2**53

    schema_errors, invariant_errors = validate_document(data)
    assert schema_errors
    assert any("RFC 8785 canonicalizable" in error for error in invariant_errors)


def test_self_declared_registered_ids_cannot_replace_registry_denominator():
    data = load(EXAMPLES_DIR / "node-self-image-set-v1-example.json")
    replacement_id = "ent_repo_01ARZ3NDEKTSV4RRFFQ69G5FAW"
    data["registered_node_ids"] = [replacement_id]
    data["self_images"][0]["node_id"] = replacement_id

    assert any(
        "derive exactly" in error
        for error in semantic_errors(data)
    )


def test_registry_projection_rejects_private_or_mutable_metadata():
    data = load(EXAMPLES_DIR / "node-self-image-set-v1-example.json")
    data["registry_projection"][0]["metadata"] = {
        "custody_path": "/private/source"
    }

    schema_errors, _ = validate_document(data)
    assert schema_errors


def test_stage_receipt_enforces_output_and_child_bounds():
    data = load(EXAMPLES_DIR / "governance-stage-receipt-v1-example.json")
    data["outputs"][0]["size_bytes"] = data["execution_limits"]["max_output_bytes"] + 1
    assert semantic_errors(data)


def test_cadence_receipt_requires_exact_predecessor_hash_chain():
    data = load(EXAMPLES_DIR / "governance-cadence-receipt-v1-example.json")
    data["stage_receipts"][4]["predecessor_receipt_digest"] = (
        "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    )
    assert semantic_errors(data)


def test_cadence_run_one_is_valid_only_as_an_incomplete_first_traversal():
    data = load(EXAMPLES_DIR / "governance-cadence-receipt-v1-example.json")
    data["run_number"] = 1
    data["previous_cadence_receipt_digest"] = None
    data["fixed_point"] = {
        "status": "not_applicable",
        "new_event_count": 999,
        "changed_byte_count": 999,
        "replayed_completed_children": 0,
        "previous_output_digest": None,
        "output_digest_matches_previous": False,
    }
    data["readiness"]["exact_all"] = False
    data["readiness"]["ready"] = False
    data["readiness"]["status"] = "incomplete"

    assert validate_document(data) == ([], [])

    data["readiness"]["exact_all"] = True
    data["readiness"]["ready"] = True
    data["readiness"]["status"] = "ready"
    schema_errors, invariant_errors = validate_document(data)
    assert schema_errors
    assert invariant_errors


def test_cadence_false_ready_rejects_nonzero_fixed_point_counts():
    data = load(EXAMPLES_DIR / "governance-cadence-receipt-v1-example.json")
    data["fixed_point"]["new_event_count"] = 999

    schema_errors, invariant_errors = validate_document(data)
    assert schema_errors
    assert invariant_errors


def test_cadence_run_two_ready_binds_the_previous_output_digest():
    data = load(EXAMPLES_DIR / "governance-cadence-receipt-v1-example.json")
    data["fixed_point"]["previous_output_digest"] = (
        "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    )

    schema_errors, invariant_errors = validate_document(data)
    assert schema_errors == []
    assert any("output_digest_matches_previous" in error for error in invariant_errors)


def test_cadence_changed_second_traversal_is_honestly_incomplete():
    data = load(EXAMPLES_DIR / "governance-cadence-receipt-v1-example.json")
    data["output_digest"] = (
        "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    )
    data["fixed_point"]["status"] = "changed"
    data["fixed_point"]["changed_byte_count"] = 999
    data["fixed_point"]["output_digest_matches_previous"] = False
    data["readiness"]["exact_all"] = False
    data["readiness"]["ready"] = False
    data["readiness"]["status"] = "incomplete"

    assert validate_document(data) == ([], [])


def test_snapshot_bundle_ready_requires_two_runs_and_post_proof_fixed_point():
    data = load(EXAMPLES_DIR / "governance-snapshot-bundle-v1-example.json")
    data["governance_cadence_receipts"].pop()
    assert semantic_errors(data)

    data = load(EXAMPLES_DIR / "governance-snapshot-bundle-v1-example.json")
    data["post_proof_idempotence"]["emitted_receipt_count"] = 1
    schema_errors, _ = validate_document(data)
    assert schema_errors


def test_snapshot_bundle_recursively_validates_embedded_events():
    data = load(EXAMPLES_DIR / "governance-snapshot-bundle-v1-example.json")
    data["normalized_events"][0]["event_id"] = "evt_" + "0" * 64
    assert semantic_errors(data)


def test_candidate_testament_cannot_carry_ratification():
    data = load(EXAMPLES_DIR / "governance-testament-v1-example.json")
    data["status"] = "candidate"
    schema_errors, _ = validate_document(data)
    assert schema_errors


def test_ratified_testament_fails_when_constitutional_scope_is_blocked():
    data = load(EXAMPLES_DIR / "governance-testament-v1-example.json")
    coverage = data["ratification"]["constitutional_coverage"]
    coverage["blocked_scopes"] = ["scope:operator-authority"]
    coverage["ready"] = False
    schema_errors, invariant_errors = validate_document(data)
    assert schema_errors == []
    assert any("ratified status is impossible" in error for error in invariant_errors)


def test_empty_strict_governance_content_is_rejected():
    census = load(EXAMPLES_DIR / "source-census-v1-example.json")
    census["raw_units"] = []
    assert validate_document(census)[0]

    assertion = load(EXAMPLES_DIR / "assertion-evidence-v1-example.json")
    assertion["evidence_references"] = []
    assert validate_document(assertion)[0]

    lineage = load(EXAMPLES_DIR / "lineage-graph-v1-example.json")
    lineage["nodes"] = []
    assert validate_document(lineage)[0]

    testament = load(EXAMPLES_DIR / "governance-testament-v1-example.json")
    testament["directive"] = ""
    assert validate_document(testament)[0]

    atlas = load(EXAMPLES_DIR / "iceberg-atlas-v1-example.json")
    atlas["timelines"]["operator_intent"] = []
    assert validate_document(atlas)[0]

    atlas = load(EXAMPLES_DIR / "iceberg-atlas-v1-example.json")
    atlas["relationships"] = []
    assert validate_document(atlas)[0]

    ideals = load(EXAMPLES_DIR / "ideal-form-register-v1-example.json")
    ideals["ideal_forms"] = []
    assert validate_document(ideals)[0]

    self_images = load(EXAMPLES_DIR / "node-self-image-set-v1-example.json")
    self_images["self_images"] = []
    assert validate_document(self_images)[0]

    stage = load(EXAMPLES_DIR / "governance-stage-receipt-v1-example.json")
    stage["child_receipts"] = []
    assert validate_document(stage)[0]

    bundle = load(EXAMPLES_DIR / "governance-snapshot-bundle-v1-example.json")
    bundle["source_envelopes"] = []
    assert validate_document(bundle)[0]
