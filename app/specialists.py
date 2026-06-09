from __future__ import annotations

from pathlib import Path

from openai import OpenAI

from schemas import SpecialistOutput, SpecialistType


ROOT = Path(__file__).resolve().parents[1]


SPECIALIST_PROMPT_FILES = {
    SpecialistType.planner: ROOT / "specialists" / "prompts" / "planner.md",
}


def read_prompt(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Missing specialist prompt: {path}")
    return path.read_text(encoding="utf-8")


def run_specialist(
    *,
    specialist_type: SpecialistType,
    handoff_packet: str,
    api_key: str,
    model: str,
    extra_instruction: str = "",
) -> SpecialistOutput:
    client = OpenAI(api_key=api_key)

    prompt_path = SPECIALIST_PROMPT_FILES.get(specialist_type)
    if prompt_path is None:
        raise ValueError(f"Specialist not implemented yet: {specialist_type}")

    system_prompt = read_prompt(prompt_path)

    user_content = f"""
Approved handoff packet:
{handoff_packet}

Billy's extra instruction:
{extra_instruction or "None"}

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

    return parsed