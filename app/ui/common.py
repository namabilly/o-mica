from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from schemas import FollowupTicketBatch, HandoffPacket, SpecialistOutput, TicketEnvelope
from storage import (
    list_handoff_packet_files,
    list_specialist_output_files,
    list_ticket_json_files,
    load_handoff_packet_json,
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
        "last_run_result": None,
        "active_run_id": None,
        "active_run_polls": 0,
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def render_sidebar() -> tuple[str, str, str]:
    with st.sidebar:
        st.markdown("### 丞相台")

        view = st.radio(
            "View",
            options=["Run / 执行", "Advanced / 工房"],
            index=0,
            key="app_view",
            help=(
                "Run is the one-shot flow. Advanced exposes the step-by-step "
                "control panels (create, review, dispatch, specialists, graph)."
            ),
        )

        st.divider()

        project_key = st.selectbox(
            "Project context",
            options=["general", "jiuzhou", "research"],
            index=0,
        )

        model = st.text_input(
            "Model",
            value=st.secrets.get("OPENAI_MODEL", "gpt-5.2"),
        )

    return project_key, model, view


def _badge_line(ticket, *, show_status: bool = True) -> str:
    """One compact line of `key: value` chips for a ticket."""
    parts = []
    if show_status:
        parts.append(f"`{ticket.status.value}`")
    parts.append(f"{ticket.priority.value} priority")
    parts.append(f"{safe_enum_value(ticket.specialist_type)}/{safe_enum_value(ticket.domain_type)}")
    parts.append(f"`{ticket.category.value}`")
    return " · ".join(parts)


def render_ticket_summary(envelope: TicketEnvelope, *, show_status: bool = True) -> None:
    """Compact ticket card: title, badges, objective, next action.

    Everything verbose lives in render_ticket_details behind expanders.
    """
    ticket = envelope.ticket

    st.markdown(f"#### {ticket.title}")
    st.caption(_badge_line(ticket, show_status=show_status))

    st.markdown("**Objective**")
    st.write(ticket.objective)

    st.markdown("**Next action**")
    st.write(ticket.next_action)


def render_ticket_details(envelope: TicketEnvelope) -> None:
    """All the verbose ticket fields, folded into two expanders."""
    ticket = envelope.ticket

    with st.expander("Details"):
        st.markdown("**Context**")
        st.write(ticket.context or "None")

        st.markdown("**Recommended specialist**")
        st.write(ticket.recommended_specialist or "None")

        st.markdown("**Assumptions**")
        st.write(ticket.assumptions or ["None"])

        st.markdown("**Missing information**")
        st.write(ticket.missing_information or ["None"])

        st.markdown("**Risks**")
        st.write(ticket.risks or ["None"])

        st.markdown("**Lineage**")
        st.write(f"- Ticket: `{ticket.ticket_id}`")
        st.write(f"- Parent: `{ticket.parent_ticket_id or 'None'}`")
        st.write(f"- Root: `{ticket.root_ticket_id or 'None'}`")
        st.write(f"- Source output: `{ticket.source_output_id or 'None'}`")
        if ticket.child_ticket_ids:
            st.write("- Children: " + ", ".join(f"`{c}`" for c in ticket.child_ticket_ids))

    with st.expander("Inspect (raw)"):
        tab_md, tab_json = st.tabs(["Markdown", "JSON"])
        with tab_md:
            st.code(ticket_to_markdown(envelope), language="markdown")
        with tab_json:
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


def select_handoff_packet_ui(prefix: str, implemented_specialists: list):
    specialist_filter = st.selectbox(
        "Handoff folder",
        options=["all"] + [s.value for s in implemented_specialists],
        index=0,
        key=f"{prefix}_handoff_filter",
    )

    if specialist_filter == "all":
        handoff_files = list_handoff_packet_files()
    else:
        handoff_files = list_handoff_packet_files(specialist_filter)

    # list_handoff_packet_files returns .md files. Load matching .json files.
    json_files = [
        path.with_suffix(".json")
        for path in handoff_files
        if path.with_suffix(".json").exists()
    ]

    if not json_files:
        st.info("No saved handoff packets found.")
        return None, None

    labels = [path.stem for path in json_files]

    selected_label = st.selectbox(
        "Select saved handoff packet",
        options=labels,
        key=f"{prefix}_selected_handoff_packet",
    )

    selected_path = json_files[labels.index(selected_label)]
    packet = load_handoff_packet_json(selected_path)

    return selected_path, packet
    

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
    """Render a SpecialistOutput, leading with the deliverable itself.

    The deliverable is the thing Billy wants; meta (assumptions, risks, lineage)
    and raw dumps are folded into two expanders below it.
    """
    suggested_followup_tickets = getattr(output, "suggested_followup_tickets", [])

    st.markdown(f"#### {output.title}")
    badges = [
        f"{safe_enum_value(output.specialist_type)}/{safe_enum_value(output.domain_type)}"
    ]
    if getattr(output, "deliverable_filename", None):
        badges.append(f"`{output.deliverable_filename}`")
    st.caption(" · ".join(badges))

    if output.summary:
        st.caption(output.summary)

    # The deliverable, front and center.
    st.markdown(output.deliverable)

    with st.expander("Details & meta"):
        st.markdown("**Assumptions**")
        st.write(output.assumptions or ["None"])
        st.markdown("**Risks**")
        st.write(output.risks or ["None"])
        st.markdown("**Next steps**")
        st.write(output.next_steps or ["None"])
        st.markdown("**Review questions**")
        st.write(output.review_questions or ["None"])
        st.markdown("**Suggested follow-up tickets**")
        st.write(suggested_followup_tickets or ["None"])
        st.markdown("**Lineage**")
        st.write(f"- Output: `{output.output_id}`")
        st.write(f"- Source ticket: `{output.source_ticket_id or 'None'}`")
        st.write(f"- Source handoff: `{output.source_handoff_id or 'None'}`")

    with st.expander("Inspect (raw)"):
        st.code(specialist_output_to_markdown(output), language="markdown")


def _guess_filename(output) -> str:
    """Best-effort default filename for accepting an output as a deliverable."""
    suggested = getattr(output, "deliverable_filename", None)
    if suggested:
        return suggested

    # Fall back to a slug of the title with a .md extension.
    title = (output.title or "deliverable").lower().strip()
    slug = "".join(c if c.isalnum() else "-" for c in title).strip("-") or "deliverable"
    return f"{slug}.md"


def render_accept_deliverable(output, *, key_prefix: str = "") -> None:
    """Render the 'accept as final deliverable' control for a specialist output.

    Lets Billy confirm/edit the filename, saves the deliverable's content to a
    real file under deliverables/, and offers an immediate download.
    """
    from workflows import accept_output_as_deliverable

    st.markdown("### Accept as Final Deliverable")
    st.caption(
        "Save the deliverable to a real file under `deliverables/` and download it."
    )

    filename = st.text_input(
        "Filename",
        value=_guess_filename(output),
        key=f"{key_prefix}deliverable_filename_{output.output_id}",
    )

    note = st.text_input(
        "Acceptance note (optional)",
        value="",
        key=f"{key_prefix}deliverable_note_{output.output_id}",
    )

    has_ticket = bool(getattr(output, "source_ticket_id", None))
    close_ticket = st.checkbox(
        "Mark source ticket completed",
        value=has_ticket,
        disabled=not has_ticket,
        help=(
            f"Move ticket `{output.source_ticket_id}` to completed."
            if has_ticket
            else "This output has no linked source ticket."
        ),
        key=f"{key_prefix}deliverable_close_{output.output_id}",
    )

    # Always offer the raw content for download, even before saving.
    st.download_button(
        "Download deliverable",
        data=output.deliverable,
        file_name=filename or _guess_filename(output),
        mime="text/plain",
        use_container_width=True,
        key=f"{key_prefix}deliverable_download_{output.output_id}",
    )

    if st.button(
        "Accept and save deliverable",
        type="primary",
        use_container_width=True,
        key=f"{key_prefix}deliverable_accept_{output.output_id}",
    ):
        accept = accept_output_as_deliverable(
            output=output,
            filename=filename or None,
            note=note,
            close_ticket=close_ticket,
        )
        st.success(f"Saved final deliverable to: `{accept.artifact_path}`")
        if accept.closed_ticket_id:
            st.success(f"Ticket `{accept.closed_ticket_id}` marked completed.")


_RUN_STEP_ICONS = {
    "succeeded": "✅",
    "failed": "❌",
    "running": "⏳",
    "pending": "⬜",
    "skipped": "⏭️",
    "waiting_for_review": "🟡",
}


def render_run_trace(trace, *, expanded: bool = True) -> None:
    """Render a RunTrace: header metrics plus a step-by-step timeline."""
    st.markdown("### Trace / 执行轨迹")

    c1, c2, c3 = st.columns(3)
    c1.metric("Mode", safe_enum_value(trace.mode))
    c2.metric("Final Status", trace.final_status)
    c3.metric("Steps", len(trace.steps))

    if trace.stop_reason:
        st.info(trace.stop_reason)

    with st.expander("Steps", expanded=expanded):
        for i, step in enumerate(trace.steps, start=1):
            icon = _RUN_STEP_ICONS.get(safe_enum_value(step.status), "•")
            line = f"{icon} **{i}. {step.name}** — `{safe_enum_value(step.status)}`"
            if step.message:
                line += f" — {step.message}"
            st.markdown(line)

            if step.artifact_id or step.artifact_path:
                detail = f"`{step.artifact_type or 'artifact'}: {step.artifact_id or 'None'}`"
                st.caption(detail)
                if step.artifact_path:
                    st.caption(f"File: `{step.artifact_path}`")

    with st.expander("Lineage", expanded=False):
        st.write(f"**Run ID:** `{trace.run_id}`")
        st.write(f"**Root Ticket ID:** `{trace.root_ticket_id or 'None'}`")
        st.write(f"**Ticket ID:** `{trace.ticket_id or 'None'}`")
        st.write(f"**Output ID:** `{trace.output_id or 'None'}`")


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