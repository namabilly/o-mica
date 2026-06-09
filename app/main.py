from __future__ import annotations

import json

import streamlit as st

from mica import create_ticket, generate_handoff_packet, revise_ticket
from schemas import (
    HandoffPacket,
    ReviewDecision,
    SpecialistOutput,
    SpecialistType,
    TicketEnvelope,
    TicketStatus,
)
from specialists import run_specialist
from storage import (
    add_review_record,
    list_ticket_json_files,
    load_ticket,
    overwrite_ticket,
    record_revision,
    save_handoff_packet,
    save_specialist_output,
    save_ticket,
    specialist_output_to_markdown,
    ticket_to_markdown,
    update_ticket_status,
)


FOLDERS = [
    "open",
    "under_review",
    "approved",
    "delegated",
    "completed",
    "archived",
    "rejected",
]


IMPLEMENTED_SPECIALISTS = [
    SpecialistType.planner,
    # Add these later after you create their prompt files:
    # SpecialistType.researcher,
    # SpecialistType.analyst,
    # SpecialistType.writer,
    # SpecialistType.engineer,
    # SpecialistType.reviewer,
    # SpecialistType.operator,
    # SpecialistType.archivist,
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def safe_enum_value(value: object, default: str = "None") -> str:
    """Return .value for Enum-like objects, otherwise string fallback."""
    if value is None:
        return default
    return str(getattr(value, "value", value))


def build_handoff_md(packet: HandoffPacket) -> str:
    """Render a HandoffPacket as a copyable Markdown string."""
    constraints = "\n".join(f"- {c}" for c in packet.constraints) or "- None"

    domain_type = getattr(packet, "domain_type", None)

    return f"""# {packet.title}

## Specialist
{safe_enum_value(packet.specialist_type)}

## Domain
{safe_enum_value(domain_type)}

## Task
{packet.task}

## Context
{packet.context}

## Constraints
{constraints}

## Required Output
{packet.required_output}

## Quality Bar
{packet.quality_bar}

## Stop Condition
{packet.stop_condition}

## Source Ticket
{packet.source_ticket_title}

## Handoff Prompt
{packet.handoff_prompt}
"""


def init_session_state() -> None:
    defaults = {
        "last_ticket": None,
        "last_handoff_packet": None,
        "last_specialist_output": None,
        "last_selected_ticket": None,
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def render_sidebar() -> tuple[str, str]:
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
            **New Edict**  
            Turn messy intent into a ticket.

            **Review Desk**  
            Approve, revise, reject, or move tickets.

            **Dispatch**  
            Prepare specialist handoff packets.

            **Specialist Desk**  
            Run universal specialists on approved handoff packets.
            """
        )

    return project_key, model


def render_ticket_metrics(envelope: TicketEnvelope, *, show_status: bool = True) -> None:
    ticket = envelope.ticket

    if show_status:
        c1, c2, c3 = st.columns(3)
        c1.metric("Status", ticket.status.value)
        c2.metric("Category", ticket.category.value)
        c3.metric("Priority", ticket.priority.value)
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Category", ticket.category.value)
        c2.metric("Priority", ticket.priority.value)
        c3.metric("Review", "Required" if ticket.human_review_required else "Optional")


def render_ticket_summary(envelope: TicketEnvelope, *, show_status: bool = True) -> None:
    ticket = envelope.ticket

    st.markdown(f"## {ticket.title}")
    render_ticket_metrics(envelope, show_status=show_status)

    specialist_type = getattr(ticket, "specialist_type", None)
    domain_type = getattr(ticket, "domain_type", None)

    if specialist_type is not None or domain_type is not None:
        c1, c2 = st.columns(2)
        c1.metric("Specialist Type", safe_enum_value(specialist_type))
        c2.metric("Domain Type", safe_enum_value(domain_type))

    st.markdown("### Objective")
    st.write(ticket.objective)

    st.markdown("### Context")
    st.write(ticket.context)

    st.markdown("### Next Action")
    st.write(ticket.next_action)

    st.markdown("### Recommended Specialist")
    st.write(ticket.recommended_specialist or "None")


def render_ticket_details(envelope: TicketEnvelope) -> None:
    ticket = envelope.ticket

    with st.expander("Assumptions"):
        st.write(ticket.assumptions or ["None"])

    with st.expander("Missing Information"):
        st.write(ticket.missing_information or ["None"])

    with st.expander("Risks"):
        st.write(ticket.risks or ["None"])

    with st.expander("Full Markdown"):
        st.code(ticket_to_markdown(envelope), language="markdown")

    with st.expander("Raw JSON"):
        st.code(
            json.dumps(envelope.model_dump(), indent=2, ensure_ascii=False),
            language="json",
        )


def render_dashboard() -> None:
    st.markdown("### Dashboard")

    cols = st.columns(len(FOLDERS))

    for col, folder in zip(cols, FOLDERS):
        col.metric(folder, len(list_ticket_json_files(folder)))


def select_ticket_ui(prefix: str):
    folder_filter = st.selectbox(
        "Ticket folder",
        options=FOLDERS,
        index=0,
        key=f"{prefix}_folder_filter",
    )

    ticket_files = list_ticket_json_files(folder_filter)

    if not ticket_files:
        st.info("No tickets in this folder.")
        return None, None

    labels = [path.stem for path in ticket_files]

    selected_label = st.selectbox(
        "Select ticket",
        options=labels,
        key=f"{prefix}_selected_ticket",
    )

    selected_path = ticket_files[labels.index(selected_label)]

    # Avoid showing stale handoff/specialist outputs for a different selected ticket.
    selected_id = str(selected_path)
    if st.session_state.last_selected_ticket != selected_id:
        st.session_state.last_handoff_packet = None
        st.session_state.last_specialist_output = None
        st.session_state.last_selected_ticket = selected_id

    envelope = load_ticket(selected_path)
    return selected_path, envelope


def render_specialist_output(output: SpecialistOutput) -> None:
    """Render a SpecialistOutput in the Specialist Desk."""
    domain_type = getattr(output, "domain_type", None)
    suggested_followup_tickets = getattr(output, "suggested_followup_tickets", [])

    st.divider()
    st.markdown(f"## {output.title}")

    c1, c2 = st.columns(2)
    c1.metric("Specialist", safe_enum_value(output.specialist_type))
    c2.metric("Domain", safe_enum_value(domain_type))

    st.markdown("### Summary")
    st.write(output.summary)

    st.markdown("### Deliverable")
    st.markdown(output.deliverable)

    with st.expander("Assumptions"):
        st.write(output.assumptions or ["None"])

    with st.expander("Risks"):
        st.write(output.risks or ["None"])

    with st.expander("Next Steps"):
        st.write(output.next_steps or ["None"])

    with st.expander("Review Questions"):
        st.write(output.review_questions or ["None"])

    with st.expander("Suggested Follow-up Tickets"):
        st.write(suggested_followup_tickets or ["None"])

    st.text_area(
        "Copy full specialist output as Markdown",
        value=specialist_output_to_markdown(output),
        height=480,
        key="specialist_output_markdown",
    )


# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------


st.set_page_config(page_title="O-Mica", page_icon="🏛️", layout="wide")

init_session_state()

st.title("🏛️ O-Mica")
st.caption("Messy request → structured ticket → review → dispatch → specialist output → archive")

project_key, model = render_sidebar()

tab_create, tab_review, tab_dispatch, tab_specialist = st.tabs(
    [
        "New Edict / 下旨",
        "Review Desk / 批奏折",
        "Dispatch / 派遣",
        "Specialist Desk / 六部",
    ]
)


# ---------------------------------------------------------------------------
# Tab 1: New Edict
# ---------------------------------------------------------------------------


with tab_create:
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


# ---------------------------------------------------------------------------
# Tab 2: Review Desk
# ---------------------------------------------------------------------------


with tab_review:
    render_dashboard()

    st.divider()
    st.subheader("Review a ticket")

    selected_path, envelope = select_ticket_ui(prefix="review")

    if envelope is not None and selected_path is not None:
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
            placeholder="Example: Too broad. Make this a one-day task and avoid code changes for now.",
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

                    revised.ticket.review_history = ticket.review_history
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


# ---------------------------------------------------------------------------
# Tab 3: Dispatch
# ---------------------------------------------------------------------------


with tab_dispatch:
    st.subheader("Prepare specialist handoff")

    selected_path, envelope = select_ticket_ui(prefix="dispatch")

    if envelope is not None and selected_path is not None:
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
                packet_path = save_handoff_packet(moved_envelope, handoff_md)

                st.session_state.last_handoff_packet = packet

                st.success(
                    f"Ticket approved and handoff packet saved to:\n\n`{packet_path}`"
                )
                st.rerun()
            except Exception as e:
                st.error("Failed to approve and generate handoff.")
                st.exception(e)

        packet = st.session_state.get("last_handoff_packet")

        if packet:
            st.divider()
            st.markdown("### Handoff Packet Preview")
            st.write(f"**Specialist:** {safe_enum_value(packet.specialist_type)}")

            domain_type = getattr(packet, "domain_type", None)
            st.write(f"**Domain:** {safe_enum_value(domain_type)}")

            st.text_area(
                "Copy handoff packet",
                value=build_handoff_md(packet),
                height=480,
                key="dispatch_handoff_packet_preview",
            )


# ---------------------------------------------------------------------------
# Tab 4: Specialist Desk
# ---------------------------------------------------------------------------


with tab_specialist:
    st.subheader("Specialist Desk / 六部")

    st.info(
        "This tab runs generalized specialists on an approved handoff packet. "
        "Start with Planner / 策士, then add Researcher, Analyst, Writer, Engineer, "
        "Reviewer, Operator, and Archivist later."
    )

    selected_specialist = st.selectbox(
        "Specialist",
        options=[s.value for s in IMPLEMENTED_SPECIALISTS],
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
        render_specialist_output(output)

        if st.button("Save specialist output", use_container_width=True):
            path = save_specialist_output(output)
            st.success(f"Saved to: `{path}`")