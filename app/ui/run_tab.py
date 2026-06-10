from __future__ import annotations

import streamlit as st

from mica import create_followup_ticket_batch_from_output
from schemas import SpecialistType, WorkflowMode
from storage import save_followup_ticket_batch, save_specialist_output
from ui.common import (
    render_accept_deliverable,
    render_followup_batch,
    render_run_trace,
    render_specialist_output,
    render_ticket_summary,
)
from workflows import (
    allowed_modes_for,
    run_auto,
    run_guided,
    run_manual,
)


MODE_LABELS = {
    "Manual / 手动": WorkflowMode.manual,
    "Guided / 半自动": WorkflowMode.guided,
    "Auto / 自动": WorkflowMode.auto,
}

MODE_HELP = {
    WorkflowMode.manual: "Create the ticket, then stop. Continue in the Review Desk.",
    WorkflowMode.guided: "Advance to a specialist output, then stop for review.",
    WorkflowMode.auto: "Run depth-1 and present the final candidate plus suggested follow-ups.",
}

# Dispatchers per mode.
_RUNNERS = {
    WorkflowMode.manual: run_manual,
    WorkflowMode.guided: run_guided,
    WorkflowMode.auto: run_auto,
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
                f"Policy: `{specialist.value}` may not run in `{mode.value}` mode "
                f"(allowed: {allowed_str}). The ticket will still be created, then "
                "the run will stop for the Review Desk."
            )

    if st.button("Run", type="primary", use_container_width=True):
        if not request.strip():
            st.warning("Please enter a request first.")
        else:
            runner = _RUNNERS[mode]
            resolved_context = _build_context(extra_context, specialist_hint)

            try:
                with st.spinner(f"Running in {mode.value} mode..."):
                    result = runner(
                        user_request=request,
                        project_key=project_key,
                        api_key=st.secrets["OPENAI_API_KEY"],
                        model=model,
                        extra_context=resolved_context,
                    )
                st.session_state.last_run_result = result

                if result.trace.final_status == "failed":
                    st.error("Run failed. See the trace below.")
                else:
                    st.success(f"Run finished: {result.trace.final_status}.")
            except Exception as e:
                st.error("Run failed.")
                st.exception(e)

    result = st.session_state.get("last_run_result")

    if result is not None:
        _render_result(result, model=model)


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
        st.caption(
            "Manual mode produced a ticket only. Continue in the Review Desk."
        )
        render_ticket_summary(result.ticket, show_status=True)
    else:
        st.info("No candidate was produced. See the trace for what happened.")

    # --- Optional follow-ups (on demand only) ------------------------------
    if result.output is not None:
        _render_optional_followups(result, model=model)

    # --- Trace / Artifacts -------------------------------------------------
    st.divider()
    render_run_trace(result.trace, expanded=True)


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
