"""Canonical timestamp format for all Fill / Trade timestamps.

Every ``Fill.timestamp`` reaching the engine MUST be in the canonical form:

    YYYY-MM-DDTHH:MM:SS

- Always UTC.
- No ``Z`` suffix, no ``+00:00`` suffix, no fractional seconds.
- Lexicographic order == chronological order (used by the poll watermark).

This module is broker-agnostic. :func:`normalize_timestamp` only accepts
**ISO-8601** input. Each relay adapter is responsible for converting its
broker's native timestamp format (IBKR Flex, IBKR bridge, …) into
ISO-8601 before calling this helper — keeping broker-specific parsing
colocated with the relay that owns it.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Accepted ISO-8601 grammar for normalize_timestamp: the full date + time
# form, with optional fractional seconds and optional tz designator. This
# explicitly rejects date-only (``2026-04-19``) and truncated-time
# (``2026-04-19T15:30``) inputs that ``datetime.fromisoformat`` would
# silently inflate to midnight / zero-seconds.
_ISO_8601_FULL_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"  # required date + time
    r"(\.\d+)?"                                # optional fractional seconds
    r"(Z|[+-]\d{2}:\d{2})?$"                  # optional tz designator
)


def normalize_timestamp(raw: str, *, assume_tz: tzinfo | None = None) -> str:
    """Return *raw* (ISO-8601) reformatted as canonical ``YYYY-MM-DDTHH:MM:SS`` UTC.

    Accepted grammar: ``YYYY-MM-DDTHH:MM:SS`` with optional fractional
    seconds (``.fff...``) and optional tz designator (``Z`` or
    ``±HH:MM``). Date-only inputs and truncated-time forms are rejected
    so we never silently invent midnight or zero-seconds.

    - Tz-aware inputs are converted to UTC (``assume_tz`` ignored).
    - Tz-naive inputs are interpreted in ``assume_tz`` (default: UTC).
    - Fractional seconds are dropped.

    Raises ``ValueError`` when *raw* is empty or doesn't match the
    accepted grammar.
    """
    if not raw:
        raise ValueError("empty timestamp")
    if not _ISO_8601_FULL_RE.match(raw):
        raise ValueError(
            f"Not a valid ISO-8601 timestamp "
            f"(expected YYYY-MM-DDTHH:MM:SS[.fff][Z|±HH:MM], got {raw!r})"
        )

    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"Not a valid ISO-8601 timestamp: {raw!r}") from exc

    tz = assume_tz if assume_tz is not None else UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    dt_utc = dt.astimezone(UTC).replace(microsecond=0)
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%S")


_CANONICAL_FORMAT = "%Y-%m-%dT%H:%M:%S"


def to_epoch(ts: str) -> int:
    """Return *ts* as Unix epoch seconds (UTC), or ``0`` for empty input.

    *ts* must be in the exact canonical form produced by
    :func:`normalize_timestamp` — ``YYYY-MM-DDTHH:MM:SS``, naive,
    interpreted as UTC. An empty string is treated as "no timestamp"
    and returns ``0`` to preserve the "no watermark" semantics used by
    the poller.

    Raises ``ValueError`` for any non-empty input that isn't exactly
    canonical (including tz-aware forms like ``...Z`` or ``...+02:00``,
    fractional seconds, or broker-specific formats). These shouldn't
    occur in practice — every Fill's timestamp passes through
    :func:`normalize_timestamp` upstream — and rejecting them here
    surfaces contract violations instead of silently tolerating drift.
    Callers that need permissive ISO-8601 parsing should use
    :func:`normalize_timestamp` first.
    """
    if not ts:
        return 0
    try:
        dt = datetime.strptime(ts, _CANONICAL_FORMAT)
    except ValueError as exc:
        raise ValueError(
            f"Not a canonical timestamp (expected YYYY-MM-DDTHH:MM:SS, got {ts!r})"
        ) from exc
    return int(dt.replace(tzinfo=UTC).timestamp())


def parse_timezone(name: str) -> ZoneInfo:
    """Return a ``ZoneInfo`` for *name*, or raise ``ValueError``.

    Small wrapper so callers can convert ``ZoneInfoNotFoundError`` into
    a message they control (e.g. ``SystemExit`` at boot).
    """
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown IANA timezone {name!r}") from exc
