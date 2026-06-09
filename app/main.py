from __future__ import annotations

import json
import streamlit as st

from mica import create_ticket
from storage import save_ticket, ticket_to_markdown
from schemas import TicketEnvelope


st.set_page_config(
    page_title="O-Mica",
    page_icon="🏛️",
    layout="wide",
)

st.title("🏛️ O-Mica")
st.caption("Messy request → structured ticket → human review → archive")

with st.sidebar:
    st.header("Settings")

    project_key = st.selectbox(
        "Project context",
        options=["general", "jiuzhou", "research"],
        index=0,
    )

    model = st.text_input(
        "Model",
        value=st.secrets.get("OPENAI_MODEL", "gpt-5.2"),
    )

    st.divider()

    st.markdown("### Workflow")
    st.markdown(
        """
        1. Enter messy request  
        2. Mica creates task ticket  
        3. Review manually  
        4. Save ticket  
        5. Later: send to specialist  
        """
    )

if "last_ticket" not in st.session_state:
    st.session_state.last_ticket = None

left, right = st.columns([1, 1])

with left:
    st.subheader("Issue an edict / 下旨")

    user_request = st.text_area(
        "What do you want Mica to organize?",
        height=220,
        placeholder=(
            "Example: I want to improve Jiuzhou recruitment. "
            "The shop feels boring and I want trade contracts, "
            "but I don't want to overcomplicate it."
        ),
    )

    extra_context = st.text_area(
        "Optional extra context",
        height=120,
        placeholder="Paste relevant notes, constraints, code context, paper info, etc.",
    )

    create_clicked = st.button("Create structured ticket", type="primary")

    if create_clicked:
        if not user_request.strip():
            st.warning("Please enter a request first.")
        else:
            try:
                with st.spinner("Mica is drafting the ticket..."):
                    envelope = create_ticket(
                        user_request=user_request,
                        project_key=project_key,
                        api_key=st.secrets["OPENAI_API_KEY"],
                        model=model,
                        extra_context=extra_context,
                    )
                st.session_state.last_ticket = envelope
                st.success("Ticket created.")
            except Exception as e:
                st.error("Failed to create ticket.")
                st.exception(e)

with right:
    st.subheader("Ticket Preview")

    envelope: TicketEnvelope | None = st.session_state.last_ticket

    if envelope is None:
        st.info("No ticket yet.")
    else:
        ticket = envelope.ticket

        st.markdown(f"## {ticket.title}")

        c1, c2, c3 = st.columns(3)
        c1.metric("Category", ticket.category.value)
        c2.metric("Priority", ticket.priority.value)
        c3.metric("Review", "Required" if ticket.human_review_required else "Optional")

        st.markdown("### Objective")
        st.write(ticket.objective)

        st.markdown("### Context")
        st.write(ticket.context)

        st.markdown("### Next Action")
        st.write(ticket.next_action)

        st.markdown("### Recommended Specialist")
        st.write(ticket.recommended_specialist or "None")

        with st.expander("Assumptions"):
            st.write(ticket.assumptions or ["None"])

        with st.expander("Missing Information"):
            st.write(ticket.missing_information or ["None"])

        with st.expander("Risks"):
            st.write(ticket.risks or ["None"])

        with st.expander("Handoff Prompt"):
            st.code(ticket.handoff_prompt or "None", language="markdown")

        with st.expander("Full Markdown"):
            md = ticket_to_markdown(envelope)
            st.code(md, language="markdown")

        with st.expander("Raw JSON"):
            st.code(
                json.dumps(envelope.model_dump(), indent=2, ensure_ascii=False),
                language="json",
            )

        save_clicked = st.button("Save ticket to tickets/open")

        st.markdown("### Review Decision")

        decision = st.radio(
            "Your decision",
            options=[
                "approve",
                "approve_with_changes",
                "needs_revision",
                "reject",
                "archive_only",
            ],
            horizontal=True,
        )

        review_note = st.text_area(
            "Review note",
            placeholder="Example: Good, but make this a one-day Jiuzhou task and avoid code changes for now.",
        )

        if st.button("Record review decision"):
            st.session_state.review_decision = {
                "decision": decision,
                "note": review_note,
            }
            st.success("Review decision recorded in session.")

        if save_clicked:
            json_path, md_path = save_ticket(envelope)
            st.success(f"Saved:\n\n- {json_path}\n- {md_path}")