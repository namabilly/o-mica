from __future__ import annotations

import streamlit as st

from mica import create_followup_ticket_batch_from_output
from schemas import SpecialistType
from storage import save_followup_ticket_batch
from ui.common import (
    render_followup_batch,
    render_specialist_output,
    select_specialist_output_ui,
)


def render_output_review_tab(
    *,
    model: str,
    implemented_specialists: list[SpecialistType],
) -> None:
    st.subheader("Output Review / 验收")

    st.info(
        "Review saved specialist outputs and convert them into one or more follow-up tickets. "
        "Generated tickets are previewed before saving."
    )

    selected_output_path, output = select_specialist_output_ui(
        prefix="output_review",
        implemented_specialists=implemented_specialists,
    )

    if output is None or selected_output_path is None:
        return

    render_specialist_output(output, key_prefix="review_")

    st.divider()
    st.markdown("### Generate Follow-up Tickets")

    followup_instruction = st.text_area(
        "Follow-up instruction",
        placeholder=(
            "Example: Create implementation tickets from this plan. "
            "Keep each ticket small, concrete, and human-reviewed."
        ),
        key="followup_instruction",
    )

    parent_ticket_id = output.source_ticket_id
    root_ticket_id = parent_ticket_id

    c1, c2 = st.columns(2)
    c1.write(f"**Parent Ticket ID:** `{parent_ticket_id or 'None'}`")
    c2.write(f"**Root Ticket ID:** `{root_ticket_id or 'None'}`")

    if st.button(
        "Generate follow-up ticket batch",
        type="primary",
        use_container_width=True,
    ):
        if not followup_instruction.strip():
            st.warning("Please enter a follow-up instruction.")
        else:
            try:
                with st.spinner("Mica is creating follow-up tickets..."):
                    batch = create_followup_ticket_batch_from_output(
                        output=output,
                        followup_instruction=followup_instruction,
                        parent_ticket_id=parent_ticket_id,
                        root_ticket_id=root_ticket_id,
                        api_key=st.secrets["OPENAI_API_KEY"],
                        model=model,
                    )

                st.session_state.last_followup_batch = batch
                st.success(
                    f"Generated {len(batch.tickets)} proposed follow-up tickets."
                )
            except Exception as e:
                st.error("Failed to create follow-up ticket batch.")
                st.exception(e)

    batch = st.session_state.get("last_followup_batch")

    if batch:
        selected_indices = render_followup_batch(batch)

        if st.button("Save selected follow-up tickets", use_container_width=True):
            if not selected_indices:
                st.warning("No follow-up tickets selected.")
            else:
                saved_paths = save_followup_ticket_batch(
                    batch,
                    selected_indices=selected_indices,
                )

                st.success(
                    "Saved follow-up tickets:\n\n"
                    + "\n".join(f"- `{path}`" for path in saved_paths)
                )