from datetime import datetime

from pydantic import BaseModel, ConfigDict


class Idea(BaseModel):
    id: int
    user_id: int
    text: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
