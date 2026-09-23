from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator

from .paddleocr_aistudio import PADDLEOCR_JOB_URL


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


ProviderKind = Literal["fake", "openai_compatible", "paddleocr_aistudio"]
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
            if (
                self.provider_kind == "paddleocr_aistudio"
                and self.base_url.rstrip("/") != PADDLEOCR_JOB_URL
            ):
                raise ValueError("PaddleOCR AI Studio 仅允许使用已批准的 Jobs Endpoint")
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


class ModelCacheUpdate(BaseModel):
    enabled: bool


class ModelCacheClearResult(BaseModel):
    deleted_entries: int


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
    cache_hit: bool = False
    route_role: Literal["primary", "fallback"] = "primary"
    fallback_from_model_profile_id: str | None = None


class GatewayOverview(BaseModel):
    strict_offline: bool
    cache_enabled: bool
    cache_entry_count: int
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


EvidenceDirection = Literal["support", "counter"]
RiskLevel = Literal["高", "中", "低", "待评估"]
RiskStatus = Literal["待复核", "已核实", "已排除", "待补证", "已关闭"]


class RiskEvidenceCreate(BaseModel):
    document_id: str = Field(min_length=1, max_length=80)
    page_number: int = Field(ge=1)
    block_number: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=320)
    direction: EvidenceDirection

    @field_validator("quote", mode="before")
    @classmethod
    def strip_evidence_quote(cls, value: str) -> str:
        return value.strip()


class RiskCreate(BaseModel):
    risk_type: str = Field(default="人工线索", min_length=2, max_length=80)
    summary: str = Field(min_length=5, max_length=500)
    evidence: list[RiskEvidenceCreate] = Field(min_length=1, max_length=20)

    @field_validator("risk_type", "summary", mode="before")
    @classmethod
    def strip_risk_text(cls, value: str) -> str:
        return value.strip()


class RiskTransition(BaseModel):
    status: RiskStatus
    note: str = Field(min_length=2, max_length=500)

    @field_validator("note", mode="before")
    @classmethod
    def strip_transition_note(cls, value: str) -> str:
        return value.strip()


class RiskEvidenceRecord(BaseModel):
    id: str
    kind: Literal["document", "financial"] = "document"
    document_id: str | None = None
    document_name: str
    page_number: int | None = None
    block_number: int | None = None
    dataset_id: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    period_key: str | None = None
    account_code: str | None = None
    quote: str
    direction: EvidenceDirection
    parse_method: str | None = None
    parse_version: str | None = None


class RiskVersionRecord(BaseModel):
    version: int
    change_reason: str
    created_at: datetime
    snapshot: dict


class RiskRecord(BaseModel):
    id: str
    risk_number: str
    risk_type: str
    risk_level: RiskLevel
    status: RiskStatus
    summary: str
    trigger_rule_id: str
    trigger_rule_version: str
    input_values: dict
    baseline_values: dict
    calculation_result: dict
    model_explanation: str | None
    uncertainty: str
    human_opinion: str
    model_provider: str | None
    actual_model: str | None
    model_call_id: str | None
    version: int
    created_at: datetime
    updated_at: datetime
    evidence: list[RiskEvidenceRecord] = Field(default_factory=list)
    versions: list[RiskVersionRecord] = Field(default_factory=list)


class FakeRiskDraftResult(BaseModel):
    risk: RiskRecord
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
    task_type: str
    filename: str
    status: TaskStatus
    progress: int
    current_step: str
    error_code: str | None = None
    error_message: str | None = None
    next_action: str | None = None
    result_kind: str | None = None
    document_id: str | None = None
    dataset_id: str | None = None
    created_at: datetime
    updated_at: datetime


class DemoLoadResult(BaseModel):
    queued_task_ids: list[str]
    queued_task_count: int
    reused_document_count: int
    reused_task_count: int
    reused_financial_dataset: bool
    message: str
    external_request: bool = False


class DocumentRecord(BaseModel):
    id: str
    filename: str
    sha256: str
    size_bytes: int
    page_count: int
    parse_method: str
    parse_version: str
    created_at: datetime
    native_page_count: int = 0
    scan_page_count: int = 0
    vision_page_count: int = 0
    external_vision_page_count: int = 0
    vision_status: Literal["not_required", "completed", "requires_vision", "failed"] = (
        "not_required"
    )
    fiscal_year: int | None = None
    entity_name: str | None = None
    document_type: str | None = None
    account_names: list[str] = Field(default_factory=list)
    metadata_version: int = 0
    metadata_updated_at: datetime | None = None


