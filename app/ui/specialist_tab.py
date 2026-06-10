from __future__ import annotations

import streamlit as st

from schemas import SpecialistType
from specialists import run_specialist
from storage import save_specialist_output
from ui.common import (
    build_handoff_md,
    render_specialist_output,
    select_handoff_packet_ui,
)


def render_specialist_tab(
    *,
    model: str,
    implemented_specialists: list[SpecialistType],
) -> None:
    st.subheader("Specialist Desk / 六部")

    st.info(
        "Run generalized specialists from a saved handoff packet. "
        "Manual paste is still available as a fallback."
    )

    input_mode = st.radio(
        "Handoff input mode",
        options=["Select saved handoff", "Paste manually"],
        horizontal=True,
        key="specialist_handoff_input_mode",
    )

    selected_specialist = None
    handoff_packet_text = ""
    source_ticket_id = None
    source_handoff_id = None

    if input_mode == "Select saved handoff":
        selected_handoff_path, packet = select_handoff_packet_ui(
            prefix="specialist",
            implemented_specialists=implemented_specialists,
        )

        if packet is not None:
            selected_specialist = packet.specialist_type
            source_ticket_id = packet.source_ticket_id
            source_handoff_id = packet.handoff_id
            handoff_packet_text = build_handoff_md(packet)

            st.markdown("### Selected Handoff")
            st.write(f"**Title:** {packet.title}")
            st.write(f"**Specialist:** `{packet.specialist_type.value}`")
            st.write(f"**Domain:** `{packet.domain_type.value}`")
            st.write(f"**Source Ticket ID:** `{packet.source_ticket_id or 'None'}`")
            st.write(f"**Handoff ID:** `{packet.handoff_id}`")

            with st.expander("Handoff Markdown", expanded=False):
                st.code(handoff_packet_text, language="markdown")

    else:
        selected_specialist_value = st.selectbox(
            "Specialist",
            options=[s.value for s in implemented_specialists],
            index=0,
            key="specialist_type_manual",
        )

        selected_specialist = SpecialistType(selected_specialist_value)

        handoff_packet_text = st.text_area(
            "Paste approved handoff packet",
            height=360,
            placeholder="Paste the handoff packet generated from the Dispatch tab.",
            key="specialist_handoff_packet",
        )

    extra_instruction = st.text_area(
        "Optional extra instruction",
        height=120,
        placeholder="Example: Make this a one-week plan. Do not suggest code implementation yet.",
        key="specialist_extra_instruction",
    )

    if st.button("Run specialist", type="primary", use_container_width=True):
        if selected_specialist is None:
            st.warning("Please select a specialist or saved handoff packet.")
        elif not handoff_packet_text.strip():
            st.warning("Please provide a handoff packet first.")
        else:
            try:
                with st.spinner("Specialist is preparing the deliverable..."):
                    output = run_specialist(
                        specialist_type=selected_specialist,
                        handoff_packet=handoff_packet_text,
                        api_key=st.secrets["OPENAI_API_KEY"],
                        model=model,
                        extra_instruction=extra_instruction,
                        source_ticket_id=source_ticket_id,
                        source_handoff_id=source_handoff_id,
                    )

                st.session_state.last_specialist_output = output
                st.success("Specialist output generated.")
            except Exception as e:
                st.error("Failed to run specialist.")
                st.exception(e)

    output = st.session_state.get("last_specialist_output")

    if output:
        render_specialist_output(output, key_prefix="run_")

        if st.button("Save specialist output", use_container_width=True):
            path = save_specialist_output(output)
            st.success(f"Saved to: `{path}`")