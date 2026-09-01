"""Deterministic JSON Schema format checks without optional dependency drift."""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlsplit

from jsonschema import FormatChecker

FORMAT_CHECKER = FormatChecker()
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*$")


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
    if "T" not in value.upper():
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None
