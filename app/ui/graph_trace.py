"""Graph view of the task lineage (initiative tree) for the Run tab.

Renders the root ticket and everything descended from it — child tickets,
specialist outputs — as an interactive node graph. Clicking a node opens a
detail + actions panel below the graph. This is the visual successor to the
linear trace: a graph you expand and act on.
"""

from __future__ import annotations

import streamlit as st

from storage import (
    list_specialist_output_files,
    load_specialist_output_json,
)
from ui.common import (
    ARTIFACT_NAV,
    _render_step_artifact_detail_by,
    load_all_ticket_records,
    build_ticket_indexes,
    request_nav,
    safe_enum_value,
)


# Node visual styles per artifact type.
_NODE_STYLE = {
    "ticket": {"background": "#1f3a5f", "color": "white", "border": "1px solid #2e5a8f"},
    "output": {"background": "#2f5d3a", "color": "white", "border": "1px solid #3f7d4f"},
}

_STATUS_EMOJI = {
    "drafted": "📝",
    "under_review": "🔎",
    "approved": "✅",
    "needs_revision": "✏️",
    "rejected": "🚫",
    "delegated": "📤",
    "completed": "🏁",
    "archived": "📦",
}


def _outputs_by_source_ticket() -> dict[str, list]:
    """Group all specialist outputs by their source_ticket_id."""
    grouped: dict[str, list] = {}
    for md_path in list_specialist_output_files():
        json_path = md_path.with_suffix(".json")
        if not json_path.exists():
            continue
        try:
            out = load_specialist_output_json(json_path)
        except Exception:
            continue
        if out.source_ticket_id:
            grouped.setdefault(out.source_ticket_id, []).append(out)
    return grouped


def _node_id(artifact_type: str, artifact_id: str) -> str:
    return f"{artifact_type}:{artifact_id}"


def _split_node_id(node_id: str) -> tuple[str, str]:
    atype, _, aid = node_id.partition(":")
    return atype, aid


def render_graph_trace(root_ticket_id: str, *, key: str = "run_graph") -> None:
    """Render the initiative tree rooted at root_ticket_id as a clickable graph.

    Falls back to a clear message if the graph library is unavailable or the
    initiative has no tickets on disk yet.
    """
    try:
        from streamlit_flow import StreamlitFlowEdge, StreamlitFlowNode, streamlit_flow
        from streamlit_flow.layouts import TreeLayout
        from streamlit_flow.state import StreamlitFlowState
    except Exception:
        st.info(
            "Graph view needs the `streamlit-flow-component` package. "
            "Showing the linear trace instead."
        )
        return

    records = load_all_ticket_records()
    by_id, children_by_parent, tickets_by_root = build_ticket_indexes(records)

    initiative = tickets_by_root.get(root_ticket_id, [])
    if not initiative:
        # The root may not be saved yet, or it is its own only node.
        single = by_id.get(root_ticket_id)
        if single is None:
            st.caption("No saved tickets for this initiative yet.")
            return
        initiative = [single]

    outputs_by_ticket = _outputs_by_source_ticket()

    nodes: list = []
    edges: list = []
    seen_nodes: set[str] = set()

    def add_ticket_node(envelope) -> str:
        ticket = envelope.ticket
        nid = _node_id("ticket", ticket.ticket_id)
        if nid in seen_nodes:
            return nid
        seen_nodes.add(nid)
        emoji = _STATUS_EMOJI.get(ticket.status.value, "•")
        label = f"{emoji} {ticket.title}\n[{ticket.status.value}]"
        nodes.append(
            StreamlitFlowNode(
                id=nid,
                pos=(0, 0),
                data={"content": label},
                node_type="default",
                source_position="bottom",
                target_position="top",
                selectable=True,
                draggable=True,
                style=_NODE_STYLE["ticket"],
            )
        )
        return nid

    def add_output_node(out) -> str:
        nid = _node_id("output", out.output_id)
        if nid in seen_nodes:
            return nid
        seen_nodes.add(nid)
        label = f"📄 {out.title}\n[{safe_enum_value(out.specialist_type)}]"
        nodes.append(
            StreamlitFlowNode(
                id=nid,
                pos=(0, 0),
                data={"content": label},
                node_type="default",
                source_position="bottom",
                target_position="top",
                selectable=True,
                draggable=True,
                style=_NODE_STYLE["output"],
            )
        )
        return nid

    # Build nodes/edges for every ticket in the initiative.
    for _, envelope in initiative:
        ticket = envelope.ticket
        t_nid = add_ticket_node(envelope)

        # parent → this ticket
        if ticket.parent_ticket_id and ticket.parent_ticket_id in by_id:
            p_nid = _node_id("ticket", ticket.parent_ticket_id)
            edges.append(
                StreamlitFlowEdge(
                    id=f"{p_nid}->{t_nid}", source=p_nid, target=t_nid,
                    edge_type="smoothstep", animated=False,
                )
            )

        # this ticket → its specialist outputs
        for out in outputs_by_ticket.get(ticket.ticket_id, []):
            o_nid = add_output_node(out)
            edges.append(
                StreamlitFlowEdge(
                    id=f"{t_nid}->{o_nid}", source=t_nid, target=o_nid,
                    edge_type="smoothstep", animated=False,
                )
            )

    # Persist graph state per initiative so selections survive reruns.
    state_key = f"{key}_state_{root_ticket_id}"
    if state_key not in st.session_state:
        st.session_state[state_key] = StreamlitFlowState(nodes=nodes, edges=edges)
    else:
        # Refresh nodes/edges in case the initiative grew, keep selection.
        prev = st.session_state[state_key]
        st.session_state[state_key] = StreamlitFlowState(
            nodes=nodes, edges=edges, selected_id=getattr(prev, "selected_id", None)
        )

    new_state = streamlit_flow(
        key=key,
        state=st.session_state[state_key],
        height=420,
        fit_view=True,
        show_controls=True,
        get_node_on_click=True,
        layout=TreeLayout(direction="down", node_node_spacing=90),
    )

    st.session_state[state_key] = new_state

    # --- Detail + actions for the selected node ----------------------------
    selected = getattr(new_state, "selected_id", None)
    if not selected:
        st.caption("Click a node to inspect it and act on it.")
        return

    atype, aid = _split_node_id(selected)
    if atype not in ARTIFACT_NAV:
        st.caption("This node has no detail view.")
        return

    st.divider()
    st.markdown(f"### Selected: `{atype}`")
    _render_step_artifact_detail_by(atype, aid)

    if st.button("Open in Advanced →", key=f"{key}_nav_{selected}"):
        request_nav(atype, aid)
        st.rerun()
