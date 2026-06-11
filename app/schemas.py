from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# ID / time helpers
# ---------------------------------------------------------------------------


def now_iso() -> str:
    """Current local time as an ISO-8601 string (seconds precision)."""
    return datetime.now().isoformat(timespec="seconds")


def new_ticket_id() -> str:
    return f"ticket_{uuid4().hex[:12]}"


def new_output_id() -> str:
    return f"output_{uuid4().hex[:12]}"


def new_handoff_id() -> str:
    return f"handoff_{uuid4().hex[:12]}"


def new_run_id() -> str:
    return f"run_{uuid4().hex[:12]}"


def new_deliverable_id() -> str:
    return f"deliv_{uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Core enums
# ---------------------------------------------------------------------------


class TaskCategory(str, Enum):
    game_development = "game_development"
    academic_research = "academic_research"
    writing = "writing"
    daily_management = "daily_management"
    admin = "admin"
    mixed = "mixed"


class Priority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"


class SpecialistType(str, Enum):
    planner = "planner"
    researcher = "researcher"
    analyst = "analyst"
    writer = "writer"
    engineer = "engineer"
    reviewer = "reviewer"
    operator = "operator"
    archivist = "archivist"
    none = "none"


class DomainType(str, Enum):
    general = "general"
    game = "game"
    research = "research"
    writing = "writing"
    code = "code"
    daily = "daily"
    admin = "admin"


class TicketStatus(str, Enum):
    drafted = "drafted"
    under_review = "under_review"
    approved = "approved"
    needs_revision = "needs_revision"
    rejected = "rejected"
    delegated = "delegated"
    completed = "completed"
    archived = "archived"


class WorkflowMode(str, Enum):
    manual = "manual"
    guided = "guided"
    auto = "auto"


class ReviewDecision(str, Enum):
    approve = "approve"
    approve_with_changes = "approve_with_changes"
    needs_revision = "needs_revision"
    reject = "reject"
    archive_only = "archive_only"


# Optional: for reviewing specialist outputs later.
class OutputReviewDecision(str, Enum):
    accept = "accept"
    accept_with_changes = "accept_with_changes"
    needs_revision = "needs_revision"
    reject = "reject"
    convert_to_tickets = "convert_to_tickets"
    archive = "archive"


# ---------------------------------------------------------------------------
# Review records
# ---------------------------------------------------------------------------


class ReviewRecord(BaseModel):
    decision: ReviewDecision
    note: str = ""
    timestamp: Optional[str] = None


class OutputReviewRecord(BaseModel):
    decision: OutputReviewDecision
    note: str = ""
    timestamp: Optional[str] = None


# ---------------------------------------------------------------------------
# Tickets
# ---------------------------------------------------------------------------


class TaskTicket(BaseModel):
    # Stable identity
    ticket_id: str = Field(default_factory=new_ticket_id)

    # When this ticket was first created (ISO-8601, local time). Set explicitly
    # in code at creation time (mica.create_ticket etc.). Defaults to None so
    # tickets saved before this field existed stay None and callers fall back to
    # the filename timestamp — a now_iso default would wrongly stamp "now" on
    # every load of an old ticket.
    created_at: Optional[str] = None

    # Task graph lineage
    parent_ticket_id: Optional[str] = Field(
        default=None,
        description="Direct parent ticket that led to this ticket, if any.",
    )
    root_ticket_id: Optional[str] = Field(
        default=None,
        description="Original root ticket for this task chain, if any.",
    )
    source_output_id: Optional[str] = Field(
        default=None,
        description="Specialist output that generated this ticket, if any.",
    )
    child_ticket_ids: List[str] = Field(
        default_factory=list,
        description="Follow-up tickets created from this ticket.",
    )

    # Ticket metadata
    title: str = Field(description="Short actionable title.")
    category: TaskCategory
    priority: Priority = Field(description="Estimated priority.")
    status: TicketStatus = TicketStatus.drafted

    # Routing metadata
    specialist_type: SpecialistType = SpecialistType.planner
    domain_type: DomainType = DomainType.general

    # Main task content
    objective: str = Field(description="What should be accomplished.")
    context: str = Field(description="Relevant project/user context.")
    assumptions: List[str] = Field(default_factory=list)
    missing_information: List[str] = Field(default_factory=list)

    recommended_specialist: Optional[str] = Field(
        default=None,
        description="Suggested future specialist agent, if any.",
    )

    next_action: str = Field(description="The immediate next action.")
    human_review_required: bool = True
    risks: List[str] = Field(default_factory=list)

    deliverable_format: str = Field(
        description="Expected output format, e.g. feature spec, research matrix, code plan."
    )

    handoff_prompt: Optional[str] = Field(
        default=None,
        description="Prompt that can be given to the recommended specialist.",
    )

    archive_notes: Optional[str] = Field(
        default=None,
        description="What should be saved to memory if this ticket is approved.",
    )

    review_history: List[ReviewRecord] = Field(default_factory=list)


class TicketEnvelope(BaseModel):
    ticket: TaskTicket
    review_questions: List[str] = Field(
        default_factory=list,
        description="Only questions that are truly useful for Billy to answer.",
    )
    suggested_user_reply: Optional[str] = Field(
        default=None,
        description="A short reply Billy can give to move the task forward.",
    )


class TicketRevisionRequest(BaseModel):
    original_ticket: TaskTicket
    revision_instruction: str
    review_note: str = ""


