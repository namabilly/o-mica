from __future__ import annotations

import time

import streamlit as st

from mica import create_followup_ticket_batch_from_output
from run_manager import get_run, start_continue, start_run
from schemas import SpecialistType, WorkflowMode
from storage import save_followup_ticket_batch, save_specialist_output
from ui.common import (
    render_accept_deliverable,
    render_followup_batch,
    render_run_steps_compact,
    render_run_trace_interactive,
    render_specialist_output,
    render_ticket_summary,
)
from ui.graph_trace import render_graph_trace
from workflows import (
    allowed_modes_for,
    can_continue,
)


# How often the Run tab re-polls a background run, in seconds.
_POLL_INTERVAL = 1.0

# Cap consecutive auto-refreshes so the rerun loop can never run away; after this
# many polls (~minutes), fall back to a manual refresh button.
_MAX_AUTO_POLLS = 600


MODE_LABELS = {
    "Manual / 手动": WorkflowMode.manual,
    "Guided / 半自动": WorkflowMode.guided,
    "Auto / 自动": WorkflowMode.auto,
}

MODE_HELP = {
    WorkflowMode.manual: "Create the ticket, then stop. Continue here when ready.",
    WorkflowMode.guided: "Advance to a specialist output, then stop for review.",
    WorkflowMode.auto: "Run to the final candidate, then stop for acceptance.",
}


def render_run_tab(
    *,
    project_key: str,
    model: str,
    implemented_specialists: list[SpecialistType],
) -> None:
    st.subheader("Run / 执行")

    st.info(
        "The simplified main interface. Enter a request, choose a mode, and let "
        "Mica advance the workflow. The other tabs remain for manual control."
    )

    request = st.text_area(
        "Request",
        height=140,
        placeholder="Describe what you need. Messy is fine.",
        key="run_request",
    )

    extra_context = st.text_area(
        "Project context (optional)",
        height=90,
        placeholder="Anything Mica should know about this specific task.",
        key="run_extra_context",
    )

    c1, c2 = st.columns(2)

    with c1:
        mode_label = st.radio(
            "Mode",
            options=list(MODE_LABELS.keys()),
            index=1,  # Guided is the sensible default.
            key="run_mode",
        )
        mode = MODE_LABELS[mode_label]
        st.caption(MODE_HELP[mode])

    with c2:
        specialist_hint = st.selectbox(
            "Specialist",
            options=["Auto"] + [s.value for s in implemented_specialists],
            index=0,
            key="run_specialist_hint",
            help="Auto lets Mica route the ticket. Otherwise, nudge it toward one specialist.",
        )

    # Surface the safety policy for the chosen specialist hint.
    if specialist_hint != "Auto" and mode != WorkflowMode.manual:
        specialist = SpecialistType(specialist_hint)
        allowed = allowed_modes_for(specialist)
        if mode not in allowed:
            allowed_str = ", ".join(sorted(m.value for m in allowed))
            st.warning(
                f"Policy: `{specialist.value}` won't auto-run in `{mode.value}` mode "
                f"(allowed: {allowed_str}). The ticket will be created and the run "
                "will pause — you can then click **Continue** to finish here."
            )

    active_handle = get_run(st.session_state.get("active_run_id"))
    run_in_progress = active_handle is not None and active_handle.is_running

    # While a run is in progress, no stale result/batch from a prior run should
    # linger. Clear defensively here so it holds regardless of how the run began.
    if run_in_progress:
        st.session_state.last_run_result = None
        st.session_state.last_followup_batch = None

    if st.button(
        "Run",
        type="primary",
        use_container_width=True,
        disabled=run_in_progress,
    ):
        if not request.strip():
            st.warning("Please enter a request first.")
        else:
            resolved_context = _build_context(extra_context, specialist_hint)
            run_id = start_run(
                mode=mode,
                user_request=request,
                project_key=project_key,
                api_key=st.secrets["OPENAI_API_KEY"],
                model=model,
                extra_context=resolved_context,
            )
            st.session_state.active_run_id = run_id
            st.session_state.active_run_polls = 0
            # A new run supersedes any previous result and follow-up batch.
            st.session_state.last_run_result = None
            st.session_state.last_followup_batch = None
            st.rerun()

    # Surface a background run: live trace while running, promote on completion.
    _render_active_run(model=model)

    result = st.session_state.get("last_run_result")

    if result is not None:
        _render_result(result, model=model)


