from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from schemas import FollowupTicketBatch, HandoffPacket, SpecialistOutput, TicketEnvelope
from storage import (
    list_specialist_output_files,
    list_ticket_json_files,
    load_specialist_output_json,
    load_ticket,
    specialist_output_to_markdown,
    ticket_to_markdown,
)


def safe_enum_value(value: object, default: str = "None") -> str:
    """Return .value for Enum-like objects, otherwise string fallback."""
    if value is None:
        return default

    return str(getattr(value, "value", value))


def build_handoff_md(packet: HandoffPacket) -> str:
    """Render a HandoffPacket as a copyable Markdown string."""
    constraints = "\n".join(f"- {c}" for c in packet.constraints) or "- None"

    return f"""# {packet.title}

## Handoff ID
{packet.handoff_id}

## Source Ticket ID
{packet.source_ticket_id or "None"}

## Source Ticket
{packet.source_ticket_title}

## Specialist
{safe_enum_value(packet.specialist_type)}

## Domain
{safe_enum_value(packet.domain_type)}

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

## Handoff Prompt
{packet.handoff_prompt}
"""


def init_session_state() -> None:
    defaults = {
        "last_ticket": None,
        "last_handoff_packet": None,
        "last_specialist_output": None,
        "last_followup_batch": None,
        "last_selected_ticket": None,
        "last_selected_output": None,
        "last_selected_graph_ticket": None,
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

            **Output Review**  
            Turn specialist outputs into follow-up ticket batches.

            **Task Graph**  
            Inspect parent, root, child, and initiative-level ticket relationships.
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


def render_ticket_lineage(envelope: TicketEnvelope) -> None:
    ticket = envelope.ticket

    with st.expander("Lineage / Task Graph"):
        st.write(f"**Ticket ID:** `{ticket.ticket_id}`")
        st.write(f"**Parent Ticket ID:** `{ticket.parent_ticket_id or 'None'}`")
        st.write(f"**Root Ticket ID:** `{ticket.root_ticket_id or 'None'}`")
        st.write(f"**Source Output ID:** `{ticket.source_output_id or 'None'}`")

        st.write("**Child Ticket IDs:**")
        if ticket.child_ticket_ids:
            for child_id in ticket.child_ticket_ids:
                st.write(f"- `{child_id}`")
        else:
            st.write("- None")


def render_ticket_summary(envelope: TicketEnvelope, *, show_status: bool = True) -> None:
    ticket = envelope.ticket

    st.markdown(f"## {ticket.title}")
    render_ticket_metrics(envelope, show_status=show_status)

    c1, c2 = st.columns(2)
    c1.metric("Specialist Type", safe_enum_value(ticket.specialist_type))
    c2.metric("Domain Type", safe_enum_value(ticket.domain_type))

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

    render_ticket_lineage(envelope)

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


def render_dashboard(folders: list[str]) -> None:
    st.markdown("### Dashboard")

    cols = st.columns(len(folders))

    for col, folder in zip(cols, folders):
        col.metric(folder, len(list_ticket_json_files(folder)))


def select_ticket_ui(prefix: str, folders: list[str]):
    folder_filter = st.selectbox(
        "Ticket folder",
        options=folders,
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

    selected_id = str(selected_path)
    if st.session_state.last_selected_ticket != selected_id:
        st.session_state.last_handoff_packet = None
        st.session_state.last_specialist_output = None
        st.session_state.last_followup_batch = None
        st.session_state.last_selected_ticket = selected_id

    envelope = load_ticket(selected_path)
    return selected_path, envelope


def select_specialist_output_ui(prefix: str, implemented_specialists: list):
    specialist_filter = st.selectbox(
        "Specialist output folder",
        options=["all"] + [s.value for s in implemented_specialists],
        index=0,
        key=f"{prefix}_specialist_output_filter",
    )

    if specialist_filter == "all":
        output_files = list_specialist_output_files()
    else:
        output_files = list_specialist_output_files(specialist_filter)

    json_files = [
        path.with_suffix(".json")
        for path in output_files
        if path.with_suffix(".json").exists()
    ]

    if not json_files:
        st.info("No specialist outputs found.")
        return None, None

    labels = [path.stem for path in json_files]

    selected_label = st.selectbox(
        "Select specialist output",
        options=labels,
        key=f"{prefix}_selected_specialist_output",
    )

    selected_path = json_files[labels.index(selected_label)]

    selected_id = str(selected_path)
    if st.session_state.last_selected_output != selected_id:
        st.session_state.last_followup_batch = None
        st.session_state.last_selected_output = selected_id

    output = load_specialist_output_json(selected_path)
    return selected_path, output


def render_specialist_output(output: SpecialistOutput, key_prefix: str = "") -> None:
    """Render a SpecialistOutput."""
    suggested_followup_tickets = getattr(output, "suggested_followup_tickets", [])

    st.divider()
    st.markdown(f"## {output.title}")

    c1, c2 = st.columns(2)
    c1.metric("Specialist", safe_enum_value(output.specialist_type))
    c2.metric("Domain", safe_enum_value(output.domain_type))

    with st.expander("Source / Lineage", expanded=False):
        st.write(f"**Output ID:** `{output.output_id}`")
        st.write(f"**Source Ticket ID:** `{output.source_ticket_id or 'None'}`")
        st.write(f"**Source Handoff ID:** `{output.source_handoff_id or 'None'}`")

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
        key=f"specialist_output_markdown_{key_prefix}{output.output_id}",
    )


def render_followup_batch(batch: FollowupTicketBatch) -> list[int]:
    """Render proposed follow-up tickets and return selected indices."""
    st.divider()
    st.markdown("### Proposed Follow-up Tickets")

    st.write("**Source Output ID:**", f"`{batch.source_output_id}`")
    st.write("**Parent Ticket ID:**", f"`{batch.parent_ticket_id or 'None'}`")
    st.write("**Root Ticket ID:**", f"`{batch.root_ticket_id or 'None'}`")

    if batch.coordination_notes:
        st.markdown("### Coordination Notes")
        st.write(batch.coordination_notes)

    selected_indices: list[int] = []

    for i, envelope in enumerate(batch.tickets):
        ticket = envelope.ticket

        checked = st.checkbox(
            f"Save ticket {i + 1}: {ticket.title}",
            value=True,
            key=f"save_followup_{i}_{ticket.ticket_id}",
        )

        with st.expander(f"{i + 1}. {ticket.title}", expanded=False):
            render_ticket_summary(envelope, show_status=True)
            render_ticket_details(envelope)

        if checked:
            selected_indices.append(i)

    return selected_indices


# ---------------------------------------------------------------------------
# Task graph helpers
# ---------------------------------------------------------------------------


def load_all_ticket_records() -> list[tuple[Path, TicketEnvelope]]:
    """Load all ticket JSON files across all folders."""
    records: list[tuple[Path, TicketEnvelope]] = []

    for path in list_ticket_json_files():
        try:
            envelope = load_ticket(path)
        except Exception:
            continue

        records.append((path, envelope))

    return records


def build_ticket_indexes(
    records: list[tuple[Path, TicketEnvelope]],
) -> tuple[
    dict[str, tuple[Path, TicketEnvelope]],
    dict[str, list[tuple[Path, TicketEnvelope]]],
    dict[str, list[tuple[Path, TicketEnvelope]]],
]:
    """Build lookup indexes for the task graph."""
    by_id: dict[str, tuple[Path, TicketEnvelope]] = {}
    children_by_parent: dict[str, list[tuple[Path, TicketEnvelope]]] = {}
    tickets_by_root: dict[str, list[tuple[Path, TicketEnvelope]]] = {}

    for path, envelope in records:
        ticket = envelope.ticket
        ticket_id = ticket.ticket_id

        by_id[ticket_id] = (path, envelope)

        if ticket.parent_ticket_id:
            children_by_parent.setdefault(ticket.parent_ticket_id, []).append(
                (path, envelope)
            )

        root_id = ticket.root_ticket_id or ticket.ticket_id
        tickets_by_root.setdefault(root_id, []).append((path, envelope))

    return by_id, children_by_parent, tickets_by_root


def ticket_option_label(envelope: TicketEnvelope) -> str:
    ticket = envelope.ticket

    return (
        f"{ticket.title} "
        f"｜ {ticket.status.value} "
        f"｜ {ticket.specialist_type.value}/{ticket.domain_type.value} "
        f"｜ {ticket.ticket_id}"
    )


def render_compact_ticket_card(
    envelope: TicketEnvelope,
    *,
    label: str,
    path: Path | None = None,
) -> None:
    ticket = envelope.ticket

    st.markdown(f"### {label}")
    st.markdown(f"**{ticket.title}**")

    c1, c2, c3 = st.columns(3)
    c1.metric("Status", ticket.status.value)
    c2.metric("Specialist", ticket.specialist_type.value)
    c3.metric("Domain", ticket.domain_type.value)

    st.write(f"**Ticket ID:** `{ticket.ticket_id}`")
    st.write(f"**Parent:** `{ticket.parent_ticket_id or 'None'}`")
    st.write(f"**Root:** `{ticket.root_ticket_id or 'None'}`")
    st.write(f"**Source Output:** `{ticket.source_output_id or 'None'}`")

    if path is not None:
        st.caption(f"File: `{path}`")

    with st.expander("Objective / Next action", expanded=False):
        st.markdown("**Objective**")
        st.write(ticket.objective)

        st.markdown("**Next action**")
        st.write(ticket.next_action)


def build_tree_lines(
    ticket_id: str,
    by_id: dict[str, tuple[Path, TicketEnvelope]],
    children_by_parent: dict[str, list[tuple[Path, TicketEnvelope]]],
    *,
    depth: int = 0,
    visited: set[str] | None = None,
) -> list[str]:
    if visited is None:
        visited = set()

    if ticket_id in visited:
        return [f"{'  ' * depth}- `{ticket_id}` ⚠️ cycle detected"]

    visited.add(ticket_id)

    if ticket_id not in by_id:
        return [f"{'  ' * depth}- `{ticket_id}` ⚠️ missing ticket"]

    _, envelope = by_id[ticket_id]
    ticket = envelope.ticket

    prefix = "  " * depth
    line = (
        f"{prefix}- **{ticket.title}** "
        f"`{ticket.ticket_id}` "
        f"— `{ticket.status.value}` "
        f"— `{ticket.specialist_type.value}/{ticket.domain_type.value}`"
    )

    lines = [line]

    children = children_by_parent.get(ticket_id, [])
    children = sorted(children, key=lambda item: item[1].ticket.title.lower())

    for _, child_envelope in children:
        lines.extend(
            build_tree_lines(
                child_envelope.ticket.ticket_id,
                by_id,
                children_by_parent,
                depth=depth + 1,
                visited=visited.copy(),
            )
        )

    return lines


def render_initiative_table(records: list[tuple[Path, TicketEnvelope]]) -> None:
    rows = []

    for path, envelope in records:
        ticket = envelope.ticket
        rows.append(
            {
                "title": ticket.title,
                "status": ticket.status.value,
                "specialist": ticket.specialist_type.value,
                "domain": ticket.domain_type.value,
                "ticket_id": ticket.ticket_id,
                "parent_ticket_id": ticket.parent_ticket_id or "",
                "source_output_id": ticket.source_output_id or "",
                "file": str(path),
            }
        )

    rows = sorted(rows, key=lambda row: (row["status"], row["title"]))

    st.dataframe(
        rows,
        use_container_width=True,
        hide_index=True,
    )