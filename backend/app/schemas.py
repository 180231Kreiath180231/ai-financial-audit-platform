from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ApiError(BaseModel):
    code: str
    message: str
    action: str


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    entity_name: str = Field(min_length=2, max_length=120)
    year_start: int = Field(ge=2000, le=2100)
    year_end: int = Field(ge=2000, le=2100)
    storage_path: str = Field(min_length=3, max_length=500)
    model_profile: str = Field(default="严格离线 / Fake Provider", max_length=80)

    @field_validator("name", "entity_name", "storage_path")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("year_end")
    @classmethod
    def validate_range(cls, value: int, info):
        start = info.data.get("year_start")
        if start and value < start:
            raise ValueError("结束年度不能早于开始年度")
        return value


class ProjectSummary(BaseModel):
    id: str
    name: str
    entity_name: str
    year_start: int
    year_end: int
    storage_path: str
    model_profile: str
    is_synthetic: bool
    created_at: datetime
    document_count: int = 0
    page_count: int = 0
    queued_count: int = 0
    running_count: int = 0
    failed_count: int = 0
    completed_count: int = 0


TaskStatus = Literal[
    "queued",
    "running",
    "pausing",
    "paused",
    "retry_wait",
    "failed",
    "completed",
    "cancelled",
]


class TaskRecord(BaseModel):
    id: str
    filename: str
    status: TaskStatus
    progress: int
    current_step: str
    error_code: str | None = None
    error_message: str | None = None
    next_action: str | None = None
    result_kind: str | None = None
    document_id: str | None = None
    created_at: datetime
    updated_at: datetime


class DocumentRecord(BaseModel):
    id: str
    filename: str
    sha256: str
    size_bytes: int
    page_count: int
    parse_method: str
    parse_version: str
    created_at: datetime


class UploadResult(BaseModel):
    accepted: list[TaskRecord]
    rejected: list[ApiError]


class ResourceSnapshot(BaseModel):
    cpu_percent: float
    memory_percent: float
    disk_free_gb: float
    worker_limit: int = 1
    external_api_enabled: bool = False
