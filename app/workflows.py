"""Workflow orchestration layer (v0.9 — mode separation).

This module turns a messy request into artifacts by calling the existing
building blocks instead of duplicating their logic:

    create_ticket()              (mica)
    save_ticket()                (storage)
    generate_handoff_packet()    (mica)
    save_handoff_packet_record() (storage)
    run_specialist()             (specialists)
    save_specialist_output()     (storage)
    save_run_trace()             (storage)

Three modes control *where the run stops*, not what gets saved. Every mode
still saves artifacts and a trace:

    manual  → create + save ticket, then stop for the Review Desk.
    guided  → run through the specialist output, then stop for review.
    auto    → like guided, plus a suggested (not executed) follow-up batch.

Mode belongs to the run (RunTrace.mode), not the ticket: the same ticket may be
processed manually today and in guided mode another time.

The UI should call these functions instead of orchestrating steps itself.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from mica import (
    create_ticket,
    generate_handoff_packet,
)
from schemas import (
    Deliverable,
    FollowupTicketBatch,
    RunStep,
    RunStepStatus,
    RunTrace,
    SpecialistOutput,
    SpecialistType,
    TicketEnvelope,
    WorkflowMode,
)
from specialists import run_specialist
from schemas import TicketStatus
from storage import (
    deliverable_from_output,
    find_ticket_path_by_id,
    handoff_packet_to_markdown,
    save_deliverable,
    save_handoff_packet_record,
    save_run_trace,
    save_specialist_output,
    save_ticket,
    update_ticket_status,
)


# ---------------------------------------------------------------------------
# Safety policy
# ---------------------------------------------------------------------------

# Auto is the go-to mode, so specialists may run in any mode by default. Only
# specialists that can touch code or the outside world are gated to manual —
# and even those can be advanced explicitly via continue_run (an explicit click
# is the human consent the gate was protecting for).
_ALL_MODES = {WorkflowMode.manual, WorkflowMode.guided, WorkflowMode.auto}

# Specialists that should NOT advance automatically; listed for clarity.
ALLOWED_MODES: dict[SpecialistType, set[WorkflowMode]] = {
    SpecialistType.engineer: {WorkflowMode.manual},
    SpecialistType.operator: {WorkflowMode.manual},
}

# Default for any specialist not listed above: all modes (low risk).
_DEFAULT_ALLOWED_MODES = set(_ALL_MODES)


class ModeNotAllowedError(Exception):
    """Raised when a specialist is not permitted to run in the requested mode."""


def allowed_modes_for(specialist: SpecialistType) -> set[WorkflowMode]:
    """Return the set of modes a specialist is allowed to run in."""
    return ALLOWED_MODES.get(specialist, _DEFAULT_ALLOWED_MODES)


def is_mode_allowed(specialist: SpecialistType, mode: WorkflowMode) -> bool:
    """Whether a specialist may run in the given mode under current policy."""
    # Manual is always allowed: it only creates a ticket and then stops.
    if mode == WorkflowMode.manual:
        return True
    return mode in allowed_modes_for(specialist)


# ---------------------------------------------------------------------------
# Trace helpers
# ---------------------------------------------------------------------------


def _iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _add_step(
    trace: RunTrace,
    name: str,
    status: RunStepStatus,
    *,
    message: str = "",
    artifact_type: Optional[str] = None,
    artifact_id: Optional[str] = None,
    artifact_path: Optional[str] = None,
) -> RunStep:
    """Append a step to the trace and return it."""
    step = RunStep(
        name=name,
        status=status,
        message=message,
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        artifact_path=artifact_path,
        timestamp=_iso_now(),
    )
    trace.steps.append(step)
    return step


def _finish(
    trace: RunTrace,
    *,
    final_status: str,
    stop_reason: str = "",
) -> RunTrace:
    """Finalize a trace, persist it, and return it."""
    trace.final_status = final_status
    trace.stop_reason = stop_reason
    trace.finished_at = _iso_now()
    save_run_trace(trace)
    return trace


def _new_trace(
    mode: WorkflowMode,
    *,
    user_request: str,
    project_key: str,
    trace: Optional[RunTrace] = None,
) -> RunTrace:
    """Return the trace to use for a run.

    If a caller (e.g. the background run manager) supplies a trace, use it so the
    UI can observe steps live as they are appended. Otherwise create a fresh one.
    """
    if trace is not None:
        trace.mode = mode
        trace.request = user_request
        trace.project_key = project_key
        trace.started_at = _iso_now()
        return trace

    return RunTrace(
        mode=mode,
        request=user_request,
        project_key=project_key,
        started_at=_iso_now(),
    )


# ---------------------------------------------------------------------------
# Run result
# ---------------------------------------------------------------------------


class RunResult:
    """The outcome of a workflow run.

    Carries the trace plus any produced artifacts so the UI can render a final
    candidate, the trace, and (in auto mode) suggested follow-ups without
    reloading from disk.
    """

    def __init__(
        self,
        *,
        trace: RunTrace,
        ticket: Optional[TicketEnvelope] = None,
        output=None,
        followup_batch: Optional[FollowupTicketBatch] = None,
    ) -> None:
        self.trace = trace
        self.ticket = ticket
        self.output = output
        self.followup_batch = followup_batch


# ---------------------------------------------------------------------------
# Shared sub-steps
# ---------------------------------------------------------------------------


def _step_create_and_save_ticket(
    trace: RunTrace,
    *,
    user_request: str,
    project_key: str,
    api_key: str,
    model: str,
    extra_context: Optional[str],
) -> TicketEnvelope:
    """Create a ticket from the request and save it. Updates the trace."""
    _add_step(trace, "create_ticket", RunStepStatus.running)
    envelope = create_ticket(
        user_request=user_request,
        project_key=project_key,
        api_key=api_key,
        model=model,
        extra_context=extra_context,
    )

    ticket = envelope.ticket
    trace.ticket_id = ticket.ticket_id
    trace.root_ticket_id = ticket.root_ticket_id or ticket.ticket_id

    # Replace the running placeholder with a succeeded step.
    trace.steps[-1] = RunStep(
        name="create_ticket",
        status=RunStepStatus.succeeded,
        message=ticket.title,
        artifact_type="ticket",
        artifact_id=ticket.ticket_id,
        timestamp=_iso_now(),
    )

    json_path, _ = save_ticket(envelope)
    _add_step(
        trace,
        "save_ticket",
        RunStepStatus.succeeded,
        artifact_type="ticket",
        artifact_id=ticket.ticket_id,
        artifact_path=str(json_path),
    )

    return envelope


def _step_generate_and_save_handoff(
    trace: RunTrace,
    *,
    envelope: TicketEnvelope,
    api_key: str,
    model: str,
):
    """Generate a handoff packet from the ticket and save it. Updates trace."""
    _add_step(trace, "generate_handoff", RunStepStatus.running)
    packet = generate_handoff_packet(
        envelope=envelope,
        api_key=api_key,
        model=model,
    )
    trace.steps[-1] = RunStep(
        name="generate_handoff",
        status=RunStepStatus.succeeded,
        message=packet.title,
        artifact_type="handoff",
        artifact_id=packet.handoff_id,
        timestamp=_iso_now(),
    )

    json_path, _ = save_handoff_packet_record(packet)
    _add_step(
        trace,
        "save_handoff",
        RunStepStatus.succeeded,
        artifact_type="handoff",
        artifact_id=packet.handoff_id,
        artifact_path=str(json_path),
    )

    return packet


def _step_run_and_save_specialist(
    trace: RunTrace,
    *,
    packet,
    api_key: str,
    model: str,
):
    """Run the specialist on the handoff and save its output. Updates trace."""
    _add_step(trace, "run_specialist", RunStepStatus.running)
    output = run_specialist(
        specialist_type=packet.specialist_type,
        handoff_packet=handoff_packet_to_markdown(packet),
        api_key=api_key,
        model=model,
        source_ticket_id=packet.source_ticket_id,
        source_handoff_id=packet.handoff_id,
    )
    trace.output_id = output.output_id
    trace.steps[-1] = RunStep(
        name="run_specialist",
        status=RunStepStatus.succeeded,
        message=output.title,
        artifact_type="output",
        artifact_id=output.output_id,
        timestamp=_iso_now(),
    )

    md_path = save_specialist_output(output)
    _add_step(
        trace,
        "save_output",
        RunStepStatus.succeeded,
        artifact_type="output",
        artifact_id=output.output_id,
        artifact_path=str(md_path),
    )

    return output


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------


def run_manual(
    *,
    user_request: str,
    project_key: str,
    api_key: str,
    model: str,
    extra_context: Optional[str] = None,
    trace: Optional[RunTrace] = None,
) -> RunResult:
    """Manual mode: create + save the ticket, then stop for the Review Desk.

    Nothing is dispatched or executed automatically.
    """
    trace = _new_trace(
        WorkflowMode.manual,
        user_request=user_request,
        project_key=project_key,
        trace=trace,
    )

    try:
        envelope = _step_create_and_save_ticket(
            trace,
            user_request=user_request,
            project_key=project_key,
            api_key=api_key,
            model=model,
            extra_context=extra_context,
        )
    except Exception as exc:
        _add_step(trace, "create_ticket", RunStepStatus.failed, message=str(exc))
        _finish(trace, final_status="failed", stop_reason=str(exc))
        raise

    _add_step(
        trace,
        "await_review",
        RunStepStatus.waiting_for_review,
        message="Ticket drafted. Continue in the Review Desk.",
    )
    _finish(
        trace,
        final_status="stopped_for_review",
        stop_reason="Manual mode: review and approve the ticket in the Review Desk.",
    )

    return RunResult(trace=trace, ticket=envelope)


def run_guided(
    *,
    user_request: str,
    project_key: str,
    api_key: str,
    model: str,
    extra_context: Optional[str] = None,
    trace: Optional[RunTrace] = None,
) -> RunResult:
    """Guided mode: advance safe internal steps to a specialist output, then stop.

    Produces a ticket, handoff, and specialist output, but does not mark the
    ticket completed and does not generate follow-ups. Billy reviews the output.
    """
    trace = _new_trace(
        WorkflowMode.guided,
        user_request=user_request,
        project_key=project_key,
        trace=trace,
    )

    try:
        envelope = _step_create_and_save_ticket(
            trace,
            user_request=user_request,
            project_key=project_key,
            api_key=api_key,
            model=model,
            extra_context=extra_context,
        )

        _guard_mode(trace, envelope.ticket.specialist_type, WorkflowMode.guided)

        packet = _step_generate_and_save_handoff(
            trace, envelope=envelope, api_key=api_key, model=model
        )
        output = _step_run_and_save_specialist(
            trace, packet=packet, api_key=api_key, model=model
        )
    except ModeNotAllowedError as exc:
        _finish(trace, final_status="stopped_for_review", stop_reason=str(exc))
        return RunResult(trace=trace, ticket=_safe_envelope(locals()))
    except Exception as exc:
        _add_step(trace, "run", RunStepStatus.failed, message=str(exc))
        _finish(trace, final_status="failed", stop_reason=str(exc))
        raise

    _add_step(
        trace,
        "await_review",
        RunStepStatus.waiting_for_review,
        message="Specialist output ready. Review it before acceptance.",
    )
    _finish(
        trace,
        final_status="stopped_for_review",
        stop_reason="Guided mode: review the specialist output before acceptance.",
    )

    return RunResult(trace=trace, ticket=envelope, output=output)


def run_auto(
    *,
    user_request: str,
    project_key: str,
    api_key: str,
    model: str,
    extra_context: Optional[str] = None,
    max_depth: int = 1,
    trace: Optional[RunTrace] = None,
) -> RunResult:
    """Auto mode: run a safe depth-1 workflow and present the final candidate.

    Produces a ticket, handoff, and specialist output, then stops at the final
    candidate so Billy can accept it as a deliverable. Auto mode does NOT
    generate follow-up tickets by default — that only invites loops. Use the
    explicit "suggest follow-ups" action if you actually want next-step tickets.
    """
    trace = _new_trace(
        WorkflowMode.auto,
        user_request=user_request,
        project_key=project_key,
        trace=trace,
    )

    try:
        envelope = _step_create_and_save_ticket(
            trace,
            user_request=user_request,
            project_key=project_key,
            api_key=api_key,
            model=model,
            extra_context=extra_context,
        )

        _guard_mode(trace, envelope.ticket.specialist_type, WorkflowMode.auto)

        packet = _step_generate_and_save_handoff(
            trace, envelope=envelope, api_key=api_key, model=model
        )
        output = _step_run_and_save_specialist(
            trace, packet=packet, api_key=api_key, model=model
        )
    except ModeNotAllowedError as exc:
        _finish(trace, final_status="stopped_for_review", stop_reason=str(exc))
        return RunResult(trace=trace, ticket=_safe_envelope(locals()))
    except Exception as exc:
        _add_step(trace, "run", RunStepStatus.failed, message=str(exc))
        _finish(trace, final_status="failed", stop_reason=str(exc))
        raise

    _add_step(
        trace,
        "await_acceptance",
        RunStepStatus.waiting_for_review,
        message="Final candidate ready. Accept it to save the deliverable.",
    )
    _finish(
        trace,
        final_status="stopped_for_review",
        stop_reason="Auto mode: accept the final candidate to save the deliverable.",
    )

    return RunResult(
        trace=trace,
        ticket=envelope,
        output=output,
    )


# ---------------------------------------------------------------------------
# Continuing a stopped run (resume in place)
# ---------------------------------------------------------------------------


# Steps that merely mark a stopping point; dropped when a run is resumed so the
# trace reads as one continuous flow.
_STOP_STEP_NAMES = {"await_review", "await_acceptance", "policy_gate"}


def run_stage(result: RunResult) -> str:
    """Classify how far a run has progressed.

    Returns one of:
        "no_ticket"  — nothing created yet (shouldn't normally happen)
        "ticket"     — ticket exists, no specialist output yet
        "output"     — specialist output exists; ready to accept
    """
    if result.output is not None:
        return "output"
    if result.ticket is not None:
        return "ticket"
    return "no_ticket"


def can_continue(result: RunResult) -> bool:
    """Whether there is a further automatic step to run from here.

    A run can be continued when it has a ticket but no specialist output yet —
    i.e. it stopped at a ticket (manual mode) or at the policy gate.
    """
    return run_stage(result) == "ticket"


def _strip_trailing_stop_steps(trace: RunTrace) -> None:
    """Remove trailing stop-marker steps so a resumed trace flows continuously."""
    while trace.steps and trace.steps[-1].name in _STOP_STEP_NAMES:
        trace.steps.pop()


def continue_run(
    result: RunResult,
    *,
    api_key: str,
    model: str,
) -> RunResult:
    """Advance a stopped run to its specialist output, in place.

    This is the explicit "continue" action: the user has chosen to proceed past
    a stopping point (a manual-mode pause or a safety-policy gate), so the mode
    policy is intentionally NOT re-checked here — the click is the consent the
    policy was guarding for.

    Reuses the same step helpers, appending to the existing trace.
    """
    if not can_continue(result):
        return result

    trace = result.trace
    envelope = result.ticket

    _strip_trailing_stop_steps(trace)
    trace.final_status = "running"
    trace.stop_reason = ""

    try:
        packet = _step_generate_and_save_handoff(
            trace, envelope=envelope, api_key=api_key, model=model
        )
        output = _step_run_and_save_specialist(
            trace, packet=packet, api_key=api_key, model=model
        )
    except Exception as exc:
        _add_step(trace, "run", RunStepStatus.failed, message=str(exc))
        _finish(trace, final_status="failed", stop_reason=str(exc))
        return RunResult(trace=trace, ticket=envelope)

    _add_step(
        trace,
        "await_acceptance",
        RunStepStatus.waiting_for_review,
        message="Final candidate ready. Accept it to save the deliverable.",
    )
    _finish(
        trace,
        final_status="stopped_for_review",
        stop_reason="Accept the final candidate to save the deliverable.",
    )

    return RunResult(trace=trace, ticket=envelope, output=output)


# ---------------------------------------------------------------------------
# Accepting a final deliverable
# ---------------------------------------------------------------------------


class AcceptResult:
    """Outcome of accepting a specialist output as a final deliverable."""

    def __init__(
        self,
        *,
        deliverable: Deliverable,
        artifact_path: str,
        closed_ticket_id: Optional[str] = None,
    ) -> None:
        self.deliverable = deliverable
        self.artifact_path = artifact_path
        # The ticket that was moved to completed, if any.
        self.closed_ticket_id = closed_ticket_id


def accept_output_as_deliverable(
    *,
    output: SpecialistOutput,
    filename: Optional[str] = None,
    note: str = "",
    root_ticket_id: Optional[str] = None,
    close_ticket: bool = True,
) -> AcceptResult:
    """Materialize an accepted specialist output as a final deliverable file.

    Writes the output's deliverable content verbatim to deliverables/ using the
    resolved filename, plus a sidecar record. This is the "done" action: it turns
    a candidate into a real, usable file.

    When close_ticket is True and the output is linked to a source ticket, that
    ticket is moved to `completed` — the deliverable is the proof of completion.

    Returns:
        AcceptResult
    """
    deliverable = deliverable_from_output(
        output,
        filename=filename,
        note=note,
        root_ticket_id=root_ticket_id,
    )

    artifact_path, _ = save_deliverable(deliverable)

    closed_ticket_id: Optional[str] = None
    if close_ticket and output.source_ticket_id:
        ticket_path = find_ticket_path_by_id(output.source_ticket_id)
        if ticket_path is not None:
            update_ticket_status(ticket_path, TicketStatus.completed)
            closed_ticket_id = output.source_ticket_id

    return AcceptResult(
        deliverable=deliverable,
        artifact_path=str(artifact_path),
        closed_ticket_id=closed_ticket_id,
    )


# ---------------------------------------------------------------------------
# Mode guard
# ---------------------------------------------------------------------------


def _guard_mode(
    trace: RunTrace,
    specialist: SpecialistType,
    mode: WorkflowMode,
) -> None:
    """Stop the run early if the specialist may not run in this mode.

    The ticket is already created and saved, so Billy can still continue
    manually from the Review Desk.
    """
    if is_mode_allowed(specialist, mode):
        return

    allowed = ", ".join(sorted(m.value for m in allowed_modes_for(specialist)))
    reason = (
        f"Safety policy: {specialist.value} may not run in {mode.value} mode "
        f"(allowed: {allowed}). The ticket was saved — continue in the Review Desk."
    )
    _add_step(
        trace,
        "policy_gate",
        RunStepStatus.skipped,
        message=reason,
    )
    raise ModeNotAllowedError(reason)


def _safe_envelope(local_vars: dict) -> Optional[TicketEnvelope]:
    """Return the envelope from a function's locals if it exists."""
    env = local_vars.get("envelope")
    return env if isinstance(env, TicketEnvelope) else None
