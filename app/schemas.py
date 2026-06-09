from __future__ import annotations

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


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


class ReviewDecision(str, Enum):
    approve = "approve"
    approve_with_changes = "approve_with_changes"
    needs_revision = "needs_revision"
    reject = "reject"
    archive_only = "archive_only"


class TicketStatus(str, Enum):
    drafted = "drafted"
    under_review = "under_review"
    approved = "approved"
    rejected = "rejected"
    delegated = "delegated"
    completed = "completed"
    archived = "archived"


class TaskTicket(BaseModel):
    title: str = Field(description="Short actionable title.")
    category: TaskCategory
    priority: Priority = Field(description="Estimated priority.")
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
        description="Prompt that can be given to the recommended specialist."
    )
    archive_notes: Optional[str] = Field(
        default=None,
        description="What should be saved to memory if this ticket is approved."
    )
    status: TicketStatus = TicketStatus.drafted


class TicketEnvelope(BaseModel):
    ticket: TaskTicket
    review_questions: List[str] = Field(
        default_factory=list,
        description="Only questions that are truly useful for Billy to answer."
    )
    suggested_user_reply: Optional[str] = Field(
        default=None,
        description="A short reply Billy can give to move the task forward."
    )
