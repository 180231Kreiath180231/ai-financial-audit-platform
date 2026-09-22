from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator


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
    storage_available: bool = True
    storage_error_code: str | None = None
    external_access_enabled: bool = False


ProviderKind = Literal["fake", "openai_compatible"]
ModelCapability = Literal["text", "vision", "json_schema", "tools", "embedding", "file_upload"]


class ModelProviderCreate(BaseModel):
    provider_kind: ProviderKind = "openai_compatible"
    display_name: str = Field(min_length=2, max_length=80)
    base_url: str = Field(min_length=1, max_length=500)
    api_key: SecretStr | None = None
    default_headers: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=60, ge=1, le=300)
    max_retries: int = Field(default=1, ge=0, le=3)
    enabled: bool = True

    @field_validator("display_name", "base_url")
    @classmethod
    def strip_provider_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("default_headers")
    @classmethod
    def validate_headers(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 20:
            raise ValueError("默认请求头不能超过 20 项")
        normalized: dict[str, str] = {}
        for key, item in value.items():
            header = key.strip()
            if header.lower() in {"authorization", "proxy-authorization"}:
                raise ValueError("认证信息必须使用 API Key 字段保存")
            if not header or len(header) > 100 or len(item) > 500:
                raise ValueError("请求头名称或值超出长度限制")
            normalized[header] = item.strip()
        return normalized

    @model_validator(mode="after")
    def validate_provider(self):
        if self.provider_kind == "fake":
            if self.base_url != "local://fake":
                raise ValueError("Fake Provider 仅允许 local://fake")
            if self.api_key is not None:
                raise ValueError("Fake Provider 不应配置 API Key")
        else:
            parsed = urlsplit(self.base_url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("外部服务 Base URL 必须是无凭据、查询参数和片段的有效 HTTPS 地址")
        return self


class ModelProviderUpdate(ModelProviderCreate):
    api_key: SecretStr | None = None
    clear_api_key: bool = False

    @model_validator(mode="after")
    def validate_secret_update(self):
        if self.api_key is not None and self.clear_api_key:
            raise ValueError("不能同时轮换和清除 API Key")
        return self


class ModelProviderRecord(BaseModel):
    id: str
    provider_kind: ProviderKind
    display_name: str
    base_url: str
    secret_configured: bool
    default_headers: dict[str, str]
    timeout_seconds: int
    max_retries: int
    enabled: bool
    created_at: datetime
    updated_at: datetime


class ModelProfileCreate(BaseModel):
    provider_id: str
    display_name: str = Field(min_length=2, max_length=80)
    model_name: str = Field(min_length=1, max_length=160)
    capabilities: set[ModelCapability] = Field(min_length=1)
    context_window: int = Field(default=32768, ge=1024, le=10_000_000)
    max_output_tokens: int = Field(default=4096, ge=1, le=1_000_000)
    input_cost_per_million: Decimal = Field(default=Decimal("0"), ge=0)
    output_cost_per_million: Decimal = Field(default=Decimal("0"), ge=0)
    is_fallback: bool = False
    enabled: bool = True

    @field_validator("provider_id", "display_name", "model_name")
    @classmethod
    def strip_model_text(cls, value: str) -> str:
        return value.strip()


class ModelProfileUpdate(ModelProfileCreate):
    pass


class ModelProfileRecord(BaseModel):
    id: str
    provider_id: str
    display_name: str
    model_name: str
    capabilities: list[ModelCapability]
    context_window: int
    max_output_tokens: int
    input_cost_per_million: Decimal
    output_cost_per_million: Decimal
    is_fallback: bool
    enabled: bool
    created_at: datetime
    updated_at: datetime


class ExternalAccessUpdate(BaseModel):
    enabled: bool


class OfflineModeUpdate(BaseModel):
    strict_offline: bool


class ModelCallRecord(BaseModel):
    id: str
    project_id: str | None
    provider_id: str | None
    model_profile_id: str | None
    capability: ModelCapability
    started_at: datetime
    completed_at: datetime | None
    status: str
    error_code: str | None


class GatewayOverview(BaseModel):
    strict_offline: bool
    providers: list[ModelProviderRecord]
    models: list[ModelProfileRecord]
    recent_calls: list[ModelCallRecord]


class GatewayProbe(BaseModel):
    project_id: str
    capability: ModelCapability
    prompt: str = Field(default="synthetic gateway probe", min_length=1, max_length=500)


class GatewayProbeResult(BaseModel):
    call_id: str
    provider: str
    actual_model: str
    capability: ModelCapability
    output: str
    external_request: bool = False


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
