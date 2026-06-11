# 🏛️ O-Mica · 丞相台

O-Mica is a local, human-supervised **task governance system** — a personal AI
chief-of-staff (Mica, 丞相) that turns messy requests into structured tasks,
routes them to specialists, produces real deliverables, and tracks everything
through a visible task graph.

The guiding principle: **fast when simple, controlled when risky, transparent
always, interruptible when needed.**

```text
messy request → structured ticket → review → handoff →
specialist output → accept as deliverable → follow-up tickets → task graph
```

## Workflow modes

A run advances through stopping points chosen by its mode:

- **Manual** — create the ticket, then stop for review.
- **Guided** — advance to a specialist output, then stop for acceptance.
- **Auto** — run to a final candidate (depth-1), then stop for acceptance.

Low-risk specialists (planner, writer, researcher, reviewer) may run in any
mode; engineer/operator are gated to manual but can be advanced with an explicit
**Continue**.

## Quick start

1. **Install dependencies** (Python 3.10+):

   ```bash
   pip install -r requirements.txt
   ```

2. **Configure your OpenAI key** in `.streamlit/secrets.toml`:

   ```toml
   OPENAI_API_KEY = "sk-..."
   OPENAI_MODEL   = "gpt-5.2"   # optional; defaults to gpt-5.2
   ```

   > The secrets file is the source of truth. (A stray `OPENAI_API_KEY`
   > environment variable does **not** override it.)

3. **Run the web app** from the `app/` directory:

   ```bash
   cd app
   python -m uvicorn web.server:app --port 8800
   ```

   Then open <http://127.0.0.1:8800>.

   For auto-reload during development, add `--reload`.

## Pages

- **🏠 Home** — at-a-glance status, quick run, recent runs, what needs attention.
- **🎴 Run** — one request → background run with a live trace → accept the deliverable.
- **🗂️ Tasks** — kanban board of tickets; click a card to review, dispatch, or
  inspect. Filter by specialist/domain/priority, search, and sort by time.
- **📚 Library** — saved specialist outputs, handoffs, and accepted deliverables.
- **🌸 Graph** — task lineage: each initiative from its root ticket downward.

## Architecture

```text
app/
  schemas.py        data models (tickets, handoffs, outputs, runs, deliverables)
  storage.py        file-backed persistence (tickets/ handoffs/ outputs/ runs/ deliverables/)
  mica.py           ticket creation / revision / handoff & follow-up generation
  specialists.py    specialist execution (prompts in specialists/prompts/)
  workflows.py      run orchestration (manual / guided / auto, continue, accept)
  run_manager.py    background run threads + live trace state
  web/              FastAPI + Jinja2 + HTMX UI (Server-Sent Events for live traces)
```

The engine (everything except `web/`) is UI-agnostic. Artifacts are stored as
JSON + Markdown on disk under `tickets/`, `handoffs/`, `outputs/`, `runs/`, and
`deliverables/`.
