from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DayStateProfile(BaseModel):
    daily_plan_id: int
    survey_mode: str
    brain_energy: int = Field(ge=1, le=10)
    concentration: int = Field(ge=1, le=10)
    mental_fatigue: int = Field(ge=1, le=10)
    physical_energy: int = Field(ge=1, le=10)
    desired_day_mode: str
    alternate_categories: bool | None = None
    long_answers: dict[str, Any] = Field(default_factory=dict)
    recommended_strategies: list[str] = Field(default_factory=list)
    selected_strategy: str
    strategy_reason: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
