from functools import lru_cache

from dotenv import load_dotenv
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


load_dotenv()


class Settings(BaseSettings):
    bot_token: str = Field(alias="BOT_TOKEN")
    database_url: str = Field(alias="DATABASE_URL")
    default_timezone: str = Field(default="Europe/Moscow", alias="DEFAULT_TIMEZONE")
    morning_checkin_cron: str = Field(default="0 9 * * *", alias="MORNING_CHECKIN_CRON")
    midday_checkin_cron: str = Field(default="0 13 * * *", alias="MIDDAY_CHECKIN_CRON")
    evening_review_cron: str = Field(default="0 20 * * *", alias="EVENING_REVIEW_CRON")
    weekly_stats_cron: str = Field(default="0 21 * * 0", alias="WEEKLY_STATS_CRON")
    scheduler_misfire_grace_seconds: int = Field(
        default=7_200,
        ge=1,
        alias="SCHEDULER_MISFIRE_GRACE_SECONDS",
    )
    telegram_connect_timeout_seconds: float = Field(
        default=10,
        gt=0,
        alias="TELEGRAM_CONNECT_TIMEOUT_SECONDS",
    )
    telegram_read_timeout_seconds: float = Field(
        default=30,
        gt=0,
        alias="TELEGRAM_READ_TIMEOUT_SECONDS",
    )
    telegram_write_timeout_seconds: float = Field(
        default=30,
        gt=0,
        alias="TELEGRAM_WRITE_TIMEOUT_SECONDS",
    )
    telegram_pool_timeout_seconds: float = Field(
        default=5,
        gt=0,
        alias="TELEGRAM_POOL_TIMEOUT_SECONDS",
    )
    llm_api_key: SecretStr = Field(alias="API_KEY")
    model_name: str = Field(alias="MODEL_NAME")
    model_fallbacks: str = Field(default="", alias="MODEL_FALLBACKS")
    llm_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        alias="LLM_BASE_URL",
    )
    llm_timeout_seconds: float = Field(default=60, gt=0, alias="LLM_TIMEOUT_SECONDS")
    llm_max_output_tokens: int = Field(
        default=4_096,
        ge=1,
        le=8_192,
        alias="LLM_MAX_OUTPUT_TOKENS",
    )
    llm_max_response_bytes: int = Field(
        default=1_000_000,
        ge=1_024,
        alias="LLM_MAX_RESPONSE_BYTES",
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
