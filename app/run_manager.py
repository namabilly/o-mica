"""Background run manager.

Runs workflow executions on daemon threads so they survive Streamlit reruns and
view switches. The UI observes progress through a process-global registry of run
handles instead of relying on the foreground script run (which Streamlit aborts
whenever the user interacts with any widget).

Key ideas:
- Handles live in a module-level dict, which persists across reruns because the
  module is imported once per process.
- Each handle shares a live RunTrace that the worker mutates step-by-step; the UI
  reads it each rerun to render a live trace.
- The worker thread never touches Streamlit APIs or session state (only the
  handle, under a lock), so it is safe to run without a ScriptRunContext.
"""

from __future__ import annotations

import threading
import uuid
from typing import Callable, Optional

from schemas import RunTrace, WorkflowMode
from workflows import RunResult, continue_run, run_auto, run_guided, run_manual


# Mode → entry function.
_RUNNERS: dict[WorkflowMode, Callable[..., RunResult]] = {
    WorkflowMode.manual: run_manual,
    WorkflowMode.guided: run_guided,
    WorkflowMode.auto: run_auto,
}


class RunHandle:
    """Thread-safe handle to a background run.

    status: "running" | "done" | "error"
    """

    def __init__(self, *, run_id: str, trace: RunTrace) -> None:
        self.run_id = run_id
        self._lock = threading.Lock()
        self._status = "running"
        self._trace = trace
        self._result: Optional[RunResult] = None
        self._error: Optional[str] = None

    # --- reads (cheap, lock-guarded) ---------------------------------------

    @property
    def status(self) -> str:
        with self._lock:
            return self._status

    @property
    def trace(self) -> RunTrace:
        # The trace object is shared with the worker; reading its fields for
        # display is fine even mid-mutation (worst case a step lags one poll).
        return self._trace

    @property
    def result(self) -> Optional[RunResult]:
        with self._lock:
            return self._result

    @property
    def error(self) -> Optional[str]:
        with self._lock:
            return self._error

    @property
    def is_running(self) -> bool:
        return self.status == "running"

    # --- writes (worker thread only) ---------------------------------------

    def _set_done(self, result: RunResult) -> None:
        with self._lock:
            self._result = result
            self._trace = result.trace
            self._status = "done"

    def _set_error(self, message: str) -> None:
        with self._lock:
            self._error = message
            self._status = "error"


# Process-global registry. Survives reruns; not shared across server processes,
# which is fine for a local single-user app.
_RUNS: dict[str, RunHandle] = {}
_REGISTRY_LOCK = threading.Lock()


def _register(handle: RunHandle) -> None:
    with _REGISTRY_LOCK:
        _RUNS[handle.run_id] = handle


def get_run(run_id: Optional[str]) -> Optional[RunHandle]:
    """Return the handle for run_id, if any."""
    if not run_id:
        return None
    with _REGISTRY_LOCK:
        return _RUNS.get(run_id)


def clear_run(run_id: Optional[str]) -> None:
    """Forget a run handle (e.g. after the user dismisses a finished run)."""
    if not run_id:
        return
    with _REGISTRY_LOCK:
        _RUNS.pop(run_id, None)


def _run_worker(handle: RunHandle, fn: Callable[..., RunResult], kwargs: dict) -> None:
    try:
        result = fn(**kwargs)
        handle._set_done(result)
    except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
        handle._set_error(str(exc))


def start_run(
    *,
    mode: WorkflowMode,
    user_request: str,
    project_key: str,
    api_key: str,
    model: str,
    extra_context: Optional[str] = None,
) -> str:
    """Start a workflow run on a background thread.

    Returns the run_id; the UI stores it in session state and polls via get_run.
    """
    run_id = f"uirun_{uuid.uuid4().hex[:12]}"

    # Pre-create the trace so the worker and UI share the same live object.
    trace = RunTrace(mode=mode, request=user_request, project_key=project_key)
    handle = RunHandle(run_id=run_id, trace=trace)
    _register(handle)

    runner = _RUNNERS[mode]
    kwargs = dict(
        user_request=user_request,
        project_key=project_key,
        api_key=api_key,
        model=model,
        extra_context=extra_context,
        trace=trace,
    )

    thread = threading.Thread(
        target=_run_worker,
        args=(handle, runner, kwargs),
        name=f"omica-{run_id}",
        daemon=True,
    )
    thread.start()

    return run_id


def start_continue(
    *,
    result: RunResult,
    api_key: str,
    model: str,
) -> str:
    """Continue a stopped run on a background thread, sharing its live trace."""
    run_id = f"uirun_{uuid.uuid4().hex[:12]}"

    handle = RunHandle(run_id=run_id, trace=result.trace)
    _register(handle)

    kwargs = dict(result=result, api_key=api_key, model=model)

    thread = threading.Thread(
        target=_run_worker,
        args=(handle, continue_run, kwargs),
        name=f"omica-{run_id}",
        daemon=True,
    )
    thread.start()

    return run_id
