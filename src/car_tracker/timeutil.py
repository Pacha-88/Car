"""SQLite (and this project's plain `DateTime` columns) don't round-trip
tzinfo — a value written as timezone-aware comes back naive on read. Rather
than fight that per-backend, every stored/compared timestamp in this project
is naive UTC; this is the one place that constructs "now" for that purpose,
so a comparison against a DB-sourced value never mixes aware and naive.
"""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