def _render_active_run(*, model: str) -> None:
    """Render the in-flight background run, if any, and auto-refresh until done.

    Promotes a finished run's result into last_run_result so the rest of the tab
    renders it normally.
    """
    handle = get_run(st.session_state.get("active_run_id"))
    if handle is None:
        return

    if handle.is_running:
        st.divider()
        st.markdown("### Run in progress")
        st.caption(
            "This keeps running in the background. You can switch views and come "
            "back — it won't stop."
        )
        with st.status("Working…", expanded=True):
            render_run_steps_compact(handle.trace)

        # Auto-refresh to pick up new steps, but bound it so the rerun loop can
        # never run away. After the ceiling, fall back to a manual refresh.
        polls = st.session_state.get("active_run_polls", 0)
        if polls < _MAX_AUTO_POLLS:
            st.session_state.active_run_polls = polls + 1
            time.sleep(_POLL_INTERVAL)
            st.rerun()
        else:
            st.caption("Still running. Refresh to check for updates.")
            if st.button("Refresh now", key="run_refresh"):
                st.session_state.active_run_polls = 0
                st.rerun()
        return

    # Finished: promote result or surface error, then forget the active id.
    if handle.status == "error":
        st.error(f"Run failed: {handle.error}")
    elif handle.result is not None:
        st.session_state.last_run_result = handle.result

    st.session_state.active_run_id = None
    st.session_state.active_run_polls = 0


def _build_context(extra_context: str, specialist_hint: str) -> str:
    """Combine user context with an optional specialist routing hint."""
    parts = []
    if extra_context.strip():
        parts.append(extra_context.strip())
    if specialist_hint != "Auto":
        parts.append(
            f"Routing hint: prefer specialist_type = {specialist_hint} if appropriate."
        )
    return "\n\n".join(parts) if parts else None


def _render_result(result, *, model: str) -> None:
    st.divider()

    # --- Final Candidate ---------------------------------------------------
    st.markdown("## Final Candidate")

    if result.output is not None:
        render_specialist_output(result.output, key_prefix="run_tab_")

        # The primary "done" action: turn the candidate into a real file.
        st.divider()
        render_accept_deliverable(result.output, key_prefix="run_tab_")

        with st.expander("Also save raw specialist output (intermediate)", expanded=False):
            if st.button(
                "Save specialist output",
                use_container_width=True,
                key="run_save_raw_output",
            ):
                path = save_specialist_output(result.output)
                st.success(f"Saved to: `{path}`")
    elif result.ticket is not None:
        render_ticket_summary(result.ticket, show_status=True)

        if can_continue(result):
            st.info(result.trace.stop_reason or "The run paused at the ticket.")
            st.caption(
                "Continue to generate the handoff and run the specialist, without "
                "leaving this tab."
            )
            if st.button(
                "Continue ▶",
                type="primary",
                use_container_width=True,
                key="run_continue",
            ):
                run_id = start_continue(
                    result=result,
                    api_key=st.secrets["OPENAI_API_KEY"],
                    model=model,
                )
                st.session_state.active_run_id = run_id
                st.session_state.active_run_polls = 0
                st.rerun()
    else:
        st.info("No candidate was produced. See the trace for what happened.")

    # --- Optional follow-ups (on demand only) ------------------------------
    if result.output is not None:
        _render_optional_followups(result, model=model)

    # --- Trace / Artifacts -------------------------------------------------
    st.divider()

    trace_view = st.radio(
        "Trace view",
        options=["Steps", "Graph"],
        index=0,
        horizontal=True,
        key="run_trace_view",
    )

    if trace_view == "Graph":
        root_id = result.trace.root_ticket_id or result.trace.ticket_id
        if root_id:
            render_graph_trace(root_id, key="run_graph")
        else:
            st.caption("No ticket yet — nothing to graph.")
    else:
        render_run_trace_interactive(result.trace, expanded=True)


def _render_optional_followups(result, *, model: str) -> None:
    """Generate follow-up tickets only when Billy explicitly asks.

    Follow-ups are opt-in to avoid endless loops of generated tickets.
    """
    st.divider()
    with st.expander("Need follow-up tickets? (optional)", expanded=False):
        st.caption(
            "Most 'produce X' tasks are done once you accept the deliverable. "
            "Generate follow-up tickets only if there is genuinely separate next work."
        )

        instruction = st.text_input(
            "What follow-up work, if any?",
            value="",
            placeholder="e.g. Add a CONTRIBUTING.md and a quickstart section.",
            key="run_followup_instruction",
        )

        if st.button("Suggest follow-up tickets", key="run_suggest_followups"):
            try:
                with st.spinner("Generating follow-up tickets..."):
                    batch = create_followup_ticket_batch_from_output(
                        output=result.output,
                        followup_instruction=instruction
                        or "Propose only genuinely separate next-step tickets.",
                        api_key=st.secrets["OPENAI_API_KEY"],
                        model=model,
                        parent_ticket_id=result.trace.ticket_id,
                        root_ticket_id=result.trace.root_ticket_id,
                    )
                st.session_state.last_followup_batch = batch
            except Exception as e:
                st.error("Failed to generate follow-up tickets.")
                st.exception(e)

        batch = st.session_state.get("last_followup_batch")
        if batch is not None and batch.tickets:
            selected = render_followup_batch(batch)

            if st.button(
                "Save selected follow-up tickets",
                use_container_width=True,
                key="run_save_followups",
            ):
                paths = save_followup_ticket_batch(
                    batch,
                    selected_indices=selected,
                )
                st.success(f"Saved {len(paths)} follow-up ticket(s).")
