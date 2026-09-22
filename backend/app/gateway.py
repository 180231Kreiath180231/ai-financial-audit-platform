from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .db import CAPABILITY_COLUMNS, Database, utc_now
from .openai_compatible import OpenAICompatibleAdapter, ProviderRequestError


class GatewayError(RuntimeError):
    def __init__(self, code: str, message: str, action: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.action = action


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


class ModelGateway:
    """Capability router with an audited, deny-by-default external boundary."""

    def __init__(
        self, database: Database, adapter: OpenAICompatibleAdapter | None = None
    ) -> None:
        self.database = database
        self.adapter = adapter or OpenAICompatibleAdapter()

    def route(self, project_id: str, capability: str, *, allow_fake: bool = False) -> Route:
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
                    m.input_cost_per_million, m.output_cost_per_million
                FROM model_profiles m
                JOIN model_providers p ON p.id=m.provider_id
                WHERE m.enabled=1 AND p.enabled=1 AND m.{column}=1
                ORDER BY CASE WHEN p.provider_kind='fake' THEN 1 ELSE 0 END,
                         m.is_fallback, m.created_at"""
            ).fetchall()
        for row in rows:
            if allow_fake and row["provider_kind"] == "fake":
                return Route(**dict(row))
            if not allow_fake and row["provider_kind"] != "fake" and external_allowed:
                return Route(**dict(row))
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

    def complete_external(
        self,
        project_id: str,
        capability: str,
        prompt: str,
        *,
        evidence_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        call_id = str(uuid.uuid4())
        started_at = utc_now()
        started = time.perf_counter()
        summary = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        route: Route | None = None
        try:
            route = self.route(project_id, capability)
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
            )
            return {
                "call_id": call_id,
                "provider": route.provider_name,
                "actual_model": route.model_name,
                "content": result.content,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "estimated_cost": str(estimated_cost),
            }
        except ProviderRequestError as exc:
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
            )
            raise GatewayError(exc.code, exc.message, "检查服务商状态和模型配置后重试") from exc
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
            )
            raise

    def _record_call(
        self,
        *,
        call_id: str,
        project_id: str,
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
    ) -> None:
        duration_ms = round((time.perf_counter() - started) * 1000)
        with self.database.connect(self.database.registry_path) as db:
            db.execute(
                """INSERT INTO model_calls
                (id, project_id, provider_id, model_profile_id, capability, started_at,
                 completed_at, duration_ms, evidence_refs_json, request_summary,
                 input_tokens, output_tokens, estimated_cost, retry_count, status, error_code)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    call_id,
                    project_id,
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
                    retry_count,
                    status,
                    error_code,
                ),
            )
