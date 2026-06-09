from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from schemas import (
    ReviewDecision,
    ReviewRecord,
    SpecialistOutput,
    TicketEnvelope,
    TicketStatus,
)


ROOT = Path(__file__).resolve().parents[1]

TICKETS_DIR = ROOT / "tickets"
OUTPUTS_DIR = ROOT / "outputs"


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
    """Create all ticket subfolders if they do not exist yet."""
    for folder in set(STATUS_TO_FOLDER.values()):
        (TICKETS_DIR / folder).mkdir(parents=True, exist_ok=True)


def ensure_output_dirs() -> None:
    """Create the root outputs folder if it does not exist yet."""
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)


def slugify(text: str, max_len: int = 60) -> str:
    """Convert a title to a URL/filename-safe slug.

    Allows:
    - lowercase ASCII letters
    - digits
    - CJK characters
    """
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", text)
    text = text.strip("-")
    return text[:max_len] or "ticket"


def folder_for_status(status: TicketStatus) -> str:
    """Return the ticket subfolder name for a given status."""
    return STATUS_TO_FOLDER.get(status, "open")


def timestamp_now() -> str:
    """Return a compact timestamp for filenames."""
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def iso_now() -> str:
    """Return an ISO timestamp for review records."""
    return datetime.now().isoformat(timespec="seconds")


def _delete_old_files(json_path: Path) -> None:
    """Delete a ticket's JSON and Markdown files from their current location."""
    md_path = json_path.with_suffix(".md")

    if md_path.exists():
        md_path.unlink()

    if json_path.exists():
        json_path.unlink()


def _bullets(items: list[str]) -> str:
    """Render a string list as Markdown bullets."""
    return "\n".join(f"- {item}" for item in items) if items else "- None"


def _safe_enum_value(value: object, default: str = "None") -> str:
    """Return .value for Enum-like objects, otherwise string fallback."""
    if value is None:
        return default

    return str(getattr(value, "value", value))


def _safe_attr(obj: object, name: str, default: object = None) -> object:
    """Read an attribute safely for forward/backward schema compatibility."""
    return getattr(obj, name, default)


# ---------------------------------------------------------------------------
# Ticket serialisation
# ---------------------------------------------------------------------------


def ticket_to_markdown(envelope: TicketEnvelope) -> str:
    """Render a TicketEnvelope as a human-readable Markdown document."""
    t = envelope.ticket

    specialist_type = _safe_attr(t, "specialist_type", None)
    domain_type = _safe_attr(t, "domain_type", None)

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

## Specialist Type
{_safe_enum_value(specialist_type)}

## Domain Type
{_safe_enum_value(domain_type)}

## Objective
{t.objective}

## Context
{t.context}

## Assumptions
{_bullets(t.assumptions)}

## Missing Information
{_bullets(t.missing_information)}

## Recommended Specialist
{t.recommended_specialist or "None"}

## Next Action
{t.next_action}

## Human Review Required
{t.human_review_required}

## Risks
{_bullets(t.risks)}

## Deliverable Format
{t.deliverable_format}

## Handoff Prompt
{t.handoff_prompt or "None"}

## Archive Notes
{t.archive_notes or "None"}

## Review Questions
{_bullets(envelope.review_questions)}

## Suggested User Reply
{envelope.suggested_user_reply or "None"}

## Review History
{review_history}
"""


def write_ticket_files(envelope: TicketEnvelope, json_path: Path) -> tuple[Path, Path]:
    """Write a ticket envelope to disk as both JSON and Markdown.

    Returns:
        (json_path, md_path)
    """
    json_path.parent.mkdir(parents=True, exist_ok=True)

    md_path = json_path.with_suffix(".md")

    json_path.write_text(
        envelope.model_dump_json(indent=2),
        encoding="utf-8",
    )

    md_path.write_text(
        ticket_to_markdown(envelope),
        encoding="utf-8",
    )

    return json_path, md_path


# ---------------------------------------------------------------------------
# Ticket CRUD
# ---------------------------------------------------------------------------


def save_ticket(envelope: TicketEnvelope) -> tuple[Path, Path]:
    """Save a new ticket to the folder matching its current status.

    Generates a timestamped filename.

    Returns:
        (json_path, md_path)
    """
    ensure_ticket_dirs()

    folder = folder_for_status(envelope.ticket.status)
    target_dir = TICKETS_DIR / folder

    slug = slugify(envelope.ticket.title)
    base = f"{timestamp_now()}-{slug}"

    json_path = target_dir / f"{base}.json"

    return write_ticket_files(envelope, json_path)


def load_ticket(path: Path) -> TicketEnvelope:
    """Load and validate a TicketEnvelope from a JSON file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return TicketEnvelope.model_validate(data)


