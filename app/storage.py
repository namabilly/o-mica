from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from schemas import TicketEnvelope, ReviewDecision, ReviewRecord, TicketStatus


ROOT = Path(__file__).resolve().parents[1]
TICKETS_DIR = ROOT / "tickets"

# Maps each ticket status to the subfolder it lives in under tickets/.
STATUS_TO_FOLDER = {
    TicketStatus.drafted: "open",
    TicketStatus.under_review: "under_review",
    TicketStatus.approved: "approved",
    TicketStatus.needs_revision: "open",
    TicketStatus.rejected: "rejected",
    TicketStatus.delegated: "delegated",
    TicketStatus.completed: "completed",
    TicketStatus.archived: "archived",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def ensure_ticket_dirs() -> None:
    """Create all ticket subfolders if they don't exist yet."""
    for folder in set(STATUS_TO_FOLDER.values()):
        (TICKETS_DIR / folder).mkdir(parents=True, exist_ok=True)


def slugify(text: str, max_len: int = 60) -> str:
    """Convert a title to a URL/filename-safe slug (ASCII + CJK)."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9一-鿿]+", "-", text)
    text = text.strip("-")
    return text[:max_len] or "ticket"


def folder_for_status(status: TicketStatus) -> str:
    """Return the subfolder name for a given ticket status."""
    return STATUS_TO_FOLDER.get(status, "open")


def _delete_old_files(json_path: Path) -> None:
    """Delete a ticket's JSON and Markdown files from their current location."""
    md_path = json_path.with_suffix(".md")
    if md_path.exists():
        md_path.unlink()
    if json_path.exists():
        json_path.unlink()


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def ticket_to_markdown(envelope: TicketEnvelope) -> str:
    """Render a TicketEnvelope as a human-readable Markdown document."""
    t = envelope.ticket

    def bullets(items: list[str]) -> str:
        return "\n".join(f"- {item}" for item in items) if items else "- None"

    review_history = "\n".join(
        f"- {r.timestamp or 'unknown time'} — {r.decision.value}: {r.note or 'No note'}"
        for r in t.review_history
    ) or "- None"

    return f"""# {t.title}

## Status
{t.status.value}

## Category
{t.category.value}

## Priority
{t.priority.value}

## Objective
{t.objective}

## Context
{t.context}

## Assumptions
{bullets(t.assumptions)}

## Missing Information
{bullets(t.missing_information)}

## Recommended Specialist
{t.recommended_specialist or "None"}

## Next Action
{t.next_action}

## Human Review Required
{t.human_review_required}

## Risks
{bullets(t.risks)}

## Deliverable Format
{t.deliverable_format}

## Handoff Prompt
{t.handoff_prompt or "None"}

## Archive Notes
{t.archive_notes or "None"}

## Review Questions
{bullets(envelope.review_questions)}

## Suggested User Reply
{envelope.suggested_user_reply or "None"}

## Review History
{review_history}
"""


def write_ticket_files(envelope: TicketEnvelope, json_path: Path) -> tuple[Path, Path]:
    """Write envelope to disk as both JSON and Markdown. Returns (json_path, md_path)."""
    md_path = json_path.with_suffix(".md")
    json_path.write_text(envelope.model_dump_json(indent=2), encoding="utf-8")
    md_path.write_text(ticket_to_markdown(envelope), encoding="utf-8")
    return json_path, md_path


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def save_ticket(envelope: TicketEnvelope) -> tuple[Path, Path]:
    """Save a new ticket to the folder matching its current status.

    Generates a timestamped filename. Returns (json_path, md_path).
    """
    ensure_ticket_dirs()

    folder = folder_for_status(envelope.ticket.status)
    target_dir = TICKETS_DIR / folder

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = slugify(envelope.ticket.title)
    base = f"{timestamp}-{slug}"

    json_path = target_dir / f"{base}.json"
    write_ticket_files(envelope, json_path)
    return json_path, json_path.with_suffix(".md")


def load_ticket(path: Path) -> TicketEnvelope:
    """Load and validate a TicketEnvelope from a JSON file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return TicketEnvelope.model_validate(data)


def overwrite_ticket(json_path: Path, envelope: TicketEnvelope) -> tuple[Path, Path]:
    """Overwrite an existing ticket in place without moving it."""
    return write_ticket_files(envelope, json_path)


def list_ticket_json_files(folder: Optional[str] = None) -> List[Path]:
    """Return all ticket JSON files, sorted newest-first.

    If folder is given, searches only that subfolder. Otherwise searches all subfolders.
    """
    ensure_ticket_dirs()

    if folder:
        return sorted((TICKETS_DIR / folder).glob("*.json"), reverse=True)

    files: List[Path] = []
    for child in TICKETS_DIR.iterdir():
        if child.is_dir():
            files.extend(child.glob("*.json"))
    return sorted(files, reverse=True)


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------


def update_ticket_status(json_path: Path, new_status: TicketStatus) -> Path:
    """Move a ticket to the folder matching new_status and update its status field.

    Returns the new JSON path.
    """
    envelope = load_ticket(json_path)
    envelope.ticket.status = new_status

    target_dir = TICKETS_DIR / folder_for_status(new_status)
    target_dir.mkdir(parents=True, exist_ok=True)
    new_json_path = target_dir / json_path.name

    if json_path.resolve() != new_json_path.resolve():
        _delete_old_files(json_path)

    write_ticket_files(envelope, new_json_path)
    return new_json_path


def add_review_record(json_path: Path, decision: ReviewDecision, note: str) -> Path:
    """Append a ReviewRecord to the ticket, update its status, and move it to the right folder.

    Returns the new JSON path.
    """
    envelope = load_ticket(json_path)

    envelope.ticket.review_history.append(ReviewRecord(
        decision=decision,
        note=note,
        timestamp=datetime.now().isoformat(timespec="seconds"),
    ))

    decision_to_status = {
        ReviewDecision.approve: TicketStatus.approved,
        ReviewDecision.approve_with_changes: TicketStatus.approved,
        ReviewDecision.needs_revision: TicketStatus.needs_revision,
        ReviewDecision.reject: TicketStatus.rejected,
        ReviewDecision.archive_only: TicketStatus.archived,
    }
    envelope.ticket.status = decision_to_status[decision]

    target_dir = TICKETS_DIR / folder_for_status(envelope.ticket.status)
    target_dir.mkdir(parents=True, exist_ok=True)
    new_json_path = target_dir / json_path.name

    if json_path.resolve() != new_json_path.resolve():
        _delete_old_files(json_path)

    write_ticket_files(envelope, new_json_path)
    return new_json_path


def record_revision(envelope: TicketEnvelope, revision_instruction: str) -> None:
    """Append a needs_revision ReviewRecord to envelope for the given instruction.

    Mutates envelope in place; caller is responsible for saving afterward.
    """
    envelope.ticket.review_history.append(ReviewRecord(
        decision=ReviewDecision.needs_revision,
        note=revision_instruction,
        timestamp=datetime.now().isoformat(timespec="seconds"),
    ))


# ---------------------------------------------------------------------------
# Handoff packets
# ---------------------------------------------------------------------------


def save_handoff_packet(envelope: TicketEnvelope, packet_md: str) -> Path:
    """Write a handoff packet Markdown file alongside the ticket's JSON file.

    The packet is named <ticket-base>-handoff.md. Returns the saved path.
    """
    ensure_ticket_dirs()

    folder = folder_for_status(envelope.ticket.status)
    target_dir = TICKETS_DIR / folder

    slug = slugify(envelope.ticket.title)
    existing = sorted(target_dir.glob(f"*{slug}*.json"), reverse=True)
    base = existing[0].stem if existing else f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{slug}"

    packet_path = target_dir / f"{base}-handoff.md"
    packet_path.write_text(packet_md, encoding="utf-8")
    return packet_path
