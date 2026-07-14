from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class TaskStatus(StrEnum):
    planned = "planned"
    done = "done"
    postponed = "postponed"
    cancelled = "cancelled"


class Task(BaseModel):
    id: int
    daily_plan_id: int
    text: str
    status: TaskStatus
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

