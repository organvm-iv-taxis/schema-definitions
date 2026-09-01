#!/usr/bin/env python3
"""Validate governance-memory contracts and their cross-field invariants.

JSON Schema handles the portable shape of each contract. This validator owns
the invariants that require comparing multiple records, such as a coverage
denominator matching its source set or a verified external assertion carrying
two independent evidence groups.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import rfc8785
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = ROOT / "schemas"

CONTRACT_TO_SCHEMA = {
    "source-census.v1": "source-census.v1.schema.json",
    "normalized-event.v1": "normalized-event.v1.schema.json",
    "normalization-parity-receipt.v1": "normalization-parity-receipt.v1.schema.json",
    "ideal-form-register.v1": "ideal-form-register.v1.schema.json",
    "iceberg-atlas.v1": "iceberg-atlas.v1.schema.json",
    "node-self-image-set.v1": "node-self-image-set.v1.schema.json",
    "governance-stage-receipt.v1": "governance-stage-receipt.v1.schema.json",
    "governance-cadence-receipt.v1": "governance-cadence-receipt.v1.schema.json",
    "governance-atlas-receipt.v1": "governance-atlas-receipt.v1.schema.json",
    "governance-snapshot-bundle.v1": "governance-snapshot-bundle.v1.schema.json",
    "owner-reference.v1": "owner-reference.v1.schema.json",
    "parameter-contract.v1": "parameter-contract.v1.schema.json",
    "source-envelope.v1": "source-envelope.v1.schema.json",
    "assertion-evidence.v1": "assertion-evidence.v1.schema.json",
    "lineage-graph.v1": "lineage-graph.v1.schema.json",
    "governance-testament.v1": "governance-testament.v1.schema.json",
    "node-self-image.v1": "node-self-image.v1.schema.json",
    "coverage-receipt.v1": "coverage-receipt.v1.schema.json",
}

SOURCE_STATUSES = (
    "acquired",
    "parsed",
    "quarantined",
    "inaccessible",
    "missing_expected",
    "owner_blocked",
)

CADENCE_STAGES = (
    "discover",
    "snapshot",
    "parse",
    "classify",
    "reconcile",
    "distill",
    "validate",
    "render",
    "receipt",
)

READINESS_DEBT_FIELDS = (
    "unresolved_blockers",
    "quarantines",
    "missing_requirements",
    "citation_debt",
    "incomplete_predicates",
)


def load_json(path: Path) -> Any:
    """Load one JSON document."""
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _duplicates(values: list[Any]) -> list[Any]:
    """Return sorted, non-null duplicate values."""
    return sorted(
        value
        for value, count in Counter(values).items()
        if value is not None and count > 1
    )


def _readiness_errors(
    data: dict[str, Any],
    *,
    exact_all: bool,
    prerequisites_ready: bool = True,
) -> list[str]:
    """Recompute the shared truth-first readiness predicate."""
    readiness = data.get("readiness")
    if not isinstance(readiness, dict):
        return []

    errors: list[str] = []
    if readiness.get("exact_all") is not exact_all:
        errors.append(
            f"readiness.exact_all must be {exact_all!r} for the classified contract content"
        )

    debt_items: list[Any] = []
    for field in READINESS_DEBT_FIELDS:
        value = readiness.get(field)
        if isinstance(value, list):
            debt_items.extend(value)

    expected_ready = exact_all and prerequisites_ready and not debt_items
    if readiness.get("ready") is not expected_ready:
        errors.append(
            "readiness.ready must be true exactly when exact_all is true, all "
            "contract prerequisites pass, and blocker, quarantine, requirement, "
            "citation, and predicate debt are empty"
        )

    status = readiness.get("status")
    if (status == "ready") is not expected_ready:
        errors.append(
            "readiness.status may be 'ready' exactly when readiness.ready is true"
        )
    if status == "closed_with_owner_routed_debt":
        if readiness.get("ready") is not False:
            errors.append(
                "closed_with_owner_routed_debt must never alias readiness.ready"
            )
        if not debt_items:
            errors.append(
                "closed_with_owner_routed_debt requires explicit owner-routed debt"
            )
    return errors


def _source_census_errors(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    roots = data.get("discovery_roots")
    expectations = data.get("seed_expectations")
    raw_units = data.get("raw_units")
    if not isinstance(roots, list) or not isinstance(raw_units, list):
        return errors

    root_ids = [item.get("root_id") for item in roots if isinstance(item, dict)]
    duplicate_roots = _duplicates(root_ids)
    if duplicate_roots:
        errors.append(f"discovery_roots contain duplicate root_id values: {duplicate_roots}")
    known_roots = set(root_ids)

    expectation_ids = [
        item.get("expectation_id")
        for item in expectations or []
        if isinstance(item, dict)
    ]
    duplicate_expectations = _duplicates(expectation_ids)
    if duplicate_expectations:
        errors.append(
            "seed_expectations contain duplicate expectation_id values: "
            f"{duplicate_expectations}"
        )
    known_expectations = set(expectation_ids)
    expectations_by_id = {
        item.get("expectation_id"): item
        for item in expectations or []
        if isinstance(item, dict)
        and isinstance(item.get("expectation_id"), str)
    }

    raw_unit_ids = [
        item.get("raw_unit_id") for item in raw_units if isinstance(item, dict)
    ]
    duplicate_units = _duplicates(raw_unit_ids)
    if duplicate_units:
        errors.append(f"raw_units contain duplicate raw_unit_id values: {duplicate_units}")

    raw_expectation_ids = [
        item.get("expectation_id")
        for item in raw_units
        if isinstance(item, dict) and item.get("expectation_id") is not None
    ]
    raw_expectation_counts = Counter(raw_expectation_ids)
    for expectation_id, expectation in expectations_by_id.items():
        if (
            expectation.get("required") is True
            and raw_expectation_counts.get(expectation_id, 0) != 1
        ):
            errors.append(
                f"required seed expectation {expectation_id!r} must be represented "
                "by exactly one raw_unit.expectation_id"
            )

    for raw_unit in raw_units:
        if not isinstance(raw_unit, dict):
            continue
        raw_unit_id = raw_unit.get("raw_unit_id", "<unknown>")
        if raw_unit.get("discovery_root_id") not in known_roots:
            errors.append(
                f"raw unit {raw_unit_id!r} references an unknown discovery_root_id"
            )
        expectation_id = raw_unit.get("expectation_id")
        if expectation_id is not None and expectation_id not in known_expectations:
            errors.append(
                f"raw unit {raw_unit_id!r} references an unknown expectation_id"
            )
        expectation = expectations_by_id.get(expectation_id)
        if (
            isinstance(expectation, dict)
            and raw_unit.get("source_family") != expectation.get("source_family")
        ):
            errors.append(
                f"raw unit {raw_unit_id!r} source_family must match seed expectation "
                f"{expectation_id!r}"
            )
    return errors


def _normalized_event_errors(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    basis = data.get("identity_basis")
    if not isinstance(basis, dict):
        return errors

    forbidden_identity_fields = {
        "snapshot_id",
        "snapshot_digest",
        "line_number",
        "source_order",
        "provider_order",
        "transport_position",
        "source_family",
        "source_instance",
        "format_adapter",
    }
    present_forbidden = sorted(forbidden_identity_fields.intersection(basis))
    if present_forbidden:
        errors.append(
            "identity_basis contains transport, snapshot, order, or provider display "
            f"fields: {present_forbidden}"
        )

    canonical = rfc8785.dumps(basis)
    expected_event_id = "evt_" + hashlib.sha256(canonical).hexdigest()
    if data.get("event_id") != expected_event_id:
        errors.append(
            "event_id must equal sha256(canonical identity_basis) and therefore "
            "cannot depend on snapshot ID, line number, provider/source order, "
            "transport position, or provider display name"
        )
    return errors


def _normalization_parity_errors(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    input_census = data.get("input_census")
    output_events = data.get("output_events")
    promotions = data.get("promotions")
    readiness = data.get("readiness")
    if (
        not isinstance(input_census, dict)
        or not isinstance(output_events, dict)
        or not isinstance(readiness, dict)
        or not isinstance(promotions, list)
    ):
        return errors

    raw_unit_ids = input_census.get("raw_unit_ids")
    raw_units = input_census.get("raw_units")
    output_event_ids = output_events.get("event_ids")
    if (
        not isinstance(raw_unit_ids, list)
        or not isinstance(raw_units, list)
        or not isinstance(output_event_ids, list)
    ):
        return errors

    raw_unit_binding_ids = [
        raw_unit.get("raw_unit_id")
        for raw_unit in raw_units
        if isinstance(raw_unit, dict)
    ]
    duplicate_bindings = _duplicates(raw_unit_binding_ids)
    if duplicate_bindings:
        errors.append(
            "input_census.raw_units contains duplicate raw_unit_id values: "
            f"{duplicate_bindings}"
        )

    promotion_ids = [
        promotion.get("raw_unit_id")
        for promotion in promotions
        if isinstance(promotion, dict)
    ]
    duplicate_promotions = _duplicates(promotion_ids)
    if duplicate_promotions:
        errors.append(
            "promotions contain duplicate raw_unit_id values: "
            f"{duplicate_promotions}"
        )

    raw_unit_id_set = {
        value for value in raw_unit_ids if isinstance(value, str)
    }
    raw_unit_binding_id_set = {
        value for value in raw_unit_binding_ids if isinstance(value, str)
    }
    missing_bindings = sorted(raw_unit_id_set - raw_unit_binding_id_set)
    extra_bindings = sorted(raw_unit_binding_id_set - raw_unit_id_set)
    if missing_bindings:
        errors.append(
            "input_census.raw_units omits raw_unit_ids values: "
            f"{missing_bindings}"
        )
    if extra_bindings:
        errors.append(
            "input_census.raw_units contains raw_unit_id values outside raw_unit_ids: "
            f"{extra_bindings}"
        )

    raw_unit_content_hashes = {
        raw_unit.get("raw_unit_id"): raw_unit.get("content_hash")
        for raw_unit in raw_units
        if isinstance(raw_unit, dict)
        and isinstance(raw_unit.get("raw_unit_id"), str)
    }
    promotion_id_set = {
        value for value in promotion_ids if isinstance(value, str)
    }
    missing_promotions = sorted(raw_unit_id_set - promotion_id_set)
    extra_promotions = sorted(promotion_id_set - raw_unit_id_set)
    if missing_promotions:
        errors.append(
            f"promotions omit census raw_unit_id values: {missing_promotions}"
        )
    if extra_promotions:
        errors.append(
            f"promotions contain raw_unit_id values outside the census: {extra_promotions}"
        )

    promoted_event_ids: set[Any] = set()
    disposition_types: dict[Any, Any] = {}
    content_binding_mismatches: list[str] = []
    for promotion in promotions:
        if not isinstance(promotion, dict):
            continue
        raw_unit_id = promotion.get("raw_unit_id")
        if (
            isinstance(raw_unit_id, str)
            and raw_unit_id in raw_unit_content_hashes
            and promotion.get("raw_unit_content_hash")
            != raw_unit_content_hashes[raw_unit_id]
        ):
            content_binding_mismatches.append(raw_unit_id)
        event_ids = promotion.get("event_ids")
        if isinstance(event_ids, list):
            promoted_event_ids.update(event_ids)
        disposition = promotion.get("disposition")
        if isinstance(disposition, dict):
            disposition_types[promotion.get("raw_unit_id")] = disposition.get("type")
    if content_binding_mismatches:
        errors.append(
            "promotions contain raw_unit_content_hash values that do not match "
            "input_census.raw_units: "
            f"{sorted(content_binding_mismatches)}"
        )

    output_event_id_set = {
        value for value in output_event_ids if isinstance(value, str)
    }
    promoted_event_id_set = {
        value for value in promoted_event_ids if isinstance(value, str)
    }
    missing_output_events = sorted(output_event_id_set - promoted_event_id_set)
    extra_output_events = sorted(promoted_event_id_set - output_event_id_set)
    if missing_output_events:
        errors.append(
            "output_events contains normalized events absent from promotions: "
            f"{missing_output_events}"
        )
    if extra_output_events:
        errors.append(
            "promotions reference normalized events absent from output_events: "
            f"{extra_output_events}"
        )

    blocker_ids = {
        raw_unit_id
        for raw_unit_id, disposition_type in disposition_types.items()
        if isinstance(raw_unit_id, str)
        if disposition_type in {"blocked", "unsupported"}
    }
    quarantine_ids = {
        raw_unit_id
        for raw_unit_id, disposition_type in disposition_types.items()
        if isinstance(raw_unit_id, str)
        if disposition_type == "quarantined"
    }
    routed_blockers = set(readiness.get("unresolved_blockers", [])) | set(
        readiness.get("missing_requirements", [])
    )
    if not blocker_ids.issubset(routed_blockers):
        errors.append(
            "blocked and unsupported dispositions must appear in unresolved_blockers "
            "or missing_requirements"
        )
    if not quarantine_ids.issubset(set(readiness.get("quarantines", []))):
        errors.append(
            "quarantined dispositions must appear in readiness.quarantines"
        )

    exact_all = (
        not duplicate_promotions
        and not duplicate_bindings
        and not missing_bindings
        and not extra_bindings
        and not missing_promotions
        and not extra_promotions
        and not content_binding_mismatches
        and not missing_output_events
        and not extra_output_events
    )
    prerequisites_ready = not any(
        disposition_type in {"blocked", "unsupported", "quarantined"}
        for disposition_type in disposition_types.values()
    )
    errors.extend(
        _readiness_errors(
            data,
            exact_all=exact_all,
            prerequisites_ready=prerequisites_ready,
        )
    )
    return errors


def _coverage_errors(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    constitutional_scope = data.get("constitutional_scope")
    if isinstance(constitutional_scope, dict):
        expected_constitutional_ready = (
            constitutional_scope.get("exact_all") is True
            and not constitutional_scope.get("blocked_scopes")
            and not constitutional_scope.get("missing_requirements")
        )
        if constitutional_scope.get("ready") is not expected_constitutional_ready:
            errors.append(
                "constitutional_scope.ready must be true exactly when its scope is "
                "exact and has no blocked scopes or missing requirements"
            )

    sources = data.get("sources")
    denominator = data.get("denominator")
    counts = data.get("counts")
    residuals = data.get("residual_owners")
    if not isinstance(sources, list):
        return errors

    source_ids = [item.get("source_id") for item in sources if isinstance(item, dict)]
    duplicate_ids = sorted(
        source_id
        for source_id, count in Counter(source_ids).items()
        if source_id is not None and count > 1
    )
    if duplicate_ids:
        errors.append(f"sources contain duplicate source_id values: {duplicate_ids}")

    if isinstance(denominator, dict) and denominator.get("count") != len(sources):
        errors.append(
            "denominator.count must equal the number of classified source records"
        )

    expected_counts = Counter(
        item.get("status") for item in sources if isinstance(item, dict)
    )
    if isinstance(counts, dict):
        for status in SOURCE_STATUSES:
            if counts.get(status) != expected_counts.get(status, 0):
                errors.append(
                    f"counts.{status} must equal the number of sources with status {status!r}"
                )

    expected_residuals = {
        item.get("source_id"): {
            "owner_reference": item.get("owner_reference"),
            "failed_predicate": item.get("failed_predicate"),
            "next_action": item.get("next_action"),
        }
        for item in sources
        if isinstance(item, dict) and item.get("status") != "parsed"
    }
    actual_residuals: dict[Any, dict[str, Any]] = {}
    if isinstance(residuals, list):
        for residual in residuals:
            if not isinstance(residual, dict):
                continue
            source_id = residual.get("source_id")
            if source_id in actual_residuals:
                errors.append(
                    f"residual_owners contains duplicate source_id {source_id!r}"
                )
            actual_residuals[source_id] = {
                "owner_reference": residual.get("owner_reference"),
                "failed_predicate": residual.get("failed_predicate"),
                "next_action": residual.get("next_action"),
            }
        if actual_residuals != expected_residuals:
            errors.append(
                "residual_owners must exactly mirror every non-parsed source and its owner action"
            )

    expected_exact_all = (
        len(source_ids) == len(set(source_ids))
        and isinstance(denominator, dict)
        and denominator.get("count") == len(sources)
        and isinstance(counts, dict)
        and all(
            counts.get(status) == expected_counts.get(status, 0)
            for status in SOURCE_STATUSES
        )
        and actual_residuals == expected_residuals
    )
    if data.get("exact_all") is not expected_exact_all:
        errors.append(
            "exact_all must be true exactly when the unique denominator is classified once and every non-parsed source is owner-routed"
        )

    expected_blockers = {
        item.get("source_id")
        for item in sources
        if isinstance(item, dict)
        and item.get("status") in {"inaccessible", "owner_blocked"}
    }
    expected_quarantines = {
        item.get("source_id")
        for item in sources
        if isinstance(item, dict) and item.get("status") == "quarantined"
    }
    expected_missing_requirements = {
        item.get("source_id")
        for item in sources
        if isinstance(item, dict) and item.get("status") == "missing_expected"
    }
    expected_incomplete_predicates = {
        item.get("source_id")
        for item in sources
        if isinstance(item, dict) and item.get("status") == "acquired"
    }
    debt_expectations = {
        "unresolved_blockers": expected_blockers,
        "quarantines": expected_quarantines,
        "missing_requirements": expected_missing_requirements,
        "incomplete_predicates": expected_incomplete_predicates,
    }
    for field, expected in debt_expectations.items():
        actual = set(data.get(field, []))
        missing = expected - actual
        if missing:
            errors.append(
                f"{field} must include every source record carrying that debt: "
                + ", ".join(sorted(str(item) for item in missing))
            )

    all_debt = [
        item
        for field in (
            "unresolved_blockers",
            "quarantines",
            "missing_requirements",
            "citation_debt",
            "incomplete_predicates",
        )
        for item in data.get(field, [])
    ]
    expected_ready = (
        expected_exact_all
        and all(
            isinstance(source, dict) and source.get("status") == "parsed"
            for source in sources
        )
        and not actual_residuals
        and not all_debt
    )
    if data.get("ready") is not expected_ready:
        errors.append(
            "ready must be true exactly when exact_all is true and every source is parsed"
        )
    closure_status = data.get("closure_status")
    if (closure_status == "ready") is not expected_ready:
        errors.append(
            "closure_status may be 'ready' exactly when the ready predicate passes"
        )
    if closure_status == "closed_with_owner_routed_debt":
        if data.get("ready") is not False:
            errors.append(
                "closed_with_owner_routed_debt must never alias ready"
            )
        if not all_debt:
            errors.append(
                "closed_with_owner_routed_debt requires explicit debt"
            )

    return errors


def _assertion_errors(
    data: dict[str, Any],
    *,
    now: datetime | None = None,
) -> list[str]:
    errors: list[str] = []
    evidence = data.get("evidence_references")
    if not isinstance(evidence, list):
        return errors
    evidence_ids = [
        item.get("evidence_id") for item in evidence if isinstance(item, dict)
    ]
    duplicate_evidence_ids = _duplicates(evidence_ids)
    if duplicate_evidence_ids:
        errors.append(
            f"evidence_references contain duplicate evidence_id values: {duplicate_evidence_ids}"
        )

    freshness = data.get("freshness")
    if isinstance(freshness, dict):
        verified_at = freshness.get("verified_at")
        parsed_verified_at: datetime | None = None
        if isinstance(verified_at, str):
            try:
                normalized_verified_at = (
                    f"{verified_at[:-1]}+00:00"
                    if verified_at.endswith(("Z", "z"))
                    else verified_at
                )
                candidate = datetime.fromisoformat(normalized_verified_at)
            except ValueError:
                candidate = None
            if candidate is not None and candidate.tzinfo is not None:
                parsed_verified_at = candidate.astimezone(UTC)
        if parsed_verified_at is None:
            errors.append(
                "freshness.verified_at must be an ISO 8601 date-time with a timezone"
            )
        else:
            validation_now = (now or datetime.now(UTC)).astimezone(UTC)
            if parsed_verified_at > validation_now:
                errors.append("freshness.verified_at cannot be in the future")
            max_age_seconds = freshness.get("max_age_seconds")
            if (
                freshness.get("status") == "fresh"
                and isinstance(max_age_seconds, int)
                and not isinstance(max_age_seconds, bool)
                and max_age_seconds > 0
                and parsed_verified_at + timedelta(seconds=max_age_seconds)
                < validation_now
            ):
                errors.append(
                    "freshness.status 'fresh' is expired at validation time"
                )

    if data.get("verification_state") != "verified":
        return errors

    groups = {
        item.get("independence_group")
        for item in evidence
        if isinstance(item, dict) and item.get("independence_group")
    }
    evidence_types = {
        item.get("evidence_type") for item in evidence if isinstance(item, dict)
    }
    assertion_class = data.get("assertion_class")

    if assertion_class == "external_fact" and len(groups) < 2:
        errors.append(
            "a verified external_fact requires at least two independent evidence groups"
        )
    if assertion_class == "operator_directive":
        if len(groups) < 2:
            errors.append(
                "a verified operator_directive requires at least two independent evidence groups"
            )
        required = {"immutable_source_event", "ratified_constitutional_record"}
        missing = sorted(required - evidence_types)
        if missing:
            errors.append(
                "a verified operator_directive is missing evidence types: "
                + ", ".join(missing)
            )
        if not isinstance(freshness, dict) or freshness.get("status") not in {
            "fresh",
            "not_applicable",
        }:
            errors.append(
                "a verified operator_directive requires non-stale freshness"
            )
    if assertion_class == "current_state":
        required = {"owner_record", "fresh_verifier_receipt"}
        missing = sorted(required - evidence_types)
        if missing:
            errors.append(
                "a verified current_state is missing evidence types: "
                + ", ".join(missing)
            )
        if not isinstance(freshness, dict) or freshness.get("status") != "fresh":
            errors.append("a verified current_state requires freshness.status 'fresh'")

    return errors


def _testament_errors(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    status = data.get("status")
    ratification = data.get("ratification")

    if status == "candidate" and ratification is not None:
        errors.append("a candidate testament must not carry a ratification record")
    if status != "ratified":
        return errors
    if not isinstance(ratification, dict):
        return errors

    authority_events = ratification.get("authority_events")
    if not isinstance(authority_events, list) or not authority_events:
        errors.append(
            "a ratified testament requires at least one immutable operator authority event"
        )
    else:
        event_ids = [
            event.get("event_id") for event in authority_events if isinstance(event, dict)
        ]
        duplicate_event_ids = _duplicates(event_ids)
        if duplicate_event_ids:
            errors.append(
                f"ratification authority_events contain duplicate event_id values: {duplicate_event_ids}"
            )

    assertion_reference = ratification.get("assertion_evidence_reference")
    citations = data.get("citations")
    if isinstance(citations, list) and assertion_reference not in citations:
        errors.append(
            "ratification assertion_evidence_reference must resolve through testament citations"
        )

    coverage = ratification.get("constitutional_coverage")
    if isinstance(coverage, dict):
        expected_coverage_ready = (
            coverage.get("exact_all") is True
            and not coverage.get("blocked_scopes")
            and not coverage.get("missing_requirements")
        )
        if coverage.get("ready") is not expected_coverage_ready:
            errors.append(
                "constitutional_coverage.ready must be true exactly when coverage is exact "
                "and no relevant scope is blocked or missing"
            )
        if not expected_coverage_ready:
            errors.append(
                "ratified status is impossible while relevant constitutional coverage is blocked"
            )
    return errors


def _parameter_errors(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    parameters = data.get("parameters")
    if not isinstance(parameters, list):
        return errors

    for index, parameter in enumerate(parameters):
        if not isinstance(parameter, dict):
            continue
        key = parameter.get("key", f"index {index}")
        is_secret = (
            parameter.get("value_type") == "secret_reference"
            or parameter.get("secret_reference_policy") in {"reference_only", "required"}
        )
        if not is_secret:
            continue
        forbidden_fields = sorted(
            field
            for field in ("default", "resolved_value", "example_value")
            if field in parameter
        )
        if forbidden_fields:
            errors.append(
                f"secret parameter {key!r} contains committed value fields: "
                + ", ".join(forbidden_fields)
            )
        resolver = parameter.get("resolver")
        if isinstance(resolver, dict) and resolver.get("source") not in {
            "environment",
            "secret_store",
        }:
            errors.append(
                f"secret parameter {key!r} must resolve through environment or secret_store"
            )

    return errors


def _lineage_errors(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    nodes = data.get("nodes")
    edges = data.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return errors

    node_ids = [node.get("node_id") for node in nodes if isinstance(node, dict)]
    duplicate_nodes = sorted(
        node_id
        for node_id, count in Counter(node_ids).items()
        if node_id is not None and count > 1
    )
    if duplicate_nodes:
        errors.append(f"nodes contain duplicate node_id values: {duplicate_nodes}")
    nodes_by_id = {
        node.get("node_id"): node for node in nodes if isinstance(node, dict)
    }

    edge_ids = [edge.get("edge_id") for edge in edges if isinstance(edge, dict)]
    duplicate_edges = sorted(
        edge_id
        for edge_id, count in Counter(edge_ids).items()
        if edge_id is not None and count > 1
    )
    if duplicate_edges:
        errors.append(f"edges contain duplicate edge_id values: {duplicate_edges}")

    for edge in edges:
        if not isinstance(edge, dict):
            continue
        edge_id = edge.get("edge_id", "<unknown>")
        source_node = nodes_by_id.get(edge.get("from_node"))
        target_node = nodes_by_id.get(edge.get("to_node"))
        if source_node is None:
            errors.append(f"edge {edge_id!r} references an unknown from_node")
        if target_node is None:
            errors.append(f"edge {edge_id!r} references an unknown to_node")
        if edge.get("edge_type") == "adopts":
            if edge.get("review_state") != "reviewed" or not edge.get(
                "reviewer_reference"
            ):
                errors.append(
                    f"adoption edge {edge_id!r} requires reviewed state and a reviewer"
                )
            if source_node and target_node and not (
                source_node.get("lane") == "artifact"
                and target_node.get("lane") == "operator_intent"
            ):
                errors.append(
                    f"adoption edge {edge_id!r} must run from artifact to operator intent"
                )

    return errors


def _ideal_form_register_errors(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    ideal_forms = data.get("ideal_forms")
    coverage = data.get("coverage")
    readiness = data.get("readiness")
    if (
        not isinstance(ideal_forms, list)
        or not isinstance(coverage, dict)
        or not isinstance(readiness, dict)
    ):
        return errors

    ideal_form_ids = [
        ideal.get("ideal_form_id") for ideal in ideal_forms if isinstance(ideal, dict)
    ]
    duplicate_ideals = _duplicates(ideal_form_ids)
    if duplicate_ideals:
        errors.append(
            f"ideal_forms contain duplicate ideal_form_id values: {duplicate_ideals}"
        )

    computed_states: list[str] = []
    incomplete_predicate_ids: set[Any] = set()
    derivations_complete = True
    for ideal in ideal_forms:
        if not isinstance(ideal, dict):
            continue
        ideal_form_id = ideal.get("ideal_form_id", "<unknown>")
        predicates = ideal.get("predicates")
        if not isinstance(predicates, list):
            continue
        predicate_ids = [
            predicate.get("predicate_id")
            for predicate in predicates
            if isinstance(predicate, dict)
        ]
        duplicate_predicates = _duplicates(predicate_ids)
        if duplicate_predicates:
            errors.append(
                f"ideal form {ideal_form_id!r} contains duplicate predicate_id values: "
                f"{duplicate_predicates}"
            )
            derivations_complete = False

        results = [
            predicate.get("result")
            for predicate in predicates
            if isinstance(predicate, dict)
        ]
        if any(result == "blocked" for result in results):
            expected_state = "blocked"
        elif results and all(result == "pass" for result in results):
            expected_state = "verified"
        else:
            expected_state = "partial"
        computed_states.append(expected_state)

        if ideal.get("implementation_state") != expected_state:
            errors.append(
                f"ideal form {ideal_form_id!r} implementation_state must be derived "
                f"as {expected_state!r} from predicate receipts"
            )

        distance = ideal.get("distance_to_ideal")
        verified_count = sum(result == "pass" for result in results)
        if isinstance(distance, dict):
            if distance.get("classification") != expected_state:
                errors.append(
                    f"ideal form {ideal_form_id!r} distance classification must be "
                    "derived from predicate receipts"
                )
            if distance.get("verified_predicates") != verified_count:
                errors.append(
                    f"ideal form {ideal_form_id!r} verified_predicates must equal "
                    "the number of pass results"
                )
            if distance.get("total_predicates") != len(predicates):
                errors.append(
                    f"ideal form {ideal_form_id!r} total_predicates must equal "
                    "the predicate count"
                )

        receipt_references = {
            predicate.get("receipt_reference")
            for predicate in predicates
            if isinstance(predicate, dict)
        }
        derivation = ideal.get("derivation")
        derived_receipts = set(
            derivation.get("receipt_references", [])
            if isinstance(derivation, dict)
            else []
        )
        if receipt_references != derived_receipts:
            errors.append(
                f"ideal form {ideal_form_id!r} derivation must name every predicate receipt exactly"
            )
            derivations_complete = False

        residual_gaps = ideal.get("residual_gaps")
        if expected_state == "verified" and residual_gaps:
            errors.append(
                f"verified ideal form {ideal_form_id!r} must not retain residual_gaps"
            )
        if expected_state != "verified" and not residual_gaps:
            errors.append(
                f"non-verified ideal form {ideal_form_id!r} must name residual_gaps"
            )
        incomplete_predicate_ids.update(
            predicate.get("predicate_id")
            for predicate in predicates
            if isinstance(predicate, dict) and predicate.get("result") != "pass"
        )

    expected_coverage = {
        "registered": len(ideal_forms),
        "verified": sum(state == "verified" for state in computed_states),
        "blocked": sum(state == "blocked" for state in computed_states),
        "incomplete": sum(state == "partial" for state in computed_states),
    }
    for key, expected in expected_coverage.items():
        if coverage.get(key) != expected:
            errors.append(f"coverage.{key} must equal {expected}")

    if set(readiness.get("incomplete_predicates", [])) != incomplete_predicate_ids:
        errors.append(
            "readiness.incomplete_predicates must exactly name every non-pass predicate"
        )
    blocked_predicate_ids = {
        predicate.get("predicate_id")
        for ideal in ideal_forms
        if isinstance(ideal, dict)
        for predicate in ideal.get("predicates", [])
        if isinstance(predicate, dict) and predicate.get("result") == "blocked"
    }
    if not blocked_predicate_ids.issubset(
        set(readiness.get("unresolved_blockers", []))
    ):
        errors.append(
            "blocked ideal predicates must appear in readiness.unresolved_blockers"
        )

    exact_all = (
        not duplicate_ideals
        and derivations_complete
        and all(coverage.get(key) == value for key, value in expected_coverage.items())
    )
    errors.extend(
        _readiness_errors(
            data,
            exact_all=exact_all,
            prerequisites_ready=all(
                state == "verified" for state in computed_states
            ),
        )
    )
    return errors


def _node_self_image_set_errors(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    registry_projection = data.get("registry_projection")
    registered_node_ids = data.get("registered_node_ids")
    self_images = data.get("self_images")
    counts = data.get("counts")
    if (
        not isinstance(registry_projection, list)
        or not isinstance(registered_node_ids, list)
        or not isinstance(self_images, list)
        or not isinstance(counts, dict)
    ):
        return errors

    projection_node_ids = [
        node.get("uid") for node in registry_projection if isinstance(node, dict)
    ]
    duplicate_projection_nodes = _duplicates(projection_node_ids)
    if duplicate_projection_nodes:
        errors.append(
            "registry_projection contains duplicate uid values: "
            f"{duplicate_projection_nodes}"
        )
    projection_ordered = projection_node_ids == sorted(
        node_id for node_id in projection_node_ids if isinstance(node_id, str)
    )
    if not projection_ordered:
        errors.append("registry_projection must be ordered by ascending uid")

    reference_matches = data.get("registry_reference") == "#/registry_projection"
    if not reference_matches:
        errors.append(
            "registry_reference must resolve to the embedded registry_projection"
        )
    try:
        canonical_projection = rfc8785.dumps(registry_projection)
    except rfc8785.CanonicalizationError:
        digest_matches = False
        errors.append("registry_projection must be RFC 8785 canonicalizable")
    else:
        expected_registry_digest = (
            "sha256:" + hashlib.sha256(canonical_projection).hexdigest()
        )
        digest_matches = data.get("registry_digest") == expected_registry_digest
        if not digest_matches:
            errors.append(
                "registry_digest must equal sha256(RFC 8785 registry_projection)"
            )

    denominator_matches = registered_node_ids == projection_node_ids
    if not denominator_matches:
        errors.append(
            "registered_node_ids must derive exactly, in order, from "
            "registry_projection uid values"
        )

    image_node_ids = [
        image.get("node_id") for image in self_images if isinstance(image, dict)
    ]
    duplicate_images = _duplicates(image_node_ids)
    if duplicate_images:
        errors.append(
            f"self_images contain duplicate node_id values: {duplicate_images}"
        )
    registered_node_id_set = {
        value for value in registered_node_ids if isinstance(value, str)
    }
    image_node_id_set = {
        value for value in image_node_ids if isinstance(value, str)
    }
    missing_images = sorted(registered_node_id_set - image_node_id_set)
    extra_images = sorted(image_node_id_set - registered_node_id_set)
    if missing_images:
        errors.append(
            f"registered nodes missing self-images: {missing_images}"
        )
    if extra_images:
        errors.append(
            f"self-images exist for unregistered nodes: {extra_images}"
        )
    image_order_matches = image_node_ids == registered_node_ids
    if not image_order_matches:
        errors.append(
            "self_images must follow the registered_node_ids order"
        )
    if counts.get("registered") != len(registered_node_ids):
        errors.append("counts.registered must equal registered_node_ids length")
    if counts.get("exported") != len(self_images):
        errors.append("counts.exported must equal self_images length")

    exact_all = (
        not duplicate_projection_nodes
        and projection_ordered
        and reference_matches
        and digest_matches
        and denominator_matches
        and not duplicate_images
        and not missing_images
        and not extra_images
        and image_order_matches
        and counts.get("registered") == len(registered_node_ids)
        and counts.get("exported") == len(self_images)
    )
    errors.extend(_readiness_errors(data, exact_all=exact_all))
    return errors


def _governance_stage_receipt_errors(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    child_receipts = data.get("child_receipts")
    cursor = data.get("cursor")
    counts = data.get("counts")
    limits = data.get("execution_limits")
    inputs = data.get("inputs")
    outputs = data.get("outputs")
    if (
        not isinstance(cursor, dict)
        or not isinstance(counts, dict)
        or not isinstance(limits, dict)
        or not isinstance(child_receipts, list)
        or not isinstance(inputs, list)
        or not isinstance(outputs, list)
    ):
        return errors

    child_ids = [
        child.get("child_id") for child in child_receipts if isinstance(child, dict)
    ]
    duplicate_children = _duplicates(child_ids)
    if duplicate_children:
        errors.append(
            f"child_receipts contain duplicate child_id values: {duplicate_children}"
        )

    completed_child_ids = set(cursor.get("completed_child_ids", []))
    pending_child_ids = set(cursor.get("pending_child_ids", []))
    if completed_child_ids.intersection(pending_child_ids):
        errors.append(
            "cursor completed_child_ids and pending_child_ids must be disjoint"
        )
    if completed_child_ids | pending_child_ids != set(child_ids):
        errors.append(
            "cursor child IDs must classify every child receipt exactly once"
        )

    statuses = [
        child.get("status") for child in child_receipts if isinstance(child, dict)
    ]
    expected_completed_ids = {
        child.get("child_id")
        for child in child_receipts
        if isinstance(child, dict)
        and child.get("status") in {"completed", "skipped_completed"}
    }
    if completed_child_ids != expected_completed_ids:
        errors.append(
            "cursor.completed_child_ids must exactly match completed and skipped children"
        )

    expected_counts = Counter(statuses)
    for field in ("completed", "skipped_completed", "failed", "blocked"):
        if counts.get(field) != expected_counts.get(field, 0):
            errors.append(
                f"counts.{field} must equal the number of child receipts with that status"
            )
    expected_attempted = (
        expected_counts.get("completed", 0)
        + expected_counts.get("failed", 0)
        + expected_counts.get("blocked", 0)
    )
    if counts.get("attempted") != expected_attempted:
        errors.append(
            "counts.attempted must count completed, failed, and blocked executions "
            "but exclude skipped completed children"
        )

    if len(child_receipts) > limits.get("max_work_items", -1):
        errors.append("child_receipts exceed execution_limits.max_work_items")
    output_size = sum(
        output.get("size_bytes", 0)
        for output in outputs
        if isinstance(output, dict)
    )
    if output_size > limits.get("max_output_bytes", -1):
        errors.append("outputs exceed execution_limits.max_output_bytes")

    if data.get("stage") == "discover":
        if data.get("predecessor_receipt_digest") is not None:
            errors.append("discover stage predecessor_receipt_digest must be null")
    elif data.get("predecessor_receipt_digest") is None:
        errors.append("every non-discover stage requires a predecessor receipt digest")

    if data.get("status") == "completed":
        if pending_child_ids:
            errors.append("a completed stage must not retain pending children")
        if any(status in {"failed", "blocked"} for status in statuses):
            errors.append("a completed stage must not contain failed or blocked children")
        if cursor.get("resume_token") is not None:
            errors.append("a completed stage cursor must not retain a resume_token")
    return errors


def _governance_cadence_receipt_errors(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    stage_receipts = data.get("stage_receipts")
    fixed_point = data.get("fixed_point")
    if not isinstance(stage_receipts, list) or not isinstance(fixed_point, dict):
        return errors

    stages = [
        receipt.get("stage") for receipt in stage_receipts if isinstance(receipt, dict)
    ]
    stage_receipt_ids = [
        receipt.get("stage_receipt_id")
        for receipt in stage_receipts
        if isinstance(receipt, dict)
    ]
    duplicate_receipts = _duplicates(stage_receipt_ids)
    if duplicate_receipts:
        errors.append(
            f"stage_receipts contain duplicate stage_receipt_id values: {duplicate_receipts}"
        )
    ordered = tuple(stages) == CADENCE_STAGES
    if not ordered:
        errors.append(
            "stage_receipts must contain discover -> snapshot -> parse -> classify -> "
            "reconcile -> distill -> validate -> render -> receipt exactly once"
        )

    chain_complete = True
    for index, receipt in enumerate(stage_receipts):
        if not isinstance(receipt, dict):
            chain_complete = False
            continue
        expected_predecessor = (
            None
            if index == 0
            else stage_receipts[index - 1].get("receipt_digest")
            if isinstance(stage_receipts[index - 1], dict)
            else None
        )
        if receipt.get("predecessor_receipt_digest") != expected_predecessor:
            errors.append(
                f"stage receipt at index {index} does not bind its predecessor digest"
            )
            chain_complete = False

    run_number = data.get("run_number")
    previous_digest = data.get("previous_cadence_receipt_digest")
    previous_output_digest = fixed_point.get("previous_output_digest")
    if run_number == 1 and previous_digest is not None:
        errors.append("cadence run 1 must not name a previous cadence receipt")
    if isinstance(run_number, int) and run_number > 1 and previous_digest is None:
        errors.append("cadence runs after run 1 must bind the previous cadence receipt")
    if run_number == 1 and previous_output_digest is not None:
        errors.append("cadence run 1 must not name a previous output digest")
    if run_number == 2 and previous_output_digest is None:
        errors.append("cadence run 2 must bind the previous output digest")

    output_matches_previous = (
        previous_output_digest is not None
        and previous_output_digest == data.get("output_digest")
    )
    if fixed_point.get("output_digest_matches_previous") is not output_matches_previous:
        errors.append(
            "fixed_point.output_digest_matches_previous must equal the comparison "
            "between fixed_point.previous_output_digest and output_digest"
        )

    fixed_status = fixed_point.get("status")
    fixed_proven = (
        run_number == 2
        and fixed_status == "proven"
        and fixed_point.get("new_event_count") == 0
        and fixed_point.get("changed_byte_count") == 0
        and fixed_point.get("replayed_completed_children") == 0
        and output_matches_previous
    )
    if fixed_status == "proven" and not fixed_proven:
        errors.append(
            "fixed_point.status 'proven' requires zero events, bytes, and completed-child "
            "replays plus an output digest match"
        )
    if previous_digest is None and fixed_status != "not_applicable":
        errors.append("the first cadence run fixed point must be not_applicable")

    all_completed = all(
        isinstance(receipt, dict) and receipt.get("status") == "completed"
        for receipt in stage_receipts
    )
    exact_all = (
        ordered
        and chain_complete
        and not duplicate_receipts
        and len(stage_receipts) == len(CADENCE_STAGES)
        and fixed_proven
    )
    errors.extend(
        _readiness_errors(
            data,
            exact_all=exact_all,
            prerequisites_ready=all_completed and fixed_proven,
        )
    )
    return errors


def _governance_atlas_receipt_errors(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    snapshot_id = data.get("snapshot_id")
    references = (
        "source_envelope_set",
        "assertion_evidence_set",
        "ideal_form_register",
        "node_self_image_set",
        "iceberg_atlas",
    )
    snapshot_matches = True
    for field in references:
        reference = data.get(field)
        if isinstance(reference, dict) and reference.get("snapshot_id") != snapshot_id:
            errors.append(f"{field}.snapshot_id must match the receipt snapshot_id")
            snapshot_matches = False

    predicate_results = data.get("predicate_results")
    all_predicates_pass = isinstance(predicate_results, dict) and all(
        value is True for value in predicate_results.values()
    )
    exact_all = snapshot_matches
    errors.extend(
        _readiness_errors(
            data,
            exact_all=exact_all,
            prerequisites_ready=all_predicates_pass,
        )
    )
    return errors


def _governance_snapshot_bundle_errors(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    snapshot_id = data.get("snapshot_id")
    snapshot_digest = data.get("snapshot_digest")
    embedded_documents_valid = True

    embedded_contracts = (
        ("normalized_events", "event_id"),
        ("source_envelopes", "source_id"),
        ("assertion_evidence", "assertion_id"),
    )
    for field, identity_field in embedded_contracts:
        documents = data.get(field)
        if not isinstance(documents, list):
            continue
        identities = [
            document.get(identity_field)
            for document in documents
            if isinstance(document, dict)
        ]
        duplicates = _duplicates(identities)
        if duplicates:
            errors.append(f"{field} contains duplicate {identity_field} values: {duplicates}")
            embedded_documents_valid = False
        for index, document in enumerate(documents):
            schema_errors, invariant_errors = validate_document(document)
            if schema_errors or invariant_errors:
                embedded_documents_valid = False
                for error in schema_errors:
                    errors.append(f"{field}[{index}] schema: {error}")
                for error in invariant_errors:
                    errors.append(f"{field}[{index}] semantic: {error}")

    snapshot_matches = True
    for index, event in enumerate(data.get("normalized_events", [])):
        if not isinstance(event, dict):
            continue
        if event.get("snapshot_id") != snapshot_id:
            errors.append(
                f"normalized_events[{index}].snapshot_id must match bundle snapshot_id"
            )
            snapshot_matches = False
        if event.get("snapshot_digest") != snapshot_digest:
            errors.append(
                f"normalized_events[{index}].snapshot_digest must match bundle snapshot_digest"
            )
            snapshot_matches = False
    for index, envelope in enumerate(data.get("source_envelopes", [])):
        if not isinstance(envelope, dict):
            continue
        custody_snapshot = envelope.get("custody_snapshot")
        if not isinstance(custody_snapshot, dict):
            continue
        if custody_snapshot.get("snapshot_id") != snapshot_id:
            errors.append(
                f"source_envelopes[{index}] custody snapshot must match bundle snapshot_id"
            )
            snapshot_matches = False
        if custody_snapshot.get("snapshot_hash") != snapshot_digest:
            errors.append(
                f"source_envelopes[{index}] custody hash must match bundle snapshot_digest"
            )
            snapshot_matches = False

    reference_fields = (
        "source_census",
        "lineage_graph",
        "governance_testament",
        "coverage",
        "ideal_form_register",
        "node_self_image_set",
        "iceberg_atlas",
        "normalization_parity_receipt",
        "governance_atlas_receipt",
    )
    for field in reference_fields:
        reference = data.get(field)
        if isinstance(reference, dict) and reference.get("snapshot_id") != snapshot_id:
            errors.append(f"{field}.snapshot_id must match bundle snapshot_id")
            snapshot_matches = False

    stage_receipts = data.get("governance_stage_receipts")
    stages: list[Any] = []
    if isinstance(stage_receipts, list):
        stages = [
            receipt.get("stage")
            for receipt in stage_receipts
            if isinstance(receipt, dict)
        ]
        if tuple(stages) != CADENCE_STAGES:
            errors.append(
                "governance_stage_receipts must preserve the exact nine-stage order"
            )
        for index, receipt in enumerate(stage_receipts):
            if isinstance(receipt, dict) and receipt.get("snapshot_id") != snapshot_id:
                errors.append(
                    f"governance_stage_receipts[{index}].snapshot_id must match bundle"
                )
                snapshot_matches = False

    cadence_receipts = data.get("governance_cadence_receipts")
    cadence_snapshot_matches = True
    if isinstance(cadence_receipts, list):
        for index, receipt in enumerate(cadence_receipts):
            if isinstance(receipt, dict) and receipt.get("snapshot_id") != snapshot_id:
                errors.append(
                    f"governance_cadence_receipts[{index}].snapshot_id must match bundle"
                )
                cadence_snapshot_matches = False
                snapshot_matches = False

    final_fixed_point = False
    if isinstance(cadence_receipts, list) and len(cadence_receipts) == 2:
        first, second = cadence_receipts
        if isinstance(first, dict) and isinstance(second, dict):
            final_fixed_point = (
                first.get("run_number") == 1
                and first.get("previous_receipt_digest") is None
                and second.get("run_number") == 2
                and second.get("previous_receipt_digest") == first.get("digest")
                and second.get("output_digest") == first.get("output_digest")
                and second.get("fixed_point_status") == "proven"
                and second.get("new_event_count") == 0
                and second.get("changed_byte_count") == 0
                and second.get("replayed_completed_children") == 0
                and first.get("ready") is True
                and second.get("ready") is True
            )
            probe = data.get("post_proof_idempotence")
            final_fixed_point = final_fixed_point and isinstance(probe, dict) and (
                probe.get("cadence_receipt_digest") == second.get("digest")
                and probe.get("output_digest") == second.get("output_digest")
                and probe.get("status") == "proven"
                and probe.get("new_event_count") == 0
                and probe.get("changed_byte_count") == 0
                and probe.get("replayed_completed_children") == 0
                and probe.get("emitted_receipt_count") == 0
            )
    if len(cadence_receipts or []) == 2 and not final_fixed_point:
        errors.append(
            "two cadence receipts must bind run 1 to byte-identical run 2, then a "
            "post-proof invocation must emit zero events, bytes, receipts, or child replays"
        )

    assertions_verified = all(
        isinstance(assertion, dict)
        and assertion.get("verification_state") == "verified"
        for assertion in data.get("assertion_evidence", [])
    )
    testament = data.get("governance_testament")
    coverage = data.get("coverage")
    ideal_register = data.get("ideal_form_register")
    self_images = data.get("node_self_image_set")
    parity = data.get("normalization_parity_receipt")
    atlas_receipt = data.get("governance_atlas_receipt")
    strict_prerequisites = (
        assertions_verified
        and isinstance(testament, dict)
        and testament.get("status") == "ratified"
        and testament.get("constitutional_coverage_ready") is True
        and isinstance(coverage, dict)
        and coverage.get("exact_all") is True
        and coverage.get("ready") is True
        and isinstance(ideal_register, dict)
        and ideal_register.get("ready") is True
        and isinstance(self_images, dict)
        and self_images.get("ready") is True
        and isinstance(parity, dict)
        and parity.get("ready") is True
        and isinstance(atlas_receipt, dict)
        and atlas_receipt.get("ready") is True
        and tuple(stages) == CADENCE_STAGES
        and cadence_snapshot_matches
        and final_fixed_point
    )
    exact_all = (
        embedded_documents_valid
        and snapshot_matches
        and tuple(stages) == CADENCE_STAGES
    )
    errors.extend(
        _readiness_errors(
            data,
            exact_all=exact_all,
            prerequisites_ready=strict_prerequisites,
        )
    )
    return errors


def semantic_errors(data: Any, *, now: datetime | None = None) -> list[str]:
    """Return contract-specific semantic invariant failures."""
    if not isinstance(data, dict):
        return []
    contract_name = data.get("contract_name")
    if contract_name == "source-census.v1":
        return _source_census_errors(data)
    if contract_name == "normalized-event.v1":
        return _normalized_event_errors(data)
    if contract_name == "normalization-parity-receipt.v1":
        return _normalization_parity_errors(data)
    if contract_name == "ideal-form-register.v1":
        return _ideal_form_register_errors(data)
    if contract_name == "node-self-image-set.v1":
        return _node_self_image_set_errors(data)
    if contract_name == "governance-stage-receipt.v1":
        return _governance_stage_receipt_errors(data)
    if contract_name == "governance-cadence-receipt.v1":
        return _governance_cadence_receipt_errors(data)
    if contract_name == "governance-atlas-receipt.v1":
        return _governance_atlas_receipt_errors(data)
    if contract_name == "governance-snapshot-bundle.v1":
        return _governance_snapshot_bundle_errors(data)
    if contract_name == "coverage-receipt.v1":
        return _coverage_errors(data)
    if contract_name == "assertion-evidence.v1":
        return _assertion_errors(data, now=now)
    if contract_name == "parameter-contract.v1":
        return _parameter_errors(data)
    if contract_name == "lineage-graph.v1":
        return _lineage_errors(data)
    if contract_name == "governance-testament.v1":
        return _testament_errors(data)
    return []


def validate_document(
    data: Any, schemas_dir: Path = SCHEMAS_DIR
) -> tuple[list[str], list[str]]:
    """Return (schema errors, semantic errors) for one decoded document."""
    raw_contract_name = data.get("contract_name") if isinstance(data, dict) else None
    if not isinstance(raw_contract_name, str):
        return [f"unknown governance-memory contract_name: {raw_contract_name!r}"], []
    contract_name = raw_contract_name
    schema_filename = CONTRACT_TO_SCHEMA.get(contract_name)
    if schema_filename is None:
        return [f"unknown governance-memory contract_name: {contract_name!r}"], []
    schema = load_json(schemas_dir / schema_filename)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    schema_errors = []
    for error in sorted(validator.iter_errors(data), key=lambda item: list(item.absolute_path)):
        path = ".".join(str(part) for part in error.absolute_path) or "(root)"
        schema_errors.append(f"{path}: {error.message}")
    return schema_errors, semantic_errors(data)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate governance-memory contracts and semantic invariants"
    )
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--schemas-dir", type=Path, default=SCHEMAS_DIR)
    args = parser.parse_args()

    failures = 0
    for path in args.files:
        try:
            data = load_json(path)
            schema_errors, invariant_errors = validate_document(data, args.schemas_dir)
        except (OSError, json.JSONDecodeError) as exc:
            schema_errors, invariant_errors = [str(exc)], []
        errors = [*(f"schema: {error}" for error in schema_errors), *(
            f"semantic: {error}" for error in invariant_errors
        )]
        if errors:
            failures += 1
            print(f"FAIL {path}")
            for error in errors:
                print(f"  {error}")
        else:
            print(f"PASS {path}")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
