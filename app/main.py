from __future__ import annotations

import streamlit as st

from schemas import SpecialistType
from ui.common import init_session_state, render_sidebar
from ui.run_tab import render_run_tab
from ui.create_tab import render_create_tab
from ui.review_tab import render_review_tab
from ui.dispatch_tab import render_dispatch_tab
from ui.specialist_tab import render_specialist_tab
from ui.output_review_tab import render_output_review_tab
from ui.graph_tab import render_graph_tab


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
    SpecialistType.writer,
    # Add these later after you create their prompt files:
    # SpecialistType.researcher,
    # SpecialistType.analyst,
    # SpecialistType.engineer,
    # SpecialistType.reviewer,
    # SpecialistType.operator,
    # SpecialistType.archivist,
]


st.set_page_config(page_title="O-Mica", page_icon="🏛️", layout="wide")

init_session_state()

st.title("🏛️ O-Mica")
st.caption(
    "Messy request → ticket → review → dispatch → specialist output → follow-up tickets"
)

project_key, model = render_sidebar()

(
    tab_run,
    tab_create,
    tab_review,
    tab_dispatch,
    tab_specialist,
    tab_output_review,
    tab_graph,
) = st.tabs(
    [
        "Run / 执行",
        "New Edict / 下旨",
        "Review Desk / 批奏折",
        "Dispatch / 派遣",
        "Specialist Desk / 六部",
        "Output Review / 验收",
        "Task Graph / 谱系",
    ]
)


with tab_run:
    render_run_tab(
        project_key=project_key,
        model=model,
        implemented_specialists=IMPLEMENTED_SPECIALISTS,
    )


with tab_create:
    render_create_tab(project_key=project_key, model=model)


with tab_review:
    render_review_tab(model=model, folders=FOLDERS)


with tab_dispatch:
    render_dispatch_tab(model=model, folders=FOLDERS)


with tab_specialist:
    render_specialist_tab(
        model=model,
        implemented_specialists=IMPLEMENTED_SPECIALISTS,
    )


with tab_output_review:
    render_output_review_tab(
        model=model,
        implemented_specialists=IMPLEMENTED_SPECIALISTS,
    )


with tab_graph:
    render_graph_tab()