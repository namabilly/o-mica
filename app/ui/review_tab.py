from __future__ import annotations

import streamlit as st

from mica import revise_ticket
from schemas import ReviewDecision, TicketStatus
from storage import (
    add_review_record,
    overwrite_ticket,
    record_revision,
    update_ticket_status,
)
from ui.common import (
    render_dashboard,
    render_ticket_details,
    render_ticket_summary,
    select_ticket_ui,
)


def render_review_tab(*, model: str, folders: list[str]) -> None:
    render_dashboard(folders)

    st.divider()
    st.subheader("Review a ticket")

    selected_path, envelope = select_ticket_ui(prefix="review", folders=folders)

    if envelope is None or selected_path is None:
        return

    ticket = envelope.ticket

    st.divider()
    render_ticket_summary(envelope, show_status=True)
    render_ticket_details(envelope)

    st.divider()
    st.markdown("### Review Decision")

    decision = st.radio(
        "Decision",
        options=[d.value for d in ReviewDecision],
        horizontal=True,
        key="review_decision",
    )

    review_note = st.text_area(
        "Review note",
        placeholder="Example: Approve, but keep this as a one-day task and avoid code changes for now.",
        key="review_note",
    )

    if st.button("Record review decision", type="primary", use_container_width=True):
        new_path = add_review_record(
            selected_path,
            ReviewDecision(decision),
            review_note,
        )
        st.success(f"Review recorded. Ticket moved to: `{new_path.parent.name}`")
        st.rerun()

    st.divider()
    st.markdown("### Revise Ticket with Mica")

    revision_instruction = st.text_area(
        "Revision instruction",
        placeholder="Example: Too broad. Make this a one-day Jiuzhou task and avoid code changes for now.",
        key="revision_instruction",
    )

    if st.button("Revise ticket", use_container_width=True):
        if not revision_instruction.strip():
            st.warning("Please enter a revision instruction.")
        else:
            try:
                with st.spinner("Mica is revising the ticket..."):
                    revised = revise_ticket(
                        envelope=envelope,
                        revision_instruction=revision_instruction,
                        api_key=st.secrets["OPENAI_API_KEY"],
                        model=model,
                    )

                record_revision(revised, revision_instruction)
                overwrite_ticket(selected_path, revised)

                st.success("Ticket revised.")
                st.rerun()
            except Exception as e:
                st.error("Failed to revise ticket.")
                st.exception(e)

    st.divider()
    st.markdown("### Manual Status Change")

    status_options = [s.value for s in TicketStatus]
    new_status = st.selectbox(
        "Move ticket to status",
        options=status_options,
        index=status_options.index(ticket.status.value),
        key="manual_status_change",
    )

    if st.button("Move ticket", use_container_width=True):
        new_path = update_ticket_status(selected_path, TicketStatus(new_status))
        st.success(f"Ticket moved to: `{new_path.parent.name}`")
        st.rerun()