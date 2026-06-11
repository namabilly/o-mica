"""Run-related view helpers for the web app.

Bridges run_manager's RunHandle / RunTrace to template-friendly structures, and
provides the SSE event stream for live trace updates.
"""

from __future__ import annotations

import asyncio
import json
from typing import Optional

from run_manager import get_run

_STEP_ICON = {
    "succeeded": "✅",
    "failed": "❌",
    "running": "⏳",
    "pending": "⬜",
    "skipped": "⏭️",
    "waiting_for_review": "🟡",
}

# Friendlier step names for display.
_STEP_NAME = {
    "create_ticket": "create ticket",
    "save_ticket": "save ticket",
    "generate_handoff": "generate handoff",
    "save_handoff": "save handoff",
    "run_specialist": "run specialist",
    "save_output": "save output",
    "await_review": "await review",
    "await_acceptance": "await acceptance",
    "policy_gate": "policy gate",
    "suggest_followups": "suggest follow-ups",
}


def _enum_val(v) -> str:
    return str(getattr(v, "value", v))


def steps_view(trace) -> list[dict]:
    """Convert a RunTrace's steps to template dicts (icon, name, message)."""
    out = []
    for s in trace.steps:
        status = _enum_val(s.status)
        out.append(
            {
                "name": _STEP_NAME.get(s.name, s.name.replace("_", " ")),
                "status": status,
                "icon": _STEP_ICON.get(status, "•"),
                "message": s.message or "",
            }
        )
    return out


def trace_signature(trace) -> str:
    """A cheap change-detector: number of steps + last step status."""
    if not trace.steps:
        return "0"
    return f"{len(trace.steps)}:{_enum_val(trace.steps[-1].status)}"


async def sse_trace(run_id: str, render_steps):
    """Yield SSE events for a run until it finishes.

    render_steps(steps_view) -> html string (injected by the server so this
    module stays template-agnostic).
    """
    last_sig = None
    # Safety cap so a hung run can't stream forever (~10 min at 1s).
    for _ in range(600):
        handle = get_run(run_id)
        if handle is None:
            yield {"event": "failed", "data": "run not found"}
            return

        sig = trace_signature(handle.trace)
        if sig != last_sig:
            last_sig = sig
            html = render_steps(steps_view(handle.trace))
            # SSE data can't contain raw newlines; encode as JSON then unwrap client-side?
            # Simpler: send as a single line by escaping newlines.
            yield {"event": "trace", "data": html.replace("\n", " ")}

        if not handle.is_running:
            if handle.status == "error":
                yield {"event": "failed", "data": (handle.error or "unknown error")[:300]}
            else:
                yield {"event": "done", "data": "ok"}
            return

        await asyncio.sleep(1.0)

    yield {"event": "done", "data": "ok"}