class DocumentMetadataUpdate(BaseModel):
    fiscal_year: int | None = Field(default=None, ge=2000, le=2100)
    entity_name: str | None = Field(default=None, max_length=120)
    document_type: str | None = Field(default=None, max_length=80)
    account_names: list[str] = Field(default_factory=list, max_length=20)
    change_reason: str = Field(default="人工更新文档元数据", min_length=2, max_length=200)

    @field_validator("entity_name", "document_type", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("account_names", mode="before")
    @classmethod
    def normalize_accounts(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in value:
            account = item.strip()
            if len(account) > 80:
                raise ValueError("科目名称不能超过 80 个字符")
            if account and account not in normalized:
                normalized.append(account)
        return normalized

    @field_validator("change_reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        return value.strip()


class DocumentSearchHit(BaseModel):
    chunk_id: str | None = None
    document_id: str
    document_name: str
    page_number: int
    block_number: int
    parse_method: str
    parse_version: str
    snippet: str
    match_kind: Literal["content", "filename", "metadata", "semantic"]
    fiscal_year: int | None = None
    entity_name: str | None = None
    document_type: str | None = None
    account_names: list[str] = Field(default_factory=list)


class RetrievalStatus(BaseModel):
    chunk_version: str
    chunk_state: Literal["empty", "ready", "stale"]
    chunk_count: int
    chunked_page_count: int
    source_page_count: int
    keyword_state: Literal["empty", "ready"]
    vector_state: Literal["not_configured", "building", "ready", "stale", "failed"]
    vector_backend: Literal["sqlite_vec", "memory_cosine"] | None = None
    model_profile_id: str | None = None
    actual_model: str | None = None
    dimension: int | None = None
    indexed_chunk_count: int = 0
    external_request: bool = False
    message: str
    action: str


class PageVisionRecord(BaseModel):
    page_number: int
    status: Literal["not_required", "completed", "requires_vision", "failed"]
    provider_name: str | None = None
    actual_model: str | None = None
    model_call_id: str | None = None
    schema_version: str
    confidence: float | None = None
    image_sha256: str | None = None
    external_request: bool = False
    remote_request_id: str | None = None
    remote_cleanup_status: Literal["not_applicable", "unsupported", "unknown"] = (
        "not_applicable"
    )
    error_code: str | None = None
    error_message: str | None = None
    parse_method: str
    parse_version: str


class UploadResult(BaseModel):
    accepted: list[TaskRecord]
    rejected: list[ApiError]


class FinancialPreviewIssue(BaseModel):
    code: str
    message: str
    action: str
    line_number: int | None = None
    field: str | None = None


class FinancialPreview(BaseModel):
    preview_id: str | None
    duplicate_dataset_id: str | None
    valid: bool
    encoding: str
    size_bytes: int
    row_count: int
    currency: str
    amount_unit: str
    period_type: Literal["monthly", "annual"]
    period_start: str
    period_end: str
    extra_columns: list[str]
    warnings: list[FinancialPreviewIssue]
    errors: list[FinancialPreviewIssue]
    sample_rows: list[dict[str, str]]


class FinancialPreviewConfirm(BaseModel):
    preview_id: str = Field(min_length=1, max_length=80)


class FinancialConfirmResult(BaseModel):
    reused_dataset_id: str | None = None
    task: TaskRecord | None = None


RuleResultStatus = Literal["pass", "fail", "unavailable"]


class FinancialRuleResult(BaseModel):
    id: str
    rule_id: str
    rule_version: str
    period_key: str
    status: RuleResultStatus
    summary: str
    input_values: dict
    baseline_values: dict
    calculation_result: dict
    scope: dict
    affected_count: int
    line_start: int | None = None
    line_end: int | None = None
    created_at: datetime


class FinancialDataset(BaseModel):
    id: str
    filename: str
    sha256: str
    size_bytes: int
    encoding: str
    period_type: Literal["monthly", "annual"]
    period_start: str
    period_end: str
    row_count: int
    currency: str
    amount_unit: str
    status: Literal["active", "archived"]
    created_at: datetime
    archived_at: datetime | None = None
    rule_run_id: str | None = None
    rule_set_version: str | None = None
    rule_run_status: str | None = None
    passed_count: int | None = None
    failed_count: int | None = None
    unavailable_count: int | None = None
    completed_at: datetime | None = None
    import_warnings: list[FinancialPreviewIssue] = Field(default_factory=list)
    rule_results: list[FinancialRuleResult] = Field(default_factory=list)


class FinancialResultRow(BaseModel):
    line_number: int
    year: int
    period: str
    account_code: str
    account_name: str
    opening_debit: str
    opening_credit: str
    period_debit: str
    period_credit: str
    closing_debit: str
    closing_credit: str
    currency: str
    reason: str


class FinancialResultRows(BaseModel):
    total: int
    offset: int
    limit: int
    rows: list[FinancialResultRow]


class FinancialRuleRunReuse(BaseModel):
    reused: bool = True
    run_id: str
    rule_set_version: str
    message: str


class ResourceSnapshot(BaseModel):
    cpu_percent: float
    memory_percent: float
    disk_free_gb: float
    worker_limit: int = 1
    external_api_enabled: bool = False
