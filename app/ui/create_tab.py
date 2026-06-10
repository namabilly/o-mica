from __future__ import annotations

import streamlit as st

from mica import create_ticket
from storage import save_ticket
from ui.common import render_ticket_details, render_ticket_summary


def render_create_tab(*, project_key: str, model: str) -> None:
    st.subheader("Create a new structured ticket")

    left, right = st.columns([0.95, 1.05], gap="large")

    with left:
        user_request = st.text_area(
            "What do you want Mica to organize?",
            height=240,
            placeholder=(
                "Example: I want to improve Jiuzhou recruitment. "
                "The shop feels boring and I want trade contracts, "
                "but I don't want to overcomplicate it."
            ),
        )

        extra_context = st.text_area(
            "Optional extra context",
            height=140,
            placeholder="Paste relevant notes, constraints, code context, paper info, etc.",
        )

        if st.button("Create structured ticket", type="primary", use_container_width=True):
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
        st.markdown("### Ticket Preview")

        envelope = st.session_state.last_ticket

        if envelope is None:
            st.info("No ticket yet.")
        else:
            render_ticket_summary(envelope, show_status=False)
            render_ticket_details(envelope)

            if st.button("Save ticket to open queue", use_container_width=True):
                json_path, md_path = save_ticket(envelope)
                st.success(f"Saved:\n\n- `{json_path}`\n- `{md_path}`")