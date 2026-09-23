from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from .db import CAPABILITY_COLUMNS, Database, utc_now
from .openai_compatible import OpenAICompatibleAdapter, ProviderRequestError
from .paddleocr_aistudio import PaddleOcrAiStudioAdapter, PaddleOcrRequestError


def paddleocr_recovery_action(code: str) -> str:
    return {
        "OCR_CREDENTIAL_INVALID": "在设置中轮换 PaddleOCR Access Token 后重试",
        "OCR_BALANCE_INSUFFICIENT": "补充服务额度或更换已批准账户后重试",
        "OCR_PAGE_TOO_LARGE": "降低扫描页分辨率或压缩页面后重试",
        "OCR_PAGE_UNREADABLE": "确认本地临时页仍可读取后重新导入",
        "OCR_TASK_INTERRUPTED": "如仍需识别，请重新发起导入任务",
        "OCR_RESULT_URL_REJECTED": "联系管理员核验服务商返回的结果地址",
        "OCR_RESULT_URL_UNRESOLVED": "检查 DNS 与网络连接后重试",
    }.get(code, "检查 PaddleOCR 服务、令牌和网络后重试；原始页面仍保留在本机")


class GatewayError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        action: str,
        *,
        call_id: str | None = None,
        external_request: bool = False,
        remote_request_id: str | None = None,
        remote_cleanup_status: str = "not_applicable",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.action = action
        self.call_id = call_id
        self.external_request = external_request
        self.remote_request_id = remote_request_id
        self.remote_cleanup_status = remote_cleanup_status


@dataclass(frozen=True)
class Route:
    provider_id: str
    provider_name: str
    provider_kind: str
    model_profile_id: str
    model_name: str
    base_url: str
    api_key_ref: str | None
    default_headers_json: str
    timeout_seconds: int
    max_retries: int
    input_cost_per_million: str
    output_cost_per_million: str
    is_fallback: bool


