# Preserve custom workflow declarations

Owner: schema PR #19 and organvm/organvm-corpvs-testamentvm#553.

The CI field names a repository workflow; it is not limited to the four shared
template names. Accept safe YAML basenames and null, rejecting directory paths,
refs, invalid types, empty strings, and trailing newlines. This does not assert
workflow execution, trigger configuration, or health.

The companion registry PR updates seed generation to preserve custom basenames
and reject malformed declarations rather than silently emitting no CI agent.
Legacy empty strings and the exact workflow-directory prefix are handled by that
consumer during migration; canonical schema validity still requires null/basename.

Verification: 191 schema tests and 48 examples pass; ruff and diff hygiene pass.
Read-only validation leaves 16 registry errors: 6 legacy workflow values,
7 visibility captions, 2 class spellings, and 1 historical obligation status.
These are owned by registry #553; no registry or lifecycle records were changed.
