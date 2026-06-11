"""Task board (kanban) view helpers.

Loads tickets from disk and groups them into board columns. Pure read logic;
mutations (review decision, status move) go through storage from the routes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from storage import list_ticket_json_files, load_ticket

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
    return {
        "id": t.ticket_id,
        "title": t.title,
        "status": _enum(t.status),
        "specialist": _enum(t.specialist_type),
        "domain": _enum(t.domain_type),
        "priority": _enum(t.priority),
    }


def board() -> list[dict]:
    """Return columns, each with its list of ticket cards (newest first)."""
    cols = []
    for col in COLUMNS:
        cards = []
        for folder in col["folders"]:
            for path in list_ticket_json_files(folder):
                try:
                    env = load_ticket(path)
                except Exception:
                    continue
                cards.append(_card(env, path))
        cols.append({**col, "cards": cards, "count": len(cards)})
    return cols
