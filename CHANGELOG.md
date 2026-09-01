# Changelog

## Unreleased

- Add `project-record-v1.schema.json` and a valid YAML example for reader-mode
  documentation, with canonical identity, implementation/deployment state,
  authorship, structured claim posture, assertion-evidence references,
  class-aware audience routes, limitations, industry applicability, and
  search-intent separation.
- Require pilot and public deployment states to cite an implemented or partial
  deployment claim, and define conservative retired-state posture semantics;
  the integrity runtime separately requires the qualifying assertion to be
  verified.
- Restrict Class D records to noncanonical `deployment-artifact` or `mirror`
  roles so their canonical redirect cannot collapse into a self-reference.
- Clarify current GitHub authority while retaining historical schema `$id`
  namespaces as stable compatibility identifiers.
- Add eighteen governance-memory v1 contracts for source custody projections,
  dynamic source census, stable normalized events, complete normalization
  parity, dual-lane lineage, governance testament, assertion evidence,
  receipt-derived ideals, node self-images, Iceberg Atlas rendering, bounded
  nine-stage cadence, frozen snapshot bundles, exact coverage, owner
  resolution, and typed parameters.
- Add provider-neutral examples and semantic validation for exact coverage,
  stable identity, promotion crosswalks, evidence independence, reviewed
  adoption, candidate/ratification gates, self-image completeness, stage
  bounds, receipt chaining, two-run fixed points, and secret-reference safety.
- Define `exact_all` as exactly-once classification of the frozen denominator;
  expose `ready` separately so classified inaccessible sources retain owner
  debt, and prohibit `closed_with_owner_routed_debt` from aliasing readiness.
- Require a separately typed constitutional coverage scope whose readiness is
  exact if and only if its named authority scope is exact and carries no blocked
  scopes or missing requirements, without weakening global coverage readiness.
- Require candidate testaments to omit ratification and ratified testaments to
  bind immutable operator events, assertion evidence, the candidate digest,
  controlling formulation, and unblocked constitutional coverage.
- Add regression fixtures proving renamed and newly introduced providers require
  configuration changes only.

## 1.0.0 (2026-03-04)

- Formalized as v1.0.0 — all 6 schemas stable and validated in production since 2026-02-17
- `registry-v2.schema.json`: `schema_version` field now constrained to enum `["1.0.0", "1.0.1", "1.1.0"]`
- All schemas validated against live data across 103 repos for 15+ days
- No breaking changes from 0.1.0 — this release formalizes the existing contracts

## 0.1.0 (2026-02-17)

- Initial release: 6 JSON Schema definitions
- Schemas: registry-v2, seed-v1, governance-rules, dispatch-payload, soak-test, system-metrics
- Example files for registry, seed, and dispatch
- Validation script and pytest suite
