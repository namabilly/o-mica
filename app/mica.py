from __future__ import annotations

from pathlib import Path
from typing import Optional

from openai import OpenAI

from prompts import (
    FOLLOWUP_TICKET_BATCH_PROMPT,
    HANDOFF_PACKET_PROMPT,
    MICA_SYSTEM_PROMPT,
    TICKET_REVISION_PROMPT,
)
from schemas import (
    FollowupTicketBatch,
    HandoffPacket,
    SpecialistOutput,
    TicketEnvelope,
    TicketStatus,
)


ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Memory helpers
# ---------------------------------------------------------------------------


def read_text_file(path: Path) -> str:
    """Read a UTF-8 text file. Return empty string if missing."""
    if not path.exists():
        return ""

    return path.read_text(encoding="utf-8")


def load_memory(project_key: str) -> str:
    """Load common memory plus project-specific memory."""
    common_files = [
        ROOT / "memory" / "user_profile.md",
        ROOT / "memory" / "active_projects.md",
        ROOT / "memory" / "routing_rules.md",
    ]

    project_files = []

    if project_key == "jiuzhou":
        project_files = [
            ROOT / "projects" / "jiuzhou" / "project_brief.md",
            ROOT / "projects" / "jiuzhou" / "design_memory.md",
            ROOT / "projects" / "jiuzhou" / "architecture.md",
        ]
    elif project_key == "research":
        project_files = [
            ROOT / "projects" / "research" / "research_profile.md",
        ]

    chunks = []

    for file in common_files + project_files:
        content = read_text_file(file)

        if content.strip():
            chunks.append(f"\n\n--- FILE: {file.relative_to(ROOT)} ---\n{content}")

    return "\n".join(chunks)


# ---------------------------------------------------------------------------
# Ticket creation
# ---------------------------------------------------------------------------


def create_ticket(
    *,
    user_request: str,
    project_key: str,
    api_key: str,
    model: str,
    extra_context: Optional[str] = None,
) -> TicketEnvelope:
    """Create a structured ticket from a messy request."""
    client = OpenAI(api_key=api_key)

    memory = load_memory(project_key)

    user_content = f"""
Billy's request:
{user_request}

Selected project:
{project_key}

Relevant memory:
{memory}

Extra context from UI:
{extra_context or "None"}

Create a structured ticket. Do not execute the task.
"""

    completion = client.beta.chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": MICA_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format=TicketEnvelope,
    )

    parsed = completion.choices[0].message.parsed

    if parsed is None:
        raise RuntimeError("Model returned no parsed ticket.")

    # Root tickets should point to themselves as their root.
    if parsed.ticket.root_ticket_id is None:
        parsed.ticket.root_ticket_id = parsed.ticket.ticket_id

    parsed.ticket.parent_ticket_id = None
    parsed.ticket.source_output_id = None
    parsed.ticket.status = TicketStatus.drafted

    return parsed


# ---------------------------------------------------------------------------
# Ticket revision
# ---------------------------------------------------------------------------


def revise_ticket(
    *,
    envelope: TicketEnvelope,
    revision_instruction: str,
    api_key: str,
    model: str,
) -> TicketEnvelope:
    """Revise an existing ticket without changing its identity or lineage."""
    client = OpenAI(api_key=api_key)

    original_ticket = envelope.ticket

    user_content = f"""
Existing ticket:
{envelope.model_dump_json(indent=2)}

Billy's revision instruction:
{revision_instruction}

Revise the ticket. Do not execute the task.

Important:
- Preserve the existing ticket identity and task lineage.
- Do not create a new ticket.
"""

    completion = client.beta.chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": TICKET_REVISION_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format=TicketEnvelope,
    )

    parsed = completion.choices[0].message.parsed

    if parsed is None:
        raise RuntimeError("Model returned no revised ticket.")

    # Enforce identity and lineage in code.
    parsed.ticket.ticket_id = original_ticket.ticket_id
    parsed.ticket.parent_ticket_id = original_ticket.parent_ticket_id
    parsed.ticket.root_ticket_id = original_ticket.root_ticket_id
    parsed.ticket.source_output_id = original_ticket.source_output_id
    parsed.ticket.child_ticket_ids = original_ticket.child_ticket_ids
    parsed.ticket.review_history = original_ticket.review_history

    return parsed


# ---------------------------------------------------------------------------
# Handoff generation
# ---------------------------------------------------------------------------


def generate_handoff_packet(
    *,
    envelope: TicketEnvelope,
    api_key: str,
    model: str,
) -> HandoffPacket:
    """Generate a specialist handoff packet from a ticket."""
    client = OpenAI(api_key=api_key)

    user_content = f"""
Approved ticket:
{envelope.model_dump_json(indent=2)}

Create a specialist handoff packet.

Important:
- Use the ticket's specialist_type and domain_type when possible.
- Include source ticket linkage.
- Do not expand the task beyond the ticket.
"""

    completion = client.beta.chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": HANDOFF_PACKET_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format=HandoffPacket,
    )

    parsed = completion.choices[0].message.parsed

    if parsed is None:
        raise RuntimeError("Model returned no handoff packet.")

    # Enforce source linkage in code.
    parsed.source_ticket_id = envelope.ticket.ticket_id
    parsed.source_ticket_title = envelope.ticket.title
    parsed.specialist_type = envelope.ticket.specialist_type
    parsed.domain_type = envelope.ticket.domain_type

    return parsed


# ---------------------------------------------------------------------------
# Follow-up ticket batch generation
# ---------------------------------------------------------------------------


def create_followup_ticket_batch_from_output(
    *,
    output: SpecialistOutput,
    followup_instruction: str,
    api_key: str,
    model: str,
    parent_ticket_id: Optional[str] = None,
    root_ticket_id: Optional[str] = None,
) -> FollowupTicketBatch:
    """Create 1-N proposed follow-up tickets from a specialist output.

    The returned batch should be previewed by Billy before saving.
    """
    client = OpenAI(api_key=api_key)

    resolved_parent_ticket_id = parent_ticket_id or output.source_ticket_id
    resolved_root_ticket_id = root_ticket_id or resolved_parent_ticket_id

    user_content = f"""
Specialist output:
{output.model_dump_json(indent=2)}

Billy's follow-up instruction:
{followup_instruction}

Resolved parent ticket ID:
{resolved_parent_ticket_id or "None"}

Resolved root ticket ID:
{resolved_root_ticket_id or "None"}

Create a small batch of follow-up tickets.
"""

    completion = client.beta.chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": FOLLOWUP_TICKET_BATCH_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format=FollowupTicketBatch,
    )

    parsed = completion.choices[0].message.parsed

    if parsed is None:
        raise RuntimeError("Model returned no follow-up ticket batch.")

    # Enforce batch lineage in code.
    parsed.source_output_id = output.output_id
    parsed.parent_ticket_id = resolved_parent_ticket_id
    parsed.root_ticket_id = resolved_root_ticket_id

    # Enforce lineage on each proposed child ticket.
    for envelope in parsed.tickets:
        envelope.ticket.parent_ticket_id = parsed.parent_ticket_id
        envelope.ticket.root_ticket_id = parsed.root_ticket_id
        envelope.ticket.source_output_id = output.output_id
        envelope.ticket.status = TicketStatus.drafted
        envelope.ticket.child_ticket_ids = []

    return parsed