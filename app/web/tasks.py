"""Task board (kanban) view helpers.

Loads tickets from disk and groups them into board columns. Pure read logic;
mutations (review decision, status move) go through storage from the routes.
Supports text search, specialist/domain/priority filters, and time sort.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from storage import list_ticket_json_files, load_ticket
from web.timeutil import resolve_created, relative, exact

# Board columns → the ticket folders they include.
COLUMNS = [
    {"key": "open", "label": "Open", "dot": "lav", "folders": ["open"]},
    {"key": "review", "label": "Review", "dot": "peach", "folders": ["under_review"]},
    {"key": "progress", "label": "In Progress", "dot": "sky", "folders": ["approved", "delegated"]},
    {"key": "done", "label": "Done", "dot": "mint", "folders": ["completed"]},
]


def _enum(v) -> str:
    return str(getattr(v, "value", v))


def _card(envelope, path: Path) -> dict:
    t = envelope.ticket
    dt = resolve_created(getattr(t, "created_at", None), path)
    return {
        "id": t.ticket_id,
        "title": t.title,
        "objective": t.objective,
        "status": _enum(t.status),
        "specialist": _enum(t.specialist_type),
        "domain": _enum(t.domain_type),
        "priority": _enum(t.priority),
        "_dt": dt or datetime.min,
        "rel": relative(dt),
        "exact": exact(dt),
    }


def _matches(card: dict, *, q: str, specialist: str, domain: str, priority: str) -> bool:
    if q:
        hay = f"{card['title']} {card['objective']}".lower()
        if q.lower() not in hay:
            return False
    if specialist and specialist != "all" and card["specialist"] != specialist:
        return False
    if domain and domain != "all" and card["domain"] != domain:
        return False
    if priority and priority != "all" and card["priority"] != priority:
        return False
    return True


def board(
    *,
    q: str = "",
    specialist: str = "all",
    domain: str = "all",
    priority: str = "all",
    sort: str = "new",
) -> list[dict]:
    """Return columns with filtered + sorted ticket cards."""
    cols = []
    for col in COLUMNS:
        cards = []
        for folder in col["folders"]:
            for path in list_ticket_json_files(folder):
                try:
                    env = load_ticket(path)
                except Exception:
                    continue
                card = _card(env, path)
                if _matches(card, q=q, specialist=specialist, domain=domain, priority=priority):
                    cards.append(card)
        cards.sort(key=lambda c: c["_dt"], reverse=(sort != "old"))
        cols.append({**col, "cards": cards, "count": len(cards)})
    return cols
