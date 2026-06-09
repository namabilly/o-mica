from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from schemas import TicketEnvelope


ROOT = Path(__file__).resolve().parents[1]
TICKETS_OPEN_DIR = ROOT / "tickets" / "open"


def slugify(text: str, max_len: int = 60) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", text)
    text = text.strip("-")
    return text[:max_len] or "ticket"


def ticket_to_markdown(envelope: TicketEnvelope) -> str:
    t = envelope.ticket

    def bullets(items: list[str]) -> str:
        if not items:
            return "- None"
        return "\n".join(f"- {item}" for item in items)

    return f"""# {t.title}

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
"""


def save_ticket(envelope: TicketEnvelope) -> tuple[Path, Path]:
    TICKETS_OPEN_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = slugify(envelope.ticket.title)
    base = f"{timestamp}-{slug}"

    json_path = TICKETS_OPEN_DIR / f"{base}.json"
    md_path = TICKETS_OPEN_DIR / f"{base}.md"

    json_path.write_text(
        envelope.model_dump_json(indent=2),
        encoding="utf-8",
    )
    md_path.write_text(
        ticket_to_markdown(envelope),
        encoding="utf-8",
    )

    return json_path, md_path