# ---------------------------------------------------------------------------
# Handoff packets
# ---------------------------------------------------------------------------


class HandoffPacket(BaseModel):
    handoff_id: str = Field(default_factory=new_handoff_id)

    title: str
    specialist_type: SpecialistType
    domain_type: DomainType

    # Source linkage
    source_ticket_id: Optional[str] = None
    source_ticket_title: str

    task: str
    context: str
    constraints: List[str] = Field(default_factory=list)
    required_output: str
    quality_bar: str
    stop_condition: str
    handoff_prompt: str


# ---------------------------------------------------------------------------
# Specialist outputs
# ---------------------------------------------------------------------------


class SpecialistOutput(BaseModel):
    output_id: str = Field(default_factory=new_output_id)

    # When this output was produced (ISO-8601, local time). Set explicitly in
    # code (specialists.run_specialist). Defaults to None so outputs saved
    # before this field existed fall back to the filename timestamp.
    created_at: Optional[str] = None

    # Source linkage
    source_ticket_id: Optional[str] = None
    source_handoff_id: Optional[str] = None

    title: str
    specialist_type: SpecialistType
    domain_type: DomainType

    summary: str
    deliverable: str

    # How to materialize the deliverable as a real file when accepted.
    deliverable_filename: Optional[str] = Field(
        default=None,
        description="Suggested filename for the deliverable, e.g. README.md, proposal.md, prompt.txt.",
    )
    deliverable_format: Optional[str] = Field(
        default=None,
        description="Short format hint for the deliverable, e.g. markdown, text, json.",
    )

    assumptions: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    next_steps: List[str] = Field(default_factory=list)
    review_questions: List[str] = Field(default_factory=list)
    suggested_followup_tickets: List[str] = Field(default_factory=list)

    review_history: List[OutputReviewRecord] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Follow-up ticket generation
# ---------------------------------------------------------------------------


class FollowupTicketBatch(BaseModel):
    """A batch of proposed follow-up tickets generated from one specialist output.

    These tickets should usually be previewed and manually selected before saving.
    """

    source_output_id: str
    parent_ticket_id: Optional[str] = None
    root_ticket_id: Optional[str] = None

    coordination_notes: str = Field(
        default="",
        description="Notes about ordering, dependencies, or coordination across the generated tickets.",
    )

    tickets: List[TicketEnvelope] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Context bundle for future coordination
# ---------------------------------------------------------------------------


class TicketContextBundle(BaseModel):
    """Context bundle for loading a ticket with its local task graph context.

    Useful later when Mica needs to revise, dispatch, summarize, or coordinate a ticket.
    """

    current_ticket: TicketEnvelope
    parent_ticket: Optional[TicketEnvelope] = None
    root_ticket: Optional[TicketEnvelope] = None
    source_output: Optional[SpecialistOutput] = None
    child_tickets: List[TicketEnvelope] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Run traces (v0.9 — workflow modes)
# ---------------------------------------------------------------------------


class RunStepStatus(str, Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    skipped = "skipped"
    waiting_for_review = "waiting_for_review"


class RunStep(BaseModel):
    """A single step in a workflow run.

    Each step usually corresponds to one orchestration action, such as creating
    a ticket, saving a handoff, or running a specialist. When a step produces a
    persisted artifact, the artifact_* fields point back to it.
    """

    name: str
    status: RunStepStatus
    message: str = ""
    artifact_type: Optional[str] = Field(
        default=None,
        description="Kind of artifact produced, e.g. ticket, handoff, output, followup_batch.",
    )
    artifact_id: Optional[str] = None
    artifact_path: Optional[str] = None
    timestamp: Optional[str] = None


class RunTrace(BaseModel):
    """A record of one workflow run across one or more steps.

    Mode belongs to the run, not the ticket: the same ticket may be processed
    manually today and in guided mode another time.
    """

    run_id: str = Field(default_factory=new_run_id)
    mode: WorkflowMode

    # What the run was about.
    request: str = ""
    project_key: str = ""

    # Lineage into the task graph.
    root_ticket_id: Optional[str] = None
    ticket_id: Optional[str] = None
    output_id: Optional[str] = None

    # running | stopped_for_review | completed | failed
    final_status: str = "running"
    stop_reason: str = Field(
        default="",
        description="Why the run stopped, e.g. what Billy needs to do next.",
    )

    started_at: Optional[str] = None
    finished_at: Optional[str] = None

    steps: List[RunStep] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Final deliverables (v0.10)
# ---------------------------------------------------------------------------


class Deliverable(BaseModel):
    """An accepted, final, user-facing artifact extracted from a specialist output.

    While outputs/ holds specialist artifacts (some intermediate), a Deliverable
    is the thing Billy accepted as done. Its `content` is written verbatim to a
    real file under deliverables/ with the right extension.
    """

    deliverable_id: str = Field(default_factory=new_deliverable_id)

    title: str
    filename: str = Field(description="Final filename, e.g. README.md.")
    content: str = Field(description="The exact file content to write to disk.")
    format: Optional[str] = Field(
        default=None,
        description="Format hint, e.g. markdown, text, json.",
    )

    # Lineage back into the task graph.
    source_output_id: Optional[str] = None
    source_ticket_id: Optional[str] = None
    root_ticket_id: Optional[str] = None

    accepted_at: Optional[str] = None
    note: str = ""