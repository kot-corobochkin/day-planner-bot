from datetime import datetime
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class TaskStatus(StrEnum):
    planned = "planned"
    done = "done"
    postponed = "postponed"
    cancelled = "cancelled"


class TaskValueSource(StrEnum):
    default = "default"
    user = "user"
    ai_confirmed = "ai_confirmed"


class Task(BaseModel):
    id: int
    daily_plan_id: int
    text: str
    status: TaskStatus
    first_planned_date: date
    postponement_count: int = Field(default=0, ge=0)
    estimated_minutes: int | None = None
    starts_at: datetime | None = None
    due_at: datetime | None = None
    priority: int = Field(default=5, ge=1, le=10)
    effort: int = Field(default=5, ge=1, le=10)
    priority_source: TaskValueSource = TaskValueSource.default
    effort_source: TaskValueSource = TaskValueSource.default
    duration_source: TaskValueSource = TaskValueSource.default
    context: str | None = None
    category: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
