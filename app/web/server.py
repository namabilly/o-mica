"""O-Mica FastAPI web app.

Server-rendered (Jinja2) + HTMX, reusing the existing engine (storage, mica,
workflows, run_manager) untouched. Runs alongside the Streamlit app.

Launch:
    cd app && python -m uvicorn web.server:app --reload --port 8800
or:
    cd app && python web/server.py
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

from run_manager import get_run, start_continue, start_run
from schemas import ReviewDecision, SpecialistType, TicketStatus, WorkflowMode
from storage import (
    add_review_record,
    find_ticket_path_by_id,
    list_run_trace_files,
    list_ticket_json_files,
    load_run_trace_json,
    load_ticket,
    load_ticket_by_id,
    overwrite_ticket,
    record_revision,
    save_handoff_packet_record,
    save_ticket,
    update_ticket_status,
)
from web import graph as graph_view, library as library_view, settings, tasks as tasks_view
from web.runs import sse_trace, steps_view


# Specialists offered as routing hints in the Run form.
SPECIALISTS = ["planner", "writer", "researcher", "reviewer"]

# Map a finished run's final_status to a pill class for templates.
def _status_pill(status: str) -> str:
    cls = {
        "completed": "done", "stopped_for_review": "review",
        "running": "progress", "failed": "muted",
        "drafted": "open", "approved": "progress",
    }.get(str(getattr(status, "value", status)), "muted")
    label = str(getattr(status, "value", status)).replace("_", " ")
    return f'<span class="pill {cls}">{label}</span>'

HERE = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(HERE / "templates"))

app = FastAPI(title="O-Mica")
app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

def _status_dot(status: str) -> str:
    s = str(getattr(status, "value", status))
    return {
        "drafted": "lav", "needs_revision": "lav", "open": "lav",
        "under_review": "peach",
        "approved": "sky", "delegated": "sky",
        "completed": "mint",
        "rejected": "muted", "archived": "muted",
    }.get(s, "muted")


# Expose helpers to templates.
TEMPLATES.env.globals["status_pill"] = _status_pill
TEMPLATES.env.globals["status_dot"] = _status_dot

# Per-browser active run: cookie session id -> run_id.
_SESSION_RUN: dict[str, str] = {}


def _session_id(request: Request) -> str:
    return request.cookies.get("omica_sid", "")


def _set_session_cookie(response, sid: str) -> None:
    response.set_cookie("omica_sid", sid, max_age=60 * 60 * 24 * 7, samesite="lax")


# Navigation registry: (key, icon, label). Adding a page is one line.
PAGES = [
    ("home", "🏠", "Home"),
    ("run", "🎴", "Run"),
    ("tasks", "🗂️", "Tasks"),
    ("library", "📚", "Library"),
    ("graph", "🌸", "Graph"),
]

_FACES = ["(>ω<)", "(｡･ω･｡)", "(◕‿◕)", "(✿◕‿◕)", "ヽ(・∀・)ﾉ"]


def base_ctx(request: Request, active: str) -> dict:
    """Shared template context for the shell."""
    return {
        "request": request,
        "pages": PAGES,
        "active": active,
        "face": random.choice(_FACES),
        "project": "general",
        "model": settings.model(),
        "projects": settings.PROJECTS,
    }


def _greeting() -> str:
    h = datetime.now().hour
    return "Good morning" if h < 12 else "Good afternoon" if h < 18 else "Good evening"


def _count(folder: str) -> int:
    return len(list_ticket_json_files(folder))


# ---------------------------------------------------------------------------
# Home
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    recent = []
    for path in list_run_trace_files()[:4]:
        try:
            r = load_run_trace_json(path)
        except Exception:
            continue
        title = (r.request or "untitled")[:34]
        recent.append({"title": title, "status": r.final_status})

    open_n, review_n = _count("open"), _count("under_review")
    attention = []
    if review_n:
        attention.append(
            {"icon": "📝", "title": f"{review_n} ticket(s)", "detail": "awaiting review", "go": "tasks"}
        )
    if open_n:
        attention.append(
            {"icon": "🗂️", "title": f"{open_n} open ticket(s)", "detail": "ready to dispatch or run", "go": "tasks"}
        )

    ctx = base_ctx(request, "home")
    ctx.update(
        greeting=_greeting(),
        counts={
            "open": open_n,
            "review": review_n,
            "progress": _count("delegated"),
            "done": _count("completed"),
        },
        recent=recent,
        attention=attention,
    )
    return TEMPLATES.TemplateResponse(request, "home.html", ctx)


# ---------------------------------------------------------------------------
# Run page
# ---------------------------------------------------------------------------


@app.get("/run", response_class=HTMLResponse)
def run_page(request: Request, q_request: str = "", mode: str = "", request_: str = ""):
    # Home's Quick Run posts as ?request=...&mode=...
    prefill_request = request.query_params.get("request", "")
    prefill_mode = request.query_params.get("mode", "")

    sid = _session_id(request)
    active = _SESSION_RUN.get(sid)
    # Only treat as active if the handle still exists.
    if active and get_run(active) is None:
        active = None

    ctx = base_ctx(request, "run")
    ctx.update(
        specialists=SPECIALISTS,
        prefill_request=prefill_request,
        prefill_mode=prefill_mode,
        active_run_id=active,
    )
    resp = TEMPLATES.TemplateResponse(request, "run.html", ctx)
    if not sid:
        _set_session_cookie(resp, uuid.uuid4().hex)
    return resp


def _build_context(specialist: str) -> str | None:
    if specialist and specialist != "auto":
        return f"Routing hint: prefer specialist_type = {specialist} if appropriate."
    return None


@app.post("/run", response_class=HTMLResponse)
def run_start(
    request: Request,
    user_request: str = Form("", alias="request"),
    mode: str = Form("auto"),
    specialist: str = Form("auto"),
):
    sid = _session_id(request) or uuid.uuid4().hex
    if not user_request.strip():
        return HTMLResponse("<p class='muted'>Type a request first ～</p>")

    run_id = start_run(
        mode=WorkflowMode(mode),
        user_request=user_request,
        project_key="general",
        api_key=settings.api_key(),
        model=settings.model(),
        extra_context=_build_context(specialist),
    )
    _SESSION_RUN[sid] = run_id

    ctx = base_ctx(request, "run")
    ctx["active_run_id"] = run_id
    resp = TEMPLATES.TemplateResponse(request, "_run_live.html", ctx)
    _set_session_cookie(resp, sid)
    return resp


@app.get("/run/stream/{run_id}")
async def run_stream(request: Request, run_id: str):
    def render_steps(steps):
        return TEMPLATES.get_template("_trace_steps.html").render(steps=steps)

    return EventSourceResponse(sse_trace(run_id, render_steps))


def _result_ctx(request: Request, run_id: str) -> dict:
    handle = get_run(run_id)
    ctx = base_ctx(request, "run")
    if handle is None or handle.result is None:
        err = handle.error if handle is not None else "run not found"
        ctx.update(
            output=None, ticket=None, steps=[], final_status="failed",
            run_id=run_id, error=err,
        )
        return ctx
    res = handle.result
    ctx.update(
        run_id=run_id,
        output=res.output,
        ticket=res.ticket.ticket if res.ticket else None,
        steps=steps_view(res.trace),
        final_status=res.trace.final_status,
        stop_reason=res.trace.stop_reason,
        can_continue=(res.output is None and res.ticket is not None),
    )
    return ctx


@app.get("/run/result/{run_id}", response_class=HTMLResponse)
def run_result(request: Request, run_id: str):
    ctx = _result_ctx(request, run_id)
    return TEMPLATES.TemplateResponse(request, "_run_result.html", ctx)


@app.post("/run/{run_id}/accept", response_class=HTMLResponse)
def run_accept(
    request: Request,
    run_id: str,
    filename: str = Form("deliverable.md"),
    close_ticket: str = Form(None),
):
    from workflows import accept_output_as_deliverable

    handle = get_run(run_id)
    if handle is None or handle.result is None or handle.result.output is None:
        return HTMLResponse("<p class='muted'>Nothing to accept.</p>")

    res = handle.result
    accept = accept_output_as_deliverable(
        output=res.output,
        filename=filename or None,
        close_ticket=bool(close_ticket),
        root_ticket_id=res.trace.root_ticket_id,
    )
    msg = f"<p class='pill done' style='display:inline-block'>saved → {accept.artifact_path}</p>"
    if accept.closed_ticket_id:
        msg += f"<p class='muted'>ticket {accept.closed_ticket_id} marked completed ✿</p>"
    return HTMLResponse(msg)


@app.post("/run/{run_id}/continue", response_class=HTMLResponse)
def run_continue(request: Request, run_id: str):
    handle = get_run(run_id)
    if handle is None or handle.result is None:
        return HTMLResponse("<p class='muted'>Run not found.</p>")

    new_id = start_continue(
        result=handle.result,
        api_key=settings.api_key(),
        model=settings.model(),
    )
    sid = _session_id(request) or uuid.uuid4().hex
    _SESSION_RUN[sid] = new_id
    ctx = base_ctx(request, "run")
    ctx["active_run_id"] = new_id
    resp = TEMPLATES.TemplateResponse(request, "_run_live.html", ctx)
    _set_session_cookie(resp, sid)
    return resp


# ---------------------------------------------------------------------------
# Tasks (kanban)
# ---------------------------------------------------------------------------


@app.get("/tasks", response_class=HTMLResponse)
def tasks_page(request: Request):
    ctx = base_ctx(request, "tasks")
    ctx["columns"] = tasks_view.board()
    return TEMPLATES.TemplateResponse(request, "tasks.html", ctx)


def _ticket_view(envelope) -> dict:
    t = envelope.ticket
    return {
        "id": t.ticket_id,
        "title": t.title,
        "status": str(getattr(t.status, "value", t.status)),
        "specialist": str(getattr(t.specialist_type, "value", t.specialist_type)),
        "domain": str(getattr(t.domain_type, "value", t.domain_type)),
        "priority": str(getattr(t.priority, "value", t.priority)),
        "objective": t.objective,
        "handoff_prompt": t.handoff_prompt or "",
    }


@app.get("/tasks/new", response_class=HTMLResponse)
def tasks_new(request: Request):
    ctx = base_ctx(request, "tasks")
    return TEMPLATES.TemplateResponse(request, "_task_new.html", ctx)


@app.get("/tasks/board", response_class=HTMLResponse)
def tasks_board(request: Request):
    ctx = base_ctx(request, "tasks")
    ctx["columns"] = tasks_view.board()
    return TEMPLATES.TemplateResponse(request, "_task_board.html", ctx)


@app.get("/tasks/{ticket_id}", response_class=HTMLResponse)
def task_modal(request: Request, ticket_id: str):
    env = load_ticket_by_id(ticket_id)
    if env is None:
        return HTMLResponse("<div class='modal'><p class='muted'>Ticket not found.</p></div>")
    ctx = base_ctx(request, "tasks")
    ctx.update(
        t=_ticket_view(env),
        raw=env.model_dump_json(indent=2),
        decisions=[d.value for d in ReviewDecision],
        statuses=[s.value for s in TicketStatus],
    )
    return TEMPLATES.TemplateResponse(request, "_task_modal.html", ctx)


@app.post("/tasks/{ticket_id}/review", response_class=HTMLResponse)
def task_review(request: Request, ticket_id: str, decision: str = Form(...), note: str = Form("")):
    path = find_ticket_path_by_id(ticket_id)
    if path is None:
        return HTMLResponse("<div class='modal'><p class='muted'>Ticket not found.</p></div>")
    add_review_record(path, ReviewDecision(decision), note)
    # Close modal + signal the board to refresh via HX-Trigger.
    return HTMLResponse("", headers={"HX-Trigger": "ticketChanged"})


@app.post("/tasks/{ticket_id}/move", response_class=HTMLResponse)
def task_move(request: Request, ticket_id: str, status: str = Form(...)):
    path = find_ticket_path_by_id(ticket_id)
    if path is None:
        return HTMLResponse("<div class='modal'><p class='muted'>Ticket not found.</p></div>")
    update_ticket_status(path, TicketStatus(status))
    return HTMLResponse("", headers={"HX-Trigger": "ticketChanged"})


@app.post("/tasks/{ticket_id}/revise", response_class=HTMLResponse)
def task_revise(request: Request, ticket_id: str, instruction: str = Form("")):
    from mica import revise_ticket

    path = find_ticket_path_by_id(ticket_id)
    env = load_ticket_by_id(ticket_id)
    if path is None or env is None:
        return HTMLResponse("<div class='modal'><p class='muted'>Ticket not found.</p></div>")
    if not instruction.strip():
        return task_modal(request, ticket_id)
    try:
        revised = revise_ticket(
            envelope=env, revision_instruction=instruction,
            api_key=settings.api_key(), model=settings.model(),
        )
        record_revision(revised, instruction)
        overwrite_ticket(path, revised)
    except Exception as e:
        return HTMLResponse(f"<div class='modal'><p class='muted'>Revise failed: {e}</p></div>")
    return task_modal(request, ticket_id)


@app.post("/tasks/{ticket_id}/dispatch", response_class=HTMLResponse)
def task_dispatch(request: Request, ticket_id: str):
    from mica import generate_handoff_packet

    env = load_ticket_by_id(ticket_id)
    if env is None:
        return HTMLResponse("<p class='muted'>Ticket not found.</p>")
    try:
        packet = generate_handoff_packet(
            envelope=env, api_key=settings.api_key(), model=settings.model()
        )
        save_handoff_packet_record(packet)
    except Exception as e:
        return HTMLResponse(f"<p class='muted'>Dispatch failed: {e}</p>")
    return HTMLResponse(
        f"<p class='pill done' style='display:inline-block'>handoff saved → {packet.handoff_id}</p>"
        f"<pre style='background:var(--bg-soft);border-radius:12px;padding:12px;"
        f"white-space:pre-wrap;font-size:12px;margin-top:8px'>{packet.handoff_prompt}</pre>"
    )


@app.post("/tasks/create", response_class=HTMLResponse)
def task_create(request: Request, request_text: str = Form("", alias="request"), context: str = Form("")):
    from mica import create_ticket

    if not request_text.strip():
        return HTMLResponse("<p class='muted'>Type a request first ～</p>")
    try:
        env = create_ticket(
            user_request=request_text, project_key="general",
            api_key=settings.api_key(), model=settings.model(),
            extra_context=context or None,
        )
        save_ticket(env)
    except Exception as e:
        return HTMLResponse(f"<p class='muted'>Create failed: {e}</p>")
    t = _ticket_view(env)
    return HTMLResponse(
        f"<p class='pill done' style='display:inline-block'>created → {t['title']}</p>"
        f"<p class='muted' style='font-size:13px'>{t['objective']}</p>"
        f"<button class='btn sm' onclick=\"document.getElementById('modal').innerHTML='';location.reload()\">Close &amp; refresh board</button>"
    )


# ---------------------------------------------------------------------------
# Library
# ---------------------------------------------------------------------------


@app.get("/library", response_class=HTMLResponse)
def library_page(request: Request):
    ctx = base_ctx(request, "library")
    ctx.update(
        outputs=library_view.outputs(),
        handoffs=library_view.handoffs(),
        deliverables=library_view.deliverables(),
    )
    return TEMPLATES.TemplateResponse(request, "library.html", ctx)


@app.get("/library/output/{output_id}", response_class=HTMLResponse)
def library_output(request: Request, output_id: str):
    o = library_view.output_by_id(output_id)
    if o is None:
        return HTMLResponse("<div class='modal'><p class='muted'>Output not found.</p></div>")
    ctx = base_ctx(request, "library")
    ctx["o"] = {
        "id": o.output_id, "title": o.title,
        "specialist": str(getattr(o.specialist_type, "value", o.specialist_type)),
        "domain": str(getattr(o.domain_type, "value", o.domain_type)),
        "summary": o.summary, "deliverable": o.deliverable,
        "deliverable_filename": getattr(o, "deliverable_filename", None),
    }
    return TEMPLATES.TemplateResponse(request, "_output_modal.html", ctx)


@app.post("/library/output/{output_id}/accept", response_class=HTMLResponse)
def library_output_accept(
    request: Request, output_id: str,
    filename: str = Form("deliverable.md"), close_ticket: str = Form(None),
):
    from workflows import accept_output_as_deliverable

    o = library_view.output_by_id(output_id)
    if o is None:
        return HTMLResponse("<p class='muted'>Output not found.</p>")
    accept = accept_output_as_deliverable(
        output=o, filename=filename or None, close_ticket=bool(close_ticket),
    )
    msg = f"<p class='pill done' style='display:inline-block'>saved → {accept.artifact_path}</p>"
    if accept.closed_ticket_id:
        msg += f"<p class='muted'>ticket {accept.closed_ticket_id} completed ✿</p>"
    return HTMLResponse(msg)


@app.get("/library/handoff/{handoff_id}", response_class=HTMLResponse)
def library_handoff(request: Request, handoff_id: str):
    from storage import handoff_packet_to_markdown

    h = library_view.handoff_by_id(handoff_id)
    if h is None:
        return HTMLResponse("<div class='modal'><p class='muted'>Handoff not found.</p></div>")
    ctx = base_ctx(request, "library")
    ctx["h"] = {
        "id": h.handoff_id, "title": h.title,
        "specialist": str(getattr(h.specialist_type, "value", h.specialist_type)),
        "domain": str(getattr(h.domain_type, "value", h.domain_type)),
        "markdown": handoff_packet_to_markdown(h),
    }
    return TEMPLATES.TemplateResponse(request, "_handoff_modal.html", ctx)


@app.post("/library/handoff/{handoff_id}/run", response_class=HTMLResponse)
def library_handoff_run(request: Request, handoff_id: str):
    from specialists import run_specialist
    from storage import handoff_packet_to_markdown, save_specialist_output

    h = library_view.handoff_by_id(handoff_id)
    if h is None:
        return HTMLResponse("<p class='muted'>Handoff not found.</p>")
    try:
        out = run_specialist(
            specialist_type=h.specialist_type,
            handoff_packet=handoff_packet_to_markdown(h),
            api_key=settings.api_key(), model=settings.model(),
            source_ticket_id=h.source_ticket_id, source_handoff_id=h.handoff_id,
        )
        save_specialist_output(out)
    except Exception as e:
        return HTMLResponse(f"<p class='muted'>Run failed: {e}</p>")
    return HTMLResponse(
        f"<p class='pill done' style='display:inline-block'>output saved → {out.title}</p>"
        f"<p class='muted' style='font-size:13px'>Find it in the Outputs tab.</p>"
    )


@app.get("/library/deliverable/{deliverable_id}/download")
def library_deliverable_download(deliverable_id: str):
    from fastapi.responses import PlainTextResponse

    d = library_view.deliverable_by_id(deliverable_id)
    if d is None:
        return PlainTextResponse("not found", status_code=404)
    return PlainTextResponse(
        d.content,
        headers={"Content-Disposition": f'attachment; filename="{d.filename}"'},
    )


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------


@app.get("/graph", response_class=HTMLResponse)
def graph_page(request: Request):
    ctx = base_ctx(request, "graph")
    ctx["initiatives"] = graph_view.initiatives()
    return TEMPLATES.TemplateResponse(request, "graph.html", ctx)


# ---------------------------------------------------------------------------
# Placeholder fallback (unknown pages)
# ---------------------------------------------------------------------------


@app.get("/{page}", response_class=HTMLResponse)
def coming_soon(request: Request, page: str):
    valid = {k for k, _, _ in PAGES}
    active = page if page in valid else "home"
    ctx = base_ctx(request, active)
    label = next((l for k, _, l in PAGES if k == active), "Home")
    ctx["label"] = label
    return TEMPLATES.TemplateResponse(request, "coming_soon.html", ctx)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("web.server:app", host="127.0.0.1", port=8800, reload=False)
