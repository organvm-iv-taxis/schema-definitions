# schema-definitions

Canonical JSON Schema definitions for the organvm eight-organ system's data contracts.

## Schemas

| Schema | Validates | Source of Truth |
|--------|-----------|-----------------|
| `project-record-v1.schema.json` | Canonical identity, state, authorship, assertion references, reader routes, and search intent for one repository project | Reader-mode documentation contract |
| `registry-v2.schema.json` | `registry-v2.json` | Repository state across all 8 organs |
| `seed-v1.schema.json` | `seed.yaml` | Per-repo automation contracts |
| `governance-rules.schema.json` | `governance-rules.json` | Dependency rules, promotion state machine |
| `dispatch-payload.schema.json` | Cross-org dispatch events | ORGAN-IV routing payloads |
| `soak-test.schema.json` | `daily-*.json` | VIGILIA soak test snapshots |
| `system-metrics.schema.json` | `system-metrics.json` | Computed + manual system metrics |
| `conversation-corpus-surface-manifest.schema.json` | `conversation-corpus-surface-manifest-*.json` | Exported CCE engine surface manifest |
| `conversation-corpus-mcp-context.schema.json` | `conversation-corpus-mcp-context-*.json` | Exported CCE MCP-facing context payload |
| `conversation-corpus-surface-bundle.schema.json` | `conversation-corpus-surface-bundle-*.json` | Exported CCE validation bundle |

### Governance-memory contracts

These versioned interfaces separate private source custody from public,
provider-neutral projections. Provider names, owner locations, repository URLs,
and other live values are contract data resolved at runtime; the schemas do not
embed a provider catalog or deployment-specific path.

| Contract | Responsibility |
|----------|----------------|
| `project-record-v1.schema.json` | One project's invariant facts and audience projections, linked to assertion-evidence records |
| `source-envelope.v1.schema.json` | Provider-neutral source identity, authority, raw-unit content binding, and private custody pointer |
| `lineage-graph.v1.schema.json` | Separate operator-intent and artifact timelines with reviewed typed edges |
| `governance-testament.v1.schema.json` | Ratified directives, layers, instruments, ideals, predicates, and citations |
| `assertion-evidence.v1.schema.json` | Evidence independence, verification, and freshness for assertions |
| `node-self-image.v1.schema.json` | Identity, relations, cursors, state, digests, and distance to active ideals |
| `coverage-receipt.v1.schema.json` | Dynamic denominator, exact classification, separate global and constitutional-scope readiness, and residual owners |
| `owner-reference.v1.schema.json` | Stable owner IDs resolved through owner-native records |
| `parameter-contract.v1.schema.json` | Typed runtime parameters, validation, freshness, and secret-reference policy |
| `source-census.v1.schema.json` | Runtime enumeration of Git refs, workspaces, custody manifests, application stores, exports, and connectors |
| `normalized-event.v1.schema.json` | Stable native event identity plus immutable raw-unit content binding, independent of snapshot and transport position |
| `normalization-parity-receipt.v1.schema.json` | Complete content-bound raw-unit-to-event-or-disposition promotion crosswalk |
| `ideal-form-register.v1.schema.json` | Receipt-derived ideal status, implementation predicates, and distance |
| `iceberg-atlas.v1.schema.json` | Two authority timelines and six populated graph zooms |
| `node-self-image-set.v1.schema.json` | Exactly one valid self-image for every registered node |
| `governance-stage-receipt.v1.schema.json` | Bounded, resumable receipt for one cadence stage |
| `governance-cadence-receipt.v1.schema.json` | Ordered nine-stage receipt chain and fixed-point evidence |
| `governance-atlas-receipt.v1.schema.json` | Assertion, ideal, self-image, timeline, zoom, and Atlas readiness |
| `governance-snapshot-bundle.v1.schema.json` | Frozen cross-owner bundle with two-run and post-proof idempotence |

