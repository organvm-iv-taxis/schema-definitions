# Preserve unknown revenue assessments

Owner: Codex direct gap-filling-20260915; schema PR #19, registry PR
organvm/organvm-corpvs-testamentvm#553, downstream Editorial PR #12.

## Decision

Allow explicit null in optional revenue model and status fields. Null records an
unassessed value; it does not assert `none`, `n/a`, or an accepted business outcome.
Retain the existing finite vocabulary for assessed values. Do not alter registry
records, historical validation dates, promotion states, or visibility policy.

## Verification

- `python3 -m pytest tests/ -q`: 190 passed.
- `ruff check scripts/ tests/`: passed.
- `pyright scripts/`: zero errors or warnings.
- `python3 scripts/validate.py --all-examples`: 48 passed.
- `git diff --check`: passed.
- Read-only registry validation: 45 errors reduced to 33, without registry edits.
  Remaining: 23 workflow representations, 7 visibility representations, 2 class
  spellings, 1 historical obligation status. These remain owned by registry #553.

Workflow vocabulary also feeds the seed generator's template map; changes must
cover that consumer. Visibility captions require preservation of their policy
meaning. Historical completion must not be converted to fresh acceptance proof.

Source acceptance requires the schema PR rail. This receipt does not establish
registry landing, Editorial regeneration, or runtime adoption.
