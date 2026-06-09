from __future__ import annotations

from pathlib import Path
from typing import Optional

from openai import OpenAI
from prompts import (
    MICA_SYSTEM_PROMPT,
    TICKET_REVISION_PROMPT,
    HANDOFF_PACKET_PROMPT,
)
from schemas import TicketEnvelope, HandoffPacket


ROOT = Path(__file__).resolve().parents[1]


def read_text_file(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def load_memory(project_key: str) -> str:
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


def create_ticket(
    *,
    user_request: str,
    project_key: str,
    api_key: str,
    model: str,
    extra_context: Optional[str] = None,
) -> TicketEnvelope:
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

    # Uses OpenAI Python SDK structured parsing with a Pydantic model.
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

    return parsed


def revise_ticket(
    *,
    envelope: TicketEnvelope,
    revision_instruction: str,
    api_key: str,
    model: str,
) -> TicketEnvelope:
    client = OpenAI(api_key=api_key)

    user_content = f"""
Existing ticket:
{envelope.model_dump_json(indent=2)}

Billy's revision instruction:
{revision_instruction}

Revise the ticket. Do not execute the task.
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

    return parsed


def generate_handoff_packet(
    *,
    envelope: TicketEnvelope,
    api_key: str,
    model: str,
) -> HandoffPacket:
    client = OpenAI(api_key=api_key)

    user_content = f"""
Approved ticket:
{envelope.model_dump_json(indent=2)}

Create a specialist handoff packet.
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

    return parsed

    