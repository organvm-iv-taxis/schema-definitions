# Preserve declared visibility policy

Owner: schema #19 and registry #553; Codex gap-filling-20260915.

The hierarchy verification standard (section L6) requires FULLY PUBLIC and MOSTLY PUBLIC distinctions. The genesis transcript preserves SEMI-PUBLIC policy with qualifiers. Add those declared categories alongside existing PUBLIC, PRIVATE, and MIXED. Store historical captions intact in public_visibility_note; this field does not assert current counts, public repository state, or publication consent.

Normalize only the three known captions, preserving their entire original text. Conflicting notes fail rather than being overwritten. Unknown captions remain visible.

Verification: 192 schema tests, 48 examples and ruff pass; four normalization tests cover full-object preservation, idempotence, malformed values, and note conflicts. Repeated dry-run produces zero changes. Candidate whole-registry validation now has one error, the historical obligation status; it remains owned by #553. No lifecycle state or evidence date changed.

Schema acceptance remains prerequisite to registry acceptance and subsequent Editorial regeneration. This source repair is not deployment or Reader-mode acceptance.
