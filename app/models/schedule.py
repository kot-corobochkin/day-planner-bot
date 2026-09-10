from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ScheduleRunStatus(StrEnum):
    active = "active"
    superseded = "superseded"
    stale = "stale"


class DailyScheduleRun(BaseModel):
    id: int
    daily_plan_id: int
    source: str
    status: ScheduleRunStatus
    created_at: datetime
    applied_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ScheduleSlot(BaseModel):
    id: int
    schedule_run_id: int
    task_id: int
    position: int = Field(ge=1)
    starts_at: datetime
    ends_at: datetime
    buffer_after_minutes: int = Field(ge=0, le=120)
    reason: str | None = None

    model_config = ConfigDict(from_attributes=True)
