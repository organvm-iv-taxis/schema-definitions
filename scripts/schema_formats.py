"""Deterministic JSON Schema format checks without optional dependency drift."""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlsplit

from jsonschema import FormatChecker

FORMAT_CHECKER = FormatChecker()
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*$")
_RFC3339_DATE_TIME = re.compile(
    r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])"
    r"[Tt](?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d"
    r"(?:\.\d+)?(?:[Zz]|[+-](?:[01]\d|2[0-3]):[0-5]\d)$"
)


@FORMAT_CHECKER.checks("uri")
def is_uri(value: object) -> bool:
    """Check absolute URI syntax for the contract's machine-readable links."""
    if not isinstance(value, str):
        return True
    if any(character.isspace() for character in value):
        return False
    parsed = urlsplit(value)
    if not parsed.scheme or not _SCHEME.fullmatch(parsed.scheme):
        return False
    if parsed.scheme in {"http", "https"}:
        return bool(parsed.netloc)
    return bool(parsed.path)


@FORMAT_CHECKER.checks("date-time")
def is_date_time(value: object) -> bool:
    """Check the timezone-bearing RFC 3339 subset used by ORGANVM records."""
    if not isinstance(value, str):
        return True
    if _RFC3339_DATE_TIME.fullmatch(value) is None:
        return False
    try:
        normalized = value.replace("Z", "+00:00").replace("z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return False
    return parsed.tzinfo is not None
