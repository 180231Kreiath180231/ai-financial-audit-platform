from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

from .db import CAPABILITY_COLUMNS, Database, utc_now


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


class ModelGateway:
    """Capability router with an audited, deny-by-default external boundary."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def route(self, project_id: str, capability: str) -> Route:
        column = CAPABILITY_COLUMNS.get(capability)
        if column is None:
            raise GatewayError(
                "MODEL_CAPABILITY_INVALID", "不支持的模型能力", "检查任务能力声明"
            )
        project = self.database.get_project(project_id)
        external_allowed = (
            not self.database.strict_offline() and project["external_access_enabled"]
        )
        with self.database.connect(self.database.registry_path) as db:
            rows = db.execute(
                f"""SELECT p.id provider_id, p.display_name provider_name,
                    p.provider_kind, m.id model_profile_id, m.model_name
                FROM model_profiles m
                JOIN model_providers p ON p.id=m.provider_id
                WHERE m.enabled=1 AND p.enabled=1 AND m.{column}=1
                ORDER BY CASE WHEN p.provider_kind='fake' THEN 0 ELSE 1 END,
                         m.is_fallback, m.created_at"""
            ).fetchall()
        for row in rows:
            if row["provider_kind"] == "fake" or external_allowed:
                return Route(**dict(row))
        if self.database.strict_offline():
            raise GatewayError(
                "OFFLINE_MODE_BLOCKED",
                "严格离线模式已阻止外部模型请求",
                "保持离线，或在设置中关闭严格离线后再试",
            )
        if not project["external_access_enabled"]:
            raise GatewayError(
                "PROJECT_EXTERNAL_ACCESS_REQUIRED",
                "当前项目未授权向外部模型发送证据",
                "在设置中明确启用该项目的外发权限",
            )
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
            route = self.route(project_id, capability)
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
    ) -> None:
        duration_ms = round((time.perf_counter() - started) * 1000)
        with self.database.connect(self.database.registry_path) as db:
            db.execute(
                """INSERT INTO model_calls
                (id, project_id, provider_id, model_profile_id, capability, started_at,
                 completed_at, duration_ms, evidence_refs_json, request_summary,
                 status, error_code)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    call_id,
                    project_id,
                    route.provider_id if route else None,
                    route.model_profile_id if route else None,
                    capability,
                    started_at,
                    utc_now(),
                    duration_ms,
                    json.dumps([]),
                    request_summary,
                    status,
                    error_code,
                ),
            )
