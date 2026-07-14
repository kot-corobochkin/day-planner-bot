from datetime import datetime

from pydantic import BaseModel, ConfigDict


class User(BaseModel):
    id: int
    telegram_id: int
    timezone: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

