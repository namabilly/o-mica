from __future__ import annotations

import streamlit as st

from schemas import SpecialistType
from specialists import run_specialist
from storage import save_specialist_output
from ui.common import render_specialist_output


def render_specialist_tab(
    *,
    model: str,
    implemented_specialists: list[SpecialistType],
) -> None:
    st.subheader("Specialist Desk / 六部")

    st.info(
        "This tab runs generalized specialists on an approved handoff packet. "
        "Start with Planner / 策士, then add Researcher, Analyst, Writer, Engineer, "
        "Reviewer, Operator, and Archivist later."
    )

    selected_specialist = st.selectbox(
        "Specialist",
        options=[s.value for s in implemented_specialists],
        index=0,
        key="specialist_type",
    )

    handoff_packet = st.text_area(
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
        if not handoff_packet.strip():
            st.warning("Please paste a handoff packet first.")
        else:
            try:
                with st.spinner("Specialist is preparing the deliverable..."):
                    output = run_specialist(
                        specialist_type=SpecialistType(selected_specialist),
                        handoff_packet=handoff_packet,
                        api_key=st.secrets["OPENAI_API_KEY"],
                        model=model,
                        extra_instruction=extra_instruction,
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