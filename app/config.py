from functools import lru_cache

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


load_dotenv()


class Settings(BaseSettings):
    bot_token: str = Field(alias="BOT_TOKEN")
    database_url: str = Field(alias="DATABASE_URL")
    default_timezone: str = Field(default="Europe/Moscow", alias="DEFAULT_TIMEZONE")
    morning_checkin_cron: str = Field(default="0 9 * * *", alias="MORNING_CHECKIN_CRON")
    midday_checkin_cron: str = Field(default="0 13 * * *", alias="MIDDAY_CHECKIN_CRON")
    evening_review_cron: str = Field(default="0 20 * * *", alias="EVENING_REVIEW_CRON")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()

