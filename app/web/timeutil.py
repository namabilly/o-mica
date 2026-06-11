"""Time helpers for the web app.

Resolves a 'created' time for tickets/outputs (schema field first, filename
prefix as fallback for items predating the created_at field) and formats it as
a friendly relative string with an exact ISO tooltip.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

_FILENAME_TS = re.compile(r"^(\d{8})-(\d{6})")


def parse_filename_dt(path: Path) -> Optional[datetime]:
    """Parse the YYYYMMDD-HHMMSS prefix from a saved filename, if present."""
    m = _FILENAME_TS.match(path.stem)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    except ValueError:
        return None


def parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def resolve_created(created_at: Optional[str], path: Optional[Path]) -> Optional[datetime]:
    """Created time: the schema field if set, else the filename timestamp."""
    return parse_iso(created_at) or (parse_filename_dt(path) if path else None)


def relative(dt: Optional[datetime]) -> str:
    """Friendly relative time, e.g. 'just now', '5m ago', '2d ago', 'Jun 9'."""
    if dt is None:
        return ""
    delta = datetime.now() - dt
    secs = delta.total_seconds()
    if secs < 0:
        return "just now"
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)}m ago"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago"
    if secs < 7 * 86400:
        return f"{int(secs // 86400)}d ago"
    # Older than a week → a compact date (cross-platform, no %-d).
    return f"{dt.strftime('%b')} {dt.day}"


def exact(dt: Optional[datetime]) -> str:
    """Exact timestamp for tooltips."""
    return dt.strftime("%Y-%m-%d %H:%M") if dt else ""


def time_info(created_at: Optional[str], path: Optional[Path]) -> dict:
    """Return {'rel': ..., 'exact': ...} for a created time."""
    dt = resolve_created(created_at, path)
    return {"rel": relative(dt), "exact": exact(dt)}