For `project-record.v1`, a `pilot` or `public` deployment state is established
only by an `implemented` or `partial` deployment claim that resolves to a
verified, non-expired `current_state` assertion whose machine-readable
`fact.predicate` is `deployment_status` and whose `fact.value` exactly matches
the project record. A `retired` state still requires verified evidence, but may
use a matching historical assertion; its qualifying claim may also be
`contradicted` when the evidence establishes that the former deployment is now
unavailable. `proposed` and `unknown` claims never establish any of those three
lifecycle states.

Likewise, every `deployed` or `piloted` industry resolves at least one cited
deployment or adoption claim to verified, fresh `current_state` evidence. Its
machine-readable fact uses `industry_status`, names the industry in
`fact.subject`, binds `fact.project_repository` to `canonical_repository`, and
exactly matches the declared industry status.

Authorship declarations are likewise evidence-bound: an implemented or partial
authorship claim resolves to a verified factual `authorship` assertion whose
project, subject, role value, contributions, collaborators, generated,
inherited, and external vocabularies exactly match the project record.

Class D records are noncanonical delivery surfaces and therefore use either the
`deployment-artifact` or `mirror` repository role. Their
`canonical_repository` and redirect target identify the same upstream
repository, and `links.repository` must identify that upstream as well. CI
validates the bundled synthetic fixture without asserting a checkout identity.
Callers validating a live Class D checkout must pass its owner/name through
`--actual-repository`; the integrity runtime then requires it to be distinct
from the canonical target.

`exact_all` means complete classification of the declared denominator. It does
not mean ready. Wherever a contract exposes `readiness`, `ready` additionally
requires no unresolved blockers, quarantines, missing requirements, citation
debt, or incomplete predicates. `closed_with_owner_routed_debt` is an honest
closure state but can never alias `ready`.

A coverage receipt also carries a required `constitutional_scope`. Its `ready`
value is true exactly when that named scope is exact and has no blocked scopes
or missing requirements. Constitutional readiness is intentionally independent
of global readiness: CORPVS may ratify from complete authority evidence while
unrelated upstream normalization debt keeps the receipt's top-level `ready`
false.

The normalization contracts carry the census `raw_unit_content_hash` through
source envelopes, normalized events, and every parity promotion. The parity input
also embeds the full raw-unit/hash denominator, and semantic validation requires
the promotion bindings to match it exactly. Stable event IDs remain derived only
from native identity, native role, and normalized content identity.

## Usage

```bash
# Validate a file (auto-detects schema from filename)
python scripts/validate.py path/to/registry-v2.json

# Validate all examples
python scripts/validate.py --all-examples

# Strictly bind a project record to its local assertions/evidence and to the
# checked-out GitHub identity (required for Class D delivery surfaces)
python scripts/validate.py project-record.yml \
  --repository-root . \
  --actual-repository "$GITHUB_REPOSITORY"

# Validate governance-memory shape and cross-field invariants
python scripts/validate_governance_memory.py \
  examples/{owner-reference,parameter-contract,source-envelope,assertion-evidence,lineage-graph,governance-testament,node-self-image,coverage-receipt}-v1-example.json

# The same validator covers the truth-first census, normalization, Atlas,
# cadence, and frozen-bundle contracts listed above.

# Run tests
pytest
```

## Install

```bash
pip install -e ".[dev]"
```

Requires: Python 3.11+, `jsonschema`, `pyyaml`.

## Authority and schema identifiers

The canonical GitHub authority for this repository is
[`organvm-iv-taxis/schema-definitions`](https://github.com/organvm-iv-taxis/schema-definitions).
It provides system-wide data contracts validated by `organvm-engine`.

Some pre-existing schemas retain `$id` values under the historical
`meta-organvm.github.io` namespace. Those identifiers remain stable for
compatibility; they are schema identifiers, not a statement of current GitHub
ownership. New contracts use the current canonical authority namespace.
