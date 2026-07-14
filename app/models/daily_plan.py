from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class DailyPlan(BaseModel):
    id: int
    user_id: int
    plan_date: date
    day_type: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