def overwrite_ticket(json_path: Path, envelope: TicketEnvelope) -> tuple[Path, Path]:
    """Overwrite an existing ticket in place without moving it."""
    return write_ticket_files(envelope, json_path)


def list_ticket_json_files(folder: Optional[str] = None) -> List[Path]:
    """Return ticket JSON files, sorted newest-first.

    If folder is given, searches only that subfolder.
    Otherwise, searches all ticket subfolders.
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
# Ticket status transitions
# ---------------------------------------------------------------------------


def update_ticket_status(json_path: Path, new_status: TicketStatus) -> Path:
    """Move a ticket to the folder matching new_status and update its status.

    Returns:
        New JSON path.
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


def add_review_record(
    json_path: Path,
    decision: ReviewDecision,
    note: str,
) -> Path:
    """Append a ReviewRecord, update status, and move the ticket.

    Returns:
        New JSON path.
    """
    envelope = load_ticket(json_path)

    envelope.ticket.review_history.append(
        ReviewRecord(
            decision=decision,
            note=note,
            timestamp=iso_now(),
        )
    )

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
    """Append a needs_revision ReviewRecord for a revision instruction.

    Mutates envelope in place.
    Caller is responsible for saving afterward.
    """
    envelope.ticket.review_history.append(
        ReviewRecord(
            decision=ReviewDecision.needs_revision,
            note=revision_instruction,
            timestamp=iso_now(),
        )
    )


# ---------------------------------------------------------------------------
# Handoff packets
# ---------------------------------------------------------------------------


def save_handoff_packet(envelope: TicketEnvelope, packet_md: str) -> Path:
    """Write a handoff packet Markdown file alongside the ticket.

    The packet is named:

        <ticket-base>-handoff.md

    Returns:
        Saved handoff packet path.
    """
    ensure_ticket_dirs()

    folder = folder_for_status(envelope.ticket.status)
    target_dir = TICKETS_DIR / folder
    target_dir.mkdir(parents=True, exist_ok=True)

    slug = slugify(envelope.ticket.title)

    existing = sorted(
        target_dir.glob(f"*{slug}*.json"),
        reverse=True,
    )

    if existing:
        base = existing[0].stem
    else:
        base = f"{timestamp_now()}-{slug}"

    packet_path = target_dir / f"{base}-handoff.md"
    packet_path.write_text(packet_md, encoding="utf-8")

    return packet_path


# ---------------------------------------------------------------------------
# Specialist outputs
# ---------------------------------------------------------------------------


def specialist_output_to_markdown(output: SpecialistOutput) -> str:
    """Render a SpecialistOutput as Markdown."""
    domain_type = _safe_attr(output, "domain_type", None)
    suggested_followup_tickets = _safe_attr(output, "suggested_followup_tickets", [])

    return f"""# {output.title}

## Specialist
{_safe_enum_value(output.specialist_type)}

## Domain
{_safe_enum_value(domain_type)}

## Summary
{output.summary}

## Deliverable
{output.deliverable}

## Assumptions
{_bullets(output.assumptions)}

## Risks
{_bullets(output.risks)}

## Next Steps
{_bullets(output.next_steps)}

## Review Questions
{_bullets(output.review_questions)}

## Suggested Follow-up Tickets
{_bullets(suggested_followup_tickets)}
"""


def save_specialist_output(output: SpecialistOutput) -> Path:
    """Save a specialist output as Markdown and JSON.

    Files are stored under:

        outputs/<specialist_type>/

    Returns:
        Markdown output path.
    """
    ensure_output_dirs()

    specialist_name = _safe_enum_value(output.specialist_type, default="unknown")
    target_dir = OUTPUTS_DIR / specialist_name
    target_dir.mkdir(parents=True, exist_ok=True)

    slug = slugify(output.title)
    base = f"{timestamp_now()}-{slug}"

    md_path = target_dir / f"{base}.md"
    json_path = target_dir / f"{base}.json"

    md_path.write_text(
        specialist_output_to_markdown(output),
        encoding="utf-8",
    )

    json_path.write_text(
        output.model_dump_json(indent=2),
        encoding="utf-8",
    )

    return md_path


def list_specialist_output_files(
    specialist_type: Optional[str] = None,
) -> List[Path]:
    """List saved specialist Markdown outputs, newest-first.

    If specialist_type is given, searches only outputs/<specialist_type>/.
    Otherwise, searches all specialist output folders.
    """
    ensure_output_dirs()

    if specialist_type:
        return sorted((OUTPUTS_DIR / specialist_type).glob("*.md"), reverse=True)

    files: List[Path] = []

    for child in OUTPUTS_DIR.iterdir():
        if child.is_dir():
            files.extend(child.glob("*.md"))

    return sorted(files, reverse=True)


def load_specialist_output_json(path: Path) -> SpecialistOutput:
    """Load a SpecialistOutput from a JSON file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return SpecialistOutput.model_validate(data)