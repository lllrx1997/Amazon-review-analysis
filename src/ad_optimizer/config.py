import json
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    bright_data_api_key: str = ""
    bright_data_dataset_id: str = ""
    bright_data_input_json: str = '{"numOfReviews":100}'
    bright_data_query_json: str = "{}"
    bright_data_latest_verified: bool = False
    bright_data_limit_verified: bool = False
    bright_data_scope: Literal["unknown", "parent_page", "child_only", "mixed"] = "unknown"
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-flash"
    llm_api_key: str = ""
    max_reviews: int = Field(default=100, ge=1, le=10000)
    max_active_analyses: int = Field(default=1, ge=1, le=20)
    result_ttl_seconds: int = Field(default=7200, ge=60)
    task_timeout_seconds: int = Field(default=1200, ge=10)
    provider_poll_seconds: float = Field(default=5, ge=0.1)
    llm_batch_characters: int = Field(default=12000, ge=1000)
    llm_max_tokens: int = Field(default=8192, ge=1024)
    llm_concurrency: int = Field(default=3, ge=1, le=8)
    llm_max_attempts: int = Field(default=2, ge=1, le=3)
    llm_timeout_seconds: int = Field(default=90, ge=10, le=300)
    allowed_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    @field_validator("bright_data_input_json", "bright_data_query_json")
    @classmethod
    def validate_object(cls, value: str) -> str:
        if not isinstance(json.loads(value), dict):
            raise ValueError("Must be a JSON object")
        return value

    def missing(self) -> list[str]:
        return [name for name in ("bright_data_api_key", "bright_data_dataset_id", "llm_api_key", "llm_model") if not getattr(self, name).strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