class ModelGateway:
    """Capability router with an audited, deny-by-default external boundary."""

    def __init__(
        self,
        database: Database,
        adapter: OpenAICompatibleAdapter | None = None,
        paddleocr_adapter: PaddleOcrAiStudioAdapter | None = None,
    ) -> None:
        self.database = database
        self.adapter = adapter or OpenAICompatibleAdapter()
        self.paddleocr_adapter = paddleocr_adapter or PaddleOcrAiStudioAdapter()

    def route(
        self,
        project_id: str,
        capability: str,
        *,
        allow_fake: bool = False,
        provider_kind: str | None = None,
    ) -> Route:
        return self.routes(
            project_id,
            capability,
            allow_fake=allow_fake,
            provider_kind=provider_kind,
        )[0]

    def routes(
        self,
        project_id: str,
        capability: str,
        *,
        allow_fake: bool = False,
        provider_kind: str | None = None,
    ) -> list[Route]:
        column = CAPABILITY_COLUMNS.get(capability)
        if column is None:
            raise GatewayError(
                "MODEL_CAPABILITY_INVALID", "不支持的模型能力", "检查任务能力声明"
            )
        project = self.database.get_project(project_id)
        external_allowed = (
            not self.database.strict_offline() and project["external_access_enabled"]
        )
        if not allow_fake and self.database.strict_offline():
            raise GatewayError(
                "OFFLINE_MODE_BLOCKED",
                "严格离线模式已阻止外部模型请求",
                "保持离线，或在设置中关闭严格离线后再试",
            )
        if not allow_fake and not project["external_access_enabled"]:
            raise GatewayError(
                "PROJECT_EXTERNAL_ACCESS_REQUIRED",
                "当前项目未授权向外部模型发送证据",
                "在设置中明确启用该项目的外发权限",
            )
        with self.database.connect(self.database.registry_path) as db:
            rows = db.execute(
                f"""SELECT p.id provider_id, p.display_name provider_name,
                    p.provider_kind, p.base_url, p.api_key_ref, p.default_headers_json,
                    p.timeout_seconds, p.max_retries, m.id model_profile_id, m.model_name,
                    m.input_cost_per_million, m.output_cost_per_million,
                    m.is_fallback
                FROM model_profiles m
                JOIN model_providers p ON p.id=m.provider_id
                WHERE m.enabled=1 AND p.enabled=1 AND m.{column}=1
                ORDER BY CASE WHEN p.provider_kind='fake' THEN 1 ELSE 0 END,
                         m.is_fallback, m.created_at"""
            ).fetchall()
        routes: list[Route] = []
        for row in rows:
            if provider_kind is not None and row["provider_kind"] != provider_kind:
                continue
            if allow_fake and row["provider_kind"] == "fake":
                routes.append(Route(**{**dict(row), "is_fallback": bool(row["is_fallback"])}))
            if not allow_fake and row["provider_kind"] != "fake" and external_allowed:
                routes.append(Route(**{**dict(row), "is_fallback": bool(row["is_fallback"])}))
        if routes:
            if allow_fake:
                return routes
            primary = next((route for route in routes if not route.is_fallback), None)
            if primary is not None:
                return [primary, *(route for route in routes if route.is_fallback)]
        raise GatewayError(
            "MODEL_ROUTE_UNAVAILABLE",
            "没有启用且满足任务能力的模型",
            "配置相应能力的模型档案后重试",
        )

    def probe(self, project_id: str, capability: str, prompt: str) -> dict[str, Any]:
        call_id = str(uuid.uuid4())
        started_at = utc_now()
        started = time.perf_counter()
        summary = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        try:
            route = self.route(project_id, capability, allow_fake=True)
            if route.provider_kind != "fake":
                raise GatewayError(
                    "EXTERNAL_CONNECTOR_NOT_ENABLED",
                    "真实外部模型连接尚未启用",
                    "当前阶段仅使用 Fake Provider 验证安全路由",
                )
            output = f"FAKE_OK:{capability}:{summary[:12]}"
            self._record_call(
                call_id=call_id,
                project_id=project_id,
                capability=capability,
                request_summary=summary,
                route=route,
                started_at=started_at,
                started=started,
                status="completed",
            )
            return {
                "call_id": call_id,
                "provider": route.provider_name,
                "actual_model": route.model_name,
                "capability": capability,
                "output": output,
                "external_request": False,
            }
        except GatewayError as exc:
            self._record_call(
                call_id=call_id,
                project_id=project_id,
                capability=capability,
                request_summary=summary,
                route=None,
                started_at=started_at,
                started=started,
                status="blocked",
                error_code=exc.code,
            )
            raise

    def draft_fake_risk_explanation(
        self,
        project_id: str,
        *,
        summary: str,
        support_refs: list[str],
        counter_refs: list[str],
    ) -> dict[str, Any]:
        """Create a schema-shaped synthetic draft without making a network request."""
        call_id = str(uuid.uuid4())
        started_at = utc_now()
        started = time.perf_counter()
        prompt = json.dumps(
            {
                "schema_version": "risk-explanation.v1",
                "summary": summary,
                "support_refs": support_refs,
                "counter_refs": counter_refs,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        request_summary = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        try:
            route = self.route(project_id, "json_schema", allow_fake=True)
            if route.provider_kind != "fake":
                raise GatewayError(
                    "FAKE_PROVIDER_REQUIRED",
                    "合成解释只能使用 Fake Provider",
                    "保留并启用本地 Fake Provider",
                )
            explanation = (
                f"合成解释草稿：当前线索关联 {len(support_refs)} 条支持证据"
                f"和 {len(counter_refs)} 条反证。请逐页核对原文后再作人工判断。"
            )
            uncertainty = (
                "这是 Fake Provider 生成的结构化占位草稿；未执行正式财务规则、"
                "金额复算或真实模型推理，不构成审计结论。"
            )
            evidence_refs = [*support_refs, *counter_refs]
            self._record_call(
                call_id=call_id,
                project_id=project_id,
                capability="json_schema",
                request_summary=request_summary,
                route=route,
                started_at=started_at,
                started=started,
                status="completed",
                evidence_refs=evidence_refs,
            )
            return {
                "call_id": call_id,
                "provider": route.provider_name,
                "actual_model": route.model_name,
                "schema_version": "risk-explanation.v1",
                "explanation": explanation,
                "uncertainty": uncertainty,
                "external_request": False,
            }
        except GatewayError as exc:
            self._record_call(
                call_id=call_id,
                project_id=project_id,
                capability="json_schema",
                request_summary=request_summary,
                route=None,
                started_at=started_at,
                started=started,
                status="blocked",
                error_code=exc.code,
                evidence_refs=[*support_refs, *counter_refs],
            )
            raise

    def analyze_fake_vision_page(
        self,
        project_id: str,
        *,
        task_id: str,
        document_name: str,
        page_number: int,
        image_sha256: str,
        width: int,
        height: int,
    ) -> dict[str, Any]:
        """Return an explicitly synthetic page result without transmitting image bytes."""
        call_id = str(uuid.uuid4())
        started_at = utc_now()
        started = time.perf_counter()
        request = {
            "schema_version": "vision-page.v1",
            "document_name": document_name,
            "page_number": page_number,
            "image_sha256": image_sha256,
            "width": width,
            "height": height,
        }
        request_summary = hashlib.sha256(
            json.dumps(request, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        evidence_refs = [f"page:{page_number}:image:{image_sha256}"]
        try:
            route = self.route(project_id, "vision", allow_fake=True)
            if route.provider_kind != "fake":
                raise GatewayError(
                    "FAKE_PROVIDER_REQUIRED",
                    "合成扫描页只能使用 Fake Provider",
                    "保留并启用本地 Fake Provider",
                )
            recognized_text = (
                f"合成扫描页 {page_number}：Fake Vision 已验证页级定位；"
                "未识别或生成真实业务内容。"
            )
            result = {
                "schema_version": "vision-page.v1",
                "page_number": page_number,
                "document_type": "合成扫描件",
                "year": None,
                "entity_name": None,
                "recognized_text": recognized_text,
                "confidence": 0.0,
                "regions": [],
                "synthetic": True,
            }
            self._record_call(
                call_id=call_id,
                project_id=project_id,
                task_id=task_id,
                capability="vision",
                request_summary=request_summary,
                route=route,
                started_at=started_at,
                started=started,
                status="completed",
                evidence_refs=evidence_refs,
            )
            return {
                "call_id": call_id,
                "provider_id": route.provider_id,
                "provider": route.provider_name,
                "model_profile_id": route.model_profile_id,
                "actual_model": route.model_name,
                "external_request": False,
                "result": result,
            }
        except GatewayError as exc:
            self._record_call(
                call_id=call_id,
                project_id=project_id,
                task_id=task_id,
                capability="vision",
                request_summary=request_summary,
                route=None,
                started_at=started_at,
                started=started,
                status="blocked",
                error_code=exc.code,
                evidence_refs=evidence_refs,
            )
            raise

    def analyze_paddleocr_page(
        self,
        project_id: str,
        *,
        task_id: str,
        document_name: str,
        page_number: int,
        image_path: Path,
        image_sha256: str,
        width: int,
        height: int,
        should_continue: Callable[[], bool],
    ) -> dict[str, Any]:
        """Submit one synthetic page to the approved PaddleOCR Jobs API."""
        call_id = str(uuid.uuid4())
        started_at = utc_now()
        started = time.perf_counter()
        data_scope = {
            "whole_document": False,
            "content_type": "image/png",
            "page_number": page_number,
            "image_sha256": image_sha256,
            "width": width,
            "height": height,
            "document_name_sha256": hashlib.sha256(
                document_name.encode("utf-8")
            ).hexdigest(),
        }
        request_summary = hashlib.sha256(
            json.dumps(data_scope, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        evidence_refs = [f"page:{page_number}:image:{image_sha256}"]
        route: Route | None = None
        try:
            project = self.database.get_project(project_id)
            if not project["is_synthetic"]:
                raise GatewayError(
                    "OCR_REMOTE_RETENTION_UNVERIFIED",
                    "PaddleOCR 远端保留与删除政策尚未验证，真实审计资料外发已阻止",
                    "仅使用合成项目联调，或完成服务商数据保留专项审批",
                )
            route = self.route(
                project_id,
                "vision",
                provider_kind="paddleocr_aistudio",
            )
            if not route.api_key_ref:
                raise GatewayError(
                    "OCR_CREDENTIAL_REQUIRED",
                    "PaddleOCR 尚未配置 Access Token",
                    "在设置中添加或轮换 PaddleOCR Access Token",
                )
            result = self.paddleocr_adapter.analyze_page(
                job_url=route.base_url,
                access_token=self.database.secret_store.get(route.api_key_ref),
                default_headers=json.loads(route.default_headers_json),
                model_name=route.model_name,
                page_path=image_path,
                timeout_seconds=route.timeout_seconds,
                max_retries=route.max_retries,
                should_continue=should_continue,
            )
            schema_result = {
                "schema_version": "vision-page.v1",
                "page_number": page_number,
                "document_type": None,
                "year": None,
                "entity_name": None,
                "recognized_text": result.recognized_text,
                "confidence": None,
                "regions": [],
                "synthetic_input": True,
                "remote_cleanup_status": result.remote_cleanup_status,
            }
            self._record_call(
                call_id=call_id,
                project_id=project_id,
                task_id=task_id,
                capability="vision",
                request_summary=request_summary,
                route=route,
                started_at=started_at,
                started=started,
                status="completed",
                evidence_refs=evidence_refs,
                retry_count=result.retry_count,
                remote_request_id=result.job_id,
                remote_cleanup_status=result.remote_cleanup_status,
                data_scope=data_scope,
            )
            return {
                "call_id": call_id,
                "provider_id": route.provider_id,
                "provider": route.provider_name,
                "model_profile_id": route.model_profile_id,
                "actual_model": route.model_name,
                "external_request": True,
                "remote_request_id": result.job_id,
                "remote_cleanup_status": result.remote_cleanup_status,
                "result": schema_result,
            }
        except PaddleOcrRequestError as exc:
            self._record_call(
                call_id=call_id,
                project_id=project_id,
                task_id=task_id,
                capability="vision",
                request_summary=request_summary,
                route=route,
                started_at=started_at,
                started=started,
                status="cancelled" if exc.code == "OCR_TASK_INTERRUPTED" else "failed",
                error_code=exc.code,
                evidence_refs=evidence_refs,
                retry_count=exc.retry_count,
                remote_request_id=exc.remote_request_id,
                remote_cleanup_status=exc.remote_cleanup_status,
                data_scope=data_scope,
            )
            raise GatewayError(
                exc.code,
                exc.message,
                paddleocr_recovery_action(exc.code),
                call_id=call_id,
                external_request=exc.external_request,
                remote_request_id=exc.remote_request_id,
                remote_cleanup_status=exc.remote_cleanup_status,
            ) from exc
        except GatewayError as exc:
            self._record_call(
                call_id=call_id,
                project_id=project_id,
                task_id=task_id,
                capability="vision",
                request_summary=request_summary,
                route=route,
                started_at=started_at,
                started=started,
                status="blocked",
                error_code=exc.code,
                evidence_refs=evidence_refs,
                data_scope=data_scope,
            )
            raise GatewayError(
                exc.code,
                exc.message,
                exc.action,
                call_id=call_id,
                external_request=exc.external_request,
                remote_request_id=exc.remote_request_id,
                remote_cleanup_status=exc.remote_cleanup_status,
            ) from exc

    def complete_external(
        self,
        project_id: str,
        capability: str,
        prompt: str,
        *,
        evidence_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        summary = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        evidence_refs = evidence_refs or []
        evidence_hash = hashlib.sha256(
            json.dumps(sorted(evidence_refs), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        try:
            routes = self.routes(project_id, capability)
        except GatewayError as exc:
            call_id = str(uuid.uuid4())
            started_at = utc_now()
            started = time.perf_counter()
            self._record_call(
                call_id=call_id,
                project_id=project_id,
                capability=capability,
                request_summary=summary,
                route=None,
                started_at=started_at,
                started=started,
                status="blocked",
                error_code=exc.code,
                evidence_refs=evidence_refs,
            )
            raise

        primary_model_id = routes[0].model_profile_id
        last_error: ProviderRequestError | None = None
        failover_codes = {"MODEL_TIMEOUT", "MODEL_RATE_LIMITED", "MODEL_SERVICE_UNAVAILABLE"}
        for index, route in enumerate(routes):
            call_id = str(uuid.uuid4())
            started_at = utc_now()
            started = time.perf_counter()
            route_role = "fallback" if index > 0 or route.is_fallback else "primary"
            fallback_from = primary_model_id if route_role == "fallback" else None
            fingerprint = self._cache_fingerprint(
                project_id=project_id,
                capability=capability,
                route=route,
                prompt_hash=summary,
                evidence_hash=evidence_hash,
            )
            if self.database.model_cache_enabled():
                cached = self.database.get_model_cache(fingerprint)
                if cached is not None:
                    self._record_call(
                        call_id=call_id,
                        project_id=project_id,
                        capability=capability,
                        request_summary=summary,
                        route=route,
                        started_at=started_at,
                        started=started,
                        status="completed",
                        evidence_refs=evidence_refs,
                        input_tokens=int(cached["input_tokens"]),
                        output_tokens=int(cached["output_tokens"]),
                        cache_hit=True,
                        route_role=route_role,
                        fallback_from_model_profile_id=fallback_from,
                    )
                    return {
                        "call_id": call_id,
                        "provider": route.provider_name,
                        "actual_model": route.model_name,
                        "content": cached["content"],
                        "input_tokens": int(cached["input_tokens"]),
                        "output_tokens": int(cached["output_tokens"]),
                        "estimated_cost": "0",
                        "cache_hit": True,
                        "fallback_used": route_role == "fallback",
                    }
            try:
                if route.provider_kind != "openai_compatible":
                    raise GatewayError(
                        "MODEL_PROVIDER_UNSUPPORTED",
                        "当前服务商类型不受支持",
                        "选择 OpenAI-compatible 服务商",
                    )
                if not route.api_key_ref:
                    raise GatewayError(
                        "MODEL_CREDENTIAL_REQUIRED",
                        "模型服务商尚未配置 API Key",
                        "在设置中轮换或添加 API Key",
                    )
                result = self.adapter.complete(
                    base_url=route.base_url,
                    api_key=self.database.secret_store.get(route.api_key_ref),
                    default_headers=json.loads(route.default_headers_json),
                    model_name=route.model_name,
                    prompt=prompt,
                    timeout_seconds=route.timeout_seconds,
                    max_retries=route.max_retries,
                )
                estimated_cost = (
                    Decimal(result.input_tokens) * Decimal(route.input_cost_per_million)
                    + Decimal(result.output_tokens) * Decimal(route.output_cost_per_million)
                ) / Decimal(1_000_000)
                response = {
                    "content": result.content,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                }
                if self.database.model_cache_enabled():
                    self.database.put_model_cache(
                        project_id=project_id,
                        model_profile_id=route.model_profile_id,
                        capability=capability,
                        request_fingerprint=fingerprint,
                        prompt_hash=summary,
                        evidence_hash=evidence_hash,
                        response=response,
                    )
                self._record_call(
                    call_id=call_id,
                    project_id=project_id,
                    capability=capability,
                    request_summary=summary,
                    route=route,
                    started_at=started_at,
                    started=started,
                    status="completed",
                    evidence_refs=evidence_refs,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    retry_count=result.retry_count,
                    estimated_cost=str(estimated_cost),
                    route_role=route_role,
                    fallback_from_model_profile_id=fallback_from,
                )
                return {
                    "call_id": call_id,
                    "provider": route.provider_name,
                    "actual_model": route.model_name,
                    **response,
                    "estimated_cost": str(estimated_cost),
                    "cache_hit": False,
                    "fallback_used": route_role == "fallback",
                }
            except ProviderRequestError as exc:
                last_error = exc
                self._record_call(
                    call_id=call_id,
                    project_id=project_id,
                    capability=capability,
                    request_summary=summary,
                    route=route,
                    started_at=started_at,
                    started=started,
                    status="failed",
                    error_code=exc.code,
                    evidence_refs=evidence_refs,
                    retry_count=exc.retry_count,
                    route_role=route_role,
                    fallback_from_model_profile_id=fallback_from,
                )
                if exc.code in failover_codes and index < len(routes) - 1:
                    continue
                raise GatewayError(
                    exc.code, exc.message, "检查服务商状态和模型配置后重试"
                ) from exc
            except GatewayError as exc:
                self._record_call(
                    call_id=call_id,
                    project_id=project_id,
                    capability=capability,
                    request_summary=summary,
                    route=route,
                    started_at=started_at,
                    started=started,
                    status="blocked",
                    error_code=exc.code,
                    evidence_refs=evidence_refs,
                    route_role=route_role,
                    fallback_from_model_profile_id=fallback_from,
                )
                raise

        assert last_error is not None
        raise GatewayError(
            last_error.code, last_error.message, "检查服务商状态和模型配置后重试"
        )

    @staticmethod
    def _cache_fingerprint(
        *,
        project_id: str,
        capability: str,
        route: Route,
        prompt_hash: str,
        evidence_hash: str,
    ) -> str:
        canonical = json.dumps(
            {
                "project_id": project_id,
                "capability": capability,
                "provider_id": route.provider_id,
                "base_url": route.base_url,
                "api_key_ref": route.api_key_ref,
                "default_headers": route.default_headers_json,
                "model_profile_id": route.model_profile_id,
                "model_name": route.model_name,
                "prompt_hash": prompt_hash,
                "evidence_hash": evidence_hash,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _record_call(
        self,
        *,
        call_id: str,
        project_id: str,
        task_id: str | None = None,
        capability: str,
        request_summary: str,
        route: Route | None,
        started_at: str,
        started: float,
        status: str,
        error_code: str | None = None,
        evidence_refs: list[str] | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        retry_count: int = 0,
        estimated_cost: str = "0",
        cache_hit: bool = False,
        route_role: str = "primary",
        fallback_from_model_profile_id: str | None = None,
        remote_request_id: str | None = None,
        remote_cleanup_status: str = "not_applicable",
        data_scope: dict[str, Any] | None = None,
    ) -> None:
        duration_ms = round((time.perf_counter() - started) * 1000)
        with self.database.connect(self.database.registry_path) as db:
            db.execute(
                """INSERT INTO model_calls
                (id, project_id, task_id, provider_id, model_profile_id, capability, started_at,
                 completed_at, duration_ms, evidence_refs_json, request_summary,
                 input_tokens, output_tokens, estimated_cost, cache_hit, retry_count, status,
                 error_code, route_role, fallback_from_model_profile_id, remote_request_id,
                 remote_cleanup_status, data_scope_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    call_id,
                    project_id,
                    task_id,
                    route.provider_id if route else None,
                    route.model_profile_id if route else None,
                    capability,
                    started_at,
                    utc_now(),
                    duration_ms,
                    json.dumps(evidence_refs or []),
                    request_summary,
                    input_tokens,
                    output_tokens,
                    estimated_cost,
                    int(cache_hit),
                    retry_count,
                    status,
                    error_code,
                    route_role,
                    fallback_from_model_profile_id,
                    remote_request_id,
                    remote_cleanup_status,
                    json.dumps(data_scope or {}, ensure_ascii=False, sort_keys=True),
                ),
            )
