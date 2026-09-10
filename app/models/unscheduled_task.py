from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UnscheduledTask(BaseModel):
    id: int
    user_id: int
    text: str
    estimated_minutes: int | None = None
    priority: int = Field(default=5, ge=1, le=10)
    effort: int = Field(default=5, ge=1, le=10)
    context: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
