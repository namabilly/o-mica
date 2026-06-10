from __future__ import annotations

import streamlit as st

from ui.common import (
    build_ticket_indexes,
    build_tree_lines,
    load_all_ticket_records,
    render_compact_ticket_card,
    render_initiative_table,
    ticket_option_label,
)


def render_graph_tab() -> None:
    st.subheader("Task Graph / 谱系")

    st.info(
        "Inspect ticket lineage: root ticket, parent ticket, child tickets, "
        "and all tickets under the same initiative."
    )

    records = load_all_ticket_records()

    if not records:
        st.info("No tickets found.")
        return

    by_id, children_by_parent, tickets_by_root = build_ticket_indexes(records)

    records = sorted(records, key=lambda item: item[1].ticket.title.lower())

    labels = [ticket_option_label(envelope) for _, envelope in records]

    selected_label = st.selectbox(
        "Select any ticket",
        options=labels,
        key="graph_selected_ticket",
    )

    selected_index = labels.index(selected_label)
    selected_path, selected_envelope = records[selected_index]
    selected_ticket = selected_envelope.ticket

    st.divider()

    render_compact_ticket_card(
        selected_envelope,
        label="Current Ticket",
        path=selected_path,
    )

    st.divider()

    st.markdown("## Local Relationships")

    col_parent, col_root = st.columns(2)

    with col_parent:
        parent_id = selected_ticket.parent_ticket_id

        if parent_id and parent_id in by_id:
            parent_path, parent_envelope = by_id[parent_id]
            render_compact_ticket_card(
                parent_envelope,
                label="Parent Ticket",
                path=parent_path,
            )
        else:
            st.markdown("### Parent Ticket")
            st.info("No parent ticket.")

    with col_root:
        root_id = selected_ticket.root_ticket_id or selected_ticket.ticket_id

        if root_id and root_id in by_id:
            root_path, root_envelope = by_id[root_id]
            render_compact_ticket_card(
                root_envelope,
                label="Root Ticket",
                path=root_path,
            )
        else:
            st.markdown("### Root Ticket")
            st.info("Root ticket not found.")

    st.divider()

    st.markdown("## Child Tickets")

    children = children_by_parent.get(selected_ticket.ticket_id, [])

    if not children:
        st.info("No child tickets.")
    else:
        children = sorted(children, key=lambda item: item[1].ticket.title.lower())

        for child_path, child_envelope in children:
            with st.expander(child_envelope.ticket.title, expanded=False):
                render_compact_ticket_card(
                    child_envelope,
                    label="Child Ticket",
                    path=child_path,
                )

    st.divider()

    st.markdown("## Initiative Tree")

    root_id = selected_ticket.root_ticket_id or selected_ticket.ticket_id

    if root_id in by_id:
        lines = build_tree_lines(
            root_id,
            by_id,
            children_by_parent,
        )

        st.markdown("\n".join(lines))
    else:
        st.warning("Could not render tree because root ticket was not found.")

    st.divider()

    st.markdown("## Initiative Ticket Table")

    initiative_records = tickets_by_root.get(root_id, [])

    if initiative_records:
        render_initiative_table(initiative_records)
    else:
        st.info("No initiative records found.")