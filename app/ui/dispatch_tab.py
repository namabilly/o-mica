from __future__ import annotations

import streamlit as st

from mica import generate_handoff_packet
from schemas import ReviewDecision
from storage import (
    add_review_record,
    load_ticket,
    save_handoff_packet,
    save_handoff_packet_record,
)
from ui.common import (
    build_handoff_md,
    render_ticket_summary,
    safe_enum_value,
    select_ticket_ui,
)


def render_dispatch_tab(*, model: str, folders: list[str]) -> None:
    st.subheader("Prepare specialist handoff")

    selected_path, envelope = select_ticket_ui(prefix="dispatch", folders=folders)

    if envelope is None or selected_path is None:
        return

    ticket = envelope.ticket

    st.divider()
    render_ticket_summary(envelope, show_status=True)

    with st.expander("Existing ticket handoff prompt", expanded=True):
        st.text_area(
            "Copy this handoff prompt",
            value=ticket.handoff_prompt or "",
            height=220,
            key="dispatch_ticket_handoff_prompt",
        )

    st.divider()
    st.markdown("### Generate Handoff Packet")

    col_a, col_b = st.columns(2)

    with col_a:
        generate_clicked = st.button(
            "Preview handoff packet",
            use_container_width=True,
        )

    with col_b:
        approve_delegate_clicked = st.button(
            "Approve + save handoff packet",
            type="primary",
            use_container_width=True,
        )

    if generate_clicked:
        try:
            with st.spinner("Mica is preparing the handoff packet..."):
                packet = generate_handoff_packet(
                    envelope=envelope,
                    api_key=st.secrets["OPENAI_API_KEY"],
                    model=model,
                )

            st.session_state.last_handoff_packet = packet
            st.success("Handoff packet generated.")
        except Exception as e:
            st.error("Failed to generate handoff packet.")
            st.exception(e)

    if approve_delegate_clicked:
        try:
            with st.spinner("Mica is preparing and saving the handoff packet..."):
                packet = generate_handoff_packet(
                    envelope=envelope,
                    api_key=st.secrets["OPENAI_API_KEY"],
                    model=model,
                )

            handoff_md = build_handoff_md(packet)

            new_path = add_review_record(
                selected_path,
                ReviewDecision.approve,
                "Approved and delegated with handoff packet.",
            )

            moved_envelope = load_ticket(new_path)
            legacy_packet_path = save_handoff_packet(moved_envelope, handoff_md)
            handoff_json_path, handoff_md_path = save_handoff_packet_record(packet)

            st.session_state.last_handoff_packet = packet

            st.success(
                "Ticket approved and handoff packet saved:\n\n"
                f"- Legacy ticket-side Markdown: `{legacy_packet_path}`\n"
                f"- Handoff JSON: `{handoff_json_path}`\n"
                f"- Handoff Markdown: `{handoff_md_path}`"
            )
            st.rerun()
        except Exception as e:
            st.error("Failed to approve and generate handoff.")
            st.exception(e)

    packet = st.session_state.get("last_handoff_packet")

    if packet:
        st.divider()
        st.markdown("### Handoff Packet Preview")

        c1, c2 = st.columns(2)
        c1.metric("Specialist", safe_enum_value(packet.specialist_type))
        c2.metric("Domain", safe_enum_value(packet.domain_type))

        with st.expander("Handoff Source", expanded=False):
            st.write(f"**Handoff ID:** `{packet.handoff_id}`")
            st.write(f"**Source Ticket ID:** `{packet.source_ticket_id or 'None'}`")
            st.write(f"**Source Ticket:** {packet.source_ticket_title}")

        st.text_area(
            "Copy handoff packet",
            value=build_handoff_md(packet),
            height=480,
            key="dispatch_handoff_packet_preview",
        )