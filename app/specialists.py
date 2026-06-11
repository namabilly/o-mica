from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from openai import OpenAI

from schemas import SpecialistOutput, SpecialistType, now_iso


ROOT = Path(__file__).resolve().parents[1]


SPECIALIST_PROMPT_FILES = {
    SpecialistType.planner: ROOT / "specialists" / "prompts" / "planner.md",
    SpecialistType.researcher: ROOT / "specialists" / "prompts" / "researcher.md",
    SpecialistType.analyst: ROOT / "specialists" / "prompts" / "analyst.md",
    SpecialistType.writer: ROOT / "specialists" / "prompts" / "writer.md",
    SpecialistType.engineer: ROOT / "specialists" / "prompts" / "engineer.md",
    SpecialistType.reviewer: ROOT / "specialists" / "prompts" / "reviewer.md",
    SpecialistType.operator: ROOT / "specialists" / "prompts" / "operator.md",
    SpecialistType.archivist: ROOT / "specialists" / "prompts" / "archivist.md",
}


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------


def read_prompt(path: Path) -> str:
    """Read a specialist system prompt."""
    if not path.exists():
        raise FileNotFoundError(f"Missing specialist prompt: {path}")

    return path.read_text(encoding="utf-8")


def get_prompt_path(specialist_type: SpecialistType) -> Path:
    """Return the prompt path for an implemented specialist."""
    prompt_path = SPECIALIST_PROMPT_FILES.get(specialist_type)

    if prompt_path is None:
        raise ValueError(f"Specialist not implemented yet: {specialist_type}")

    if not prompt_path.exists():
        raise FileNotFoundError(
            f"Specialist prompt file does not exist: {prompt_path}"
        )

    return prompt_path


# ---------------------------------------------------------------------------
# Handoff parsing helpers
# ---------------------------------------------------------------------------


def extract_markdown_field(markdown_text: str, heading: str) -> Optional[str]:
    """Extract text under a Markdown level-2 heading.

    Example heading:
        Source Ticket ID

    Looks for:
        ## Source Ticket ID
        ticket_xxx

    Stops at the next '## ' heading.
    """
    pattern = rf"##\s+{re.escape(heading)}\s*\n(.*?)(?=\n##\s+|\Z)"
    match = re.search(pattern, markdown_text, flags=re.DOTALL | re.IGNORECASE)

    if not match:
        return None

    value = match.group(1).strip()

    if not value or value.lower() == "none":
        return None

    # Remove simple Markdown code ticks if present.
    value = value.strip("`").strip()

    return value or None


def extract_source_ticket_id(handoff_packet: str) -> Optional[str]:
    """Extract Source Ticket ID from handoff Markdown if present."""
    return extract_markdown_field(handoff_packet, "Source Ticket ID")


def extract_handoff_id(handoff_packet: str) -> Optional[str]:
    """Extract Handoff ID from handoff Markdown if present."""
    return extract_markdown_field(handoff_packet, "Handoff ID")


# ---------------------------------------------------------------------------
# Specialist execution
# ---------------------------------------------------------------------------


def run_specialist(
    *,
    specialist_type: SpecialistType,
    handoff_packet: str,
    api_key: str,
    model: str,
    extra_instruction: str = "",
    source_ticket_id: Optional[str] = None,
    source_handoff_id: Optional[str] = None,
) -> SpecialistOutput:
    """Run a specialist on an approved handoff packet.

    The UI currently passes the handoff packet as Markdown text. To preserve
    lineage, this function accepts explicit source IDs and also tries to extract
    them from the Markdown packet.
    """
    client = OpenAI(api_key=api_key)

    prompt_path = get_prompt_path(specialist_type)
    system_prompt = read_prompt(prompt_path)

    resolved_source_ticket_id = source_ticket_id or extract_source_ticket_id(
        handoff_packet
    )
    resolved_source_handoff_id = source_handoff_id or extract_handoff_id(
        handoff_packet
    )

    user_content = f"""
Approved handoff packet:
{handoff_packet}

Billy's extra instruction:
{extra_instruction or "None"}

Source ticket ID:
{resolved_source_ticket_id or "None"}

Source handoff ID:
{resolved_source_handoff_id or "None"}

Create the specialist deliverable.
"""

    completion = client.beta.chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        response_format=SpecialistOutput,
    )

    parsed = completion.choices[0].message.parsed

    if parsed is None:
        raise RuntimeError("Model returned no specialist output.")

    # Enforce identity/routing metadata in code.
    parsed.specialist_type = specialist_type
    parsed.source_ticket_id = resolved_source_ticket_id
    parsed.source_handoff_id = resolved_source_handoff_id
    parsed.created_at = now_iso()

    return parsed