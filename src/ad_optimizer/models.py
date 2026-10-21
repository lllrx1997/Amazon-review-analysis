from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AnalysisRequest(BaseModel):
    asin: str = Field(pattern=r"^[A-Z0-9]{10}$")

    @field_validator("asin", mode="before")
    @classmethod
    def normalize_asin(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class Review(BaseModel):
    id: str
    requested_asin: str
    source_asin: str | None = None
    review_url: str | None = None
    rating: int = Field(ge=1, le=5)
    date_raw: str = ""
    date: str | None = None
    title_original: str = ""
    body_original: str
    title_zh: str = ""
    body_zh: str = ""
    analyzed: bool = False


class Evidence(BaseModel):
    review_id: str
    quote: str = Field(min_length=1)


class Finding(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(max_length=2000)
    evidence: list[Evidence] = Field(min_length=1)
    possible_cause: str | None = Field(default=None, max_length=1500)


class Topic(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    evidence: list[Evidence] = Field(min_length=1)


class Translation(BaseModel):
    review_id: str
    title_zh: str
    body_zh: str = Field(min_length=1)


class Extraction(BaseModel):
    translations: list[Translation]
    issues: list[Finding]
    praises: list[Finding]
    neutral_feedback: list[Finding]
    topics: list[Topic]
    usage_insights: list[Finding] = []


class Report(BaseModel):
    asin: str
    product_name: str | None = None
    product_url: str
    source: str = "Bright Data"
    scope: str = "unknown"
    latest_verified: bool = False
    limit_verified: bool = False
    collected_at: datetime = Field(default_factory=utcnow)
    generated_at: datetime = Field(default_factory=utcnow)
    model: str
    rule_version: str = "mvp-1"
    received_count: int = 0
    excluded_count: int = 0
    duplicate_count: int = 0
    capped_count: int = 0
    total: int = 0
    analyzed_count: int = 0
    analysis_incomplete: bool = False
    stars: dict[str, int] = Field(default_factory=lambda: {str(i): 0 for i in range(1, 6)})
    negative_percentage: float | None = None
    issues: list[Finding] = []
    praises: list[Finding] = []
    neutral_feedback: list[Finding] = []
    topics: list[Topic] = []
    usage_insights: list[Finding] = []
    reviews: list[Review] = []
    warnings: list[str] = []


class ErrorInfo(BaseModel):
    code: str
    message: str


class Task(BaseModel):
    id: str
    asin: str
    status: Literal["fetching", "analyzing", "completed", "partial", "failed"] = "fetching"
    stage_message: str = "正在获取评论"
    revision: int = 0
    completed_batches: int = 0
    total_batches: int = 0
    processed_reviews: int = 0
    timings: dict[str, float] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime | None = None
    result: Report | None = None
    error: ErrorInfo | None = None
