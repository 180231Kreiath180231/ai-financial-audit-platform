from __future__ import annotations

import asyncio
import codecs
import csv
import io
import logging
import shutil
import sqlite3
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import psutil
from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.responses import Response as FastAPIResponse

from .assistant import AssistantError, AssistantService
from .config import load_settings
from .db import Database, ProjectStorageUnavailable, utc_now
from .demo_data import DemoDataError, DemoDataService
from .documents import (
    DocumentCorrectionError,
    correct_page_text,
    decode_document_row,
    get_page_content,
    update_document_metadata,
)
from .financial_data import (
    MAX_CSV_BYTES,
    REQUIRED_COLUMNS,
    FinancialDataError,
    FinancialDataService,
    sha256_file,
)
from .gateway import GatewayError, ModelGateway
from .logging_config import configure_logging
from .notes import AuditNoteRepository, NoteError
from .outputs import OutputDraftService, OutputError, OutputExportService, OutputSnapshotService
from .retrieval import retrieval_status
from .risks import RiskError, RiskRepository
from .schemas import (
    ApiError,
    AssistantMessageCreate,
    AssistantThreadCreate,
    AssistantThreadRecord,
    AssistantThreadUpdate,
    AuditNotePayload,
    AuditNoteRecord,
    DemoLoadResult,
    DocumentMetadataUpdate,
    DocumentRecord,
    DocumentSearchHit,
    ExternalAccessUpdate,
    FakeRiskDraftResult,
    FinancialConfirmResult,
    FinancialDataset,
    FinancialPreview,
    FinancialPreviewConfirm,
    FinancialResultRows,
    FinancialRuleRunReuse,
    FinancialTrendAccount,
    FinancialTrendAnalysis,
    GatewayOverview,
    GatewayProbe,
    GatewayProbeResult,
    ModelCacheClearResult,
    ModelCacheUpdate,
    ModelProfileCreate,
    ModelProfileRecord,
    ModelProfileUpdate,
    ModelProviderCreate,
    ModelProviderRecord,
    ModelProviderUpdate,
    OfflineModeUpdate,
    OutputDraftRecord,
    OutputDraftUpdate,
    OutputExportRecord,
    OutputSnapshotDetail,
    OutputSnapshotSummary,
    PageContentRecord,
    PageTextCorrectionCreate,
    PageTextCorrectionRecord,
    PageVisionRecord,
    ProjectCreate,
    ProjectSummary,
    ResourceSnapshot,
    RetrievalStatus,
    RiskCreate,
    RiskReassessment,
    RiskRecord,
    RiskTransition,
    TaskRecord,
    UploadResult,
)
from .search import search_project_pages
from .security import SESSION_COOKIE, LocalSessionGuard
from .synthetic_vectors import (
    SyntheticVectorError,
    build_synthetic_vector_index,
    require_synthetic_project,
    search_synthetic_hybrid,
)
from .worker import LocalTaskWorker

settings = load_settings()
configure_logging(settings.log_level)
logger = logging.getLogger("hengjian.api")
database = Database(settings.data_dir)
session_guard = LocalSessionGuard()
worker = LocalTaskWorker(database)
model_gateway = ModelGateway(database)
assistant_service = AssistantService(database, model_gateway)
risk_repository = RiskRepository(database)
note_repository = AuditNoteRepository(database)
financial_data = FinancialDataService(database)
demo_data = DemoDataService(database, financial_data, settings.demo_data_dir)
output_snapshots = OutputSnapshotService(database)
output_drafts = OutputDraftService(database, output_snapshots)
output_exports = OutputExportService(database, output_snapshots, output_drafts)
MIN_IMPORT_FREE_BYTES = 10 * 1024**3


class _ImportDiskSpaceLow(RuntimeError):
    pass


def _has_import_disk_capacity(root: Path, pending_bytes: int = 0) -> bool:
    return shutil.disk_usage(root).free - pending_bytes >= MIN_IMPORT_FREE_BYTES


def seed_synthetic_project() -> None:
    if not settings.seed_synthetic or database.list_projects():
        return
    storage = settings.data_dir / "synthetic-demo-project"
    database.create_project(
        ProjectCreate(
            name="华东制造 2025 年度审计（合成演示）",
            entity_name="华东制造有限公司（合成主体）",
            year_start=2023,
            year_end=2025,
            storage_path=str(storage),
            model_profile="严格离线 / Fake Provider",
        ),
        is_synthetic=True,
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    seed_synthetic_project()
    database.recover_tasks()
    worker_task = asyncio.create_task(worker.run())
    try:
        yield
    finally:
        worker.stop()
        await worker_task


app = FastAPI(title="衡鉴审计工作台 API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)


def require_session(request: Request) -> None:
    session_guard.verify(request)


def project_or_404(project_id: str) -> dict:
    try:
        return database.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在") from exc


def project_root_or_error(project_id: str) -> Path:
    try:
        return database.project_root(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在") from exc
    except ProjectStorageUnavailable as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PROJECT_STORAGE_UNAVAILABLE",
                "message": "项目目录不可用或项目数据库已移动",
                "action": "恢复原项目目录后重试",
            },
        ) from exc


def task_from_row(row) -> TaskRecord:
    return TaskRecord(**dict(row))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "bind": settings.host}


@app.post("/api/v1/session", status_code=204)
def create_session(request: Request, response: Response) -> None:
    client_host = request.client.host if request.client else ""
    if client_host not in {"127.0.0.1", "::1", "testclient"}:
        raise HTTPException(status_code=403, detail="仅允许本机访问")
    response.set_cookie(
        SESSION_COOKIE,
        session_guard.token,
        httponly=True,
        samesite="strict",
        secure=False,
        max_age=60 * 60 * 12,
    )


@app.get("/api/v1/projects", response_model=list[ProjectSummary], dependencies=[Depends(require_session)])
def list_projects() -> list[dict]:
    return database.list_projects()


@app.post(
    "/api/v1/projects/{project_id}/external-access",
    response_model=ProjectSummary,
    dependencies=[Depends(require_session)],
)
def set_project_external_access(project_id: str, payload: ExternalAccessUpdate) -> dict:
    project_or_404(project_id)
    database.set_project_external_access(project_id, payload.enabled)
    return next(project for project in database.list_projects() if project["id"] == project_id)


@app.post("/api/v1/projects", response_model=ProjectSummary, status_code=201, dependencies=[Depends(require_session)])
def create_project(payload: ProjectCreate) -> dict:
    try:
        project = database.create_project(payload)
        logger.info("project.created", extra={"project_id": project["id"]})
        project.update(database.project_counts(Path(project["storage_path"])))
        return project
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "PROJECT_CONFLICT", "message": "项目名称或存储路径已存在", "action": "更换名称或目录后重试"},
        ) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "STORAGE_NOT_WRITABLE", "message": str(exc), "action": "选择可写的本地目录"},
        ) from exc


@app.get(
    "/api/v1/gateway",
    response_model=GatewayOverview,
    dependencies=[Depends(require_session)],
)
def gateway_overview() -> GatewayOverview:
    return GatewayOverview(
        strict_offline=database.strict_offline(),
        cache_enabled=database.model_cache_enabled(),
        cache_entry_count=database.model_cache_entry_count(),
        providers=database.list_model_providers(),
        models=database.list_model_profiles(),
        recent_calls=database.recent_model_calls(),
    )


@app.post(
    "/api/v1/settings/offline",
    response_model=GatewayOverview,
    dependencies=[Depends(require_session)],
)
def set_offline_mode(payload: OfflineModeUpdate) -> GatewayOverview:
    database.set_strict_offline(payload.strict_offline)
    logger.info("gateway.offline_changed", extra={"strict_offline": payload.strict_offline})
    return gateway_overview()


@app.post(
    "/api/v1/settings/model-cache",
    response_model=GatewayOverview,
    dependencies=[Depends(require_session)],
)
def set_model_cache(payload: ModelCacheUpdate) -> GatewayOverview:
    database.set_model_cache_enabled(payload.enabled)
    logger.info("gateway.cache_setting_changed", extra={"enabled": payload.enabled})
    return gateway_overview()


@app.delete(
    "/api/v1/model-cache",
    response_model=ModelCacheClearResult,
    dependencies=[Depends(require_session)],
)
def clear_model_cache() -> ModelCacheClearResult:
    deleted_entries = database.clear_model_cache()
    logger.info("gateway.cache_cleared", extra={"entry_count": deleted_entries})
    return ModelCacheClearResult(deleted_entries=deleted_entries)


@app.post(
    "/api/v1/model-providers",
    response_model=ModelProviderRecord,
    status_code=201,
    dependencies=[Depends(require_session)],
)
def create_model_provider(payload: ModelProviderCreate) -> dict:
    try:
        provider = database.create_model_provider(payload)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "MODEL_PROVIDER_CONFLICT",
                "message": "服务商显示名称已存在",
                "action": "更换显示名称后重试",
            },
        ) from exc
    logger.info("gateway.provider_created", extra={"provider_id": provider["id"]})
    return provider


@app.put(
    "/api/v1/model-providers/{provider_id}",
    response_model=ModelProviderRecord,
    dependencies=[Depends(require_session)],
)
def update_model_provider(provider_id: str, payload: ModelProviderUpdate) -> dict:
    try:
        provider = database.update_model_provider(provider_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="服务商不存在") from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "MODEL_PROVIDER_PROTECTED", "message": str(exc), "action": "保留本地验收配置"},
        ) from exc
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "MODEL_PROVIDER_CONFLICT",
                "message": "服务商显示名称已存在",
                "action": "更换显示名称后重试",
            },
        ) from exc
    logger.info("gateway.provider_updated", extra={"provider_id": provider_id})
    return provider


@app.post(
    "/api/v1/model-providers/{provider_id}/toggle",
    response_model=ModelProviderRecord,
    dependencies=[Depends(require_session)],
)
def toggle_model_provider(provider_id: str) -> dict:
    try:
        return database.toggle_model_provider(provider_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="服务商不存在") from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "FAKE_PROVIDER_REQUIRED", "message": str(exc), "action": "保留本地验收通道"},
        ) from exc


@app.delete(
    "/api/v1/model-providers/{provider_id}",
    status_code=204,
    dependencies=[Depends(require_session)],
)
def delete_model_provider(provider_id: str) -> Response:
    try:
        database.delete_model_provider(provider_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="服务商不存在") from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "MODEL_PROVIDER_DELETE_BLOCKED",
                "message": str(exc),
                "action": "先删除关联模型档案；本地验收配置不可删除",
            },
        ) from exc
    logger.info("gateway.provider_deleted", extra={"provider_id": provider_id})
    return Response(status_code=204)


@app.post(
    "/api/v1/model-profiles",
    response_model=ModelProfileRecord,
    status_code=201,
    dependencies=[Depends(require_session)],
)
def create_model_profile(payload: ModelProfileCreate) -> dict:
    try:
        model = database.create_model_profile(payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="服务商不存在") from exc
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "MODEL_PROFILE_CONFLICT",
                "message": "该服务商下已存在相同模型标识",
                "action": "检查模型名称后重试",
            },
        ) from exc
    logger.info("gateway.model_created", extra={"model_profile_id": model["id"]})
    return model


@app.put(
    "/api/v1/model-profiles/{model_id}",
    response_model=ModelProfileRecord,
    dependencies=[Depends(require_session)],
)
def update_model_profile(model_id: str, payload: ModelProfileUpdate) -> dict:
    try:
        model = database.update_model_profile(model_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="服务商或模型档案不存在") from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "FAKE_MODEL_REQUIRED", "message": str(exc), "action": "保留本地验收配置"},
        ) from exc
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "MODEL_PROFILE_CONFLICT",
                "message": "该服务商下已存在相同模型标识",
                "action": "检查模型名称后重试",
            },
        ) from exc
    logger.info("gateway.model_updated", extra={"model_profile_id": model_id})
    return model


@app.post(
    "/api/v1/model-profiles/{model_id}/toggle",
    response_model=ModelProfileRecord,
    dependencies=[Depends(require_session)],
)
def toggle_model_profile(model_id: str) -> dict:
    try:
        return database.toggle_model_profile(model_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模型档案不存在") from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "FAKE_MODEL_REQUIRED", "message": str(exc), "action": "保留本地验收通道"},
        ) from exc


@app.delete(
    "/api/v1/model-profiles/{model_id}",
    status_code=204,
    dependencies=[Depends(require_session)],
)
def delete_model_profile(model_id: str) -> Response:
    try:
        database.delete_model_profile(model_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模型档案不存在") from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "MODEL_PROFILE_DELETE_BLOCKED",
                "message": str(exc),
                "action": "保留本地验收配置",
            },
        ) from exc
    logger.info("gateway.model_deleted", extra={"model_profile_id": model_id})
    return Response(status_code=204)


@app.post(
    "/api/v1/model-gateway/probe",
    response_model=GatewayProbeResult,
    dependencies=[Depends(require_session)],
)
def probe_model_gateway(payload: GatewayProbe) -> dict:
    project_or_404(payload.project_id)
    try:
        return model_gateway.probe(payload.project_id, payload.capability, payload.prompt)
    except GatewayError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message, "action": exc.action},
        ) from exc


@app.get(
    "/api/v1/projects/{project_id}/risks",
    response_model=list[RiskRecord],
    dependencies=[Depends(require_session)],
)
def list_risks(project_id: str) -> list[dict]:
    project_root_or_error(project_id)
    return risk_repository.list(project_id)


@app.post(
    "/api/v1/projects/{project_id}/risks",
    response_model=RiskRecord,
    status_code=201,
    dependencies=[Depends(require_session)],
)
def create_risk(project_id: str, payload: RiskCreate) -> dict:
    project_root_or_error(project_id)
    try:
        risk = risk_repository.create(project_id, payload)
    except RiskError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "message": exc.message, "action": exc.action},
        ) from exc
    logger.info("risk.created", extra={"project_id": project_id, "risk_id": risk["id"]})
    return risk


@app.get(
    "/api/v1/projects/{project_id}/risks/{risk_id}",
    response_model=RiskRecord,
    dependencies=[Depends(require_session)],
)
def get_risk(project_id: str, risk_id: str) -> dict:
    project_root_or_error(project_id)
    try:
        return risk_repository.get(project_id, risk_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="风险卡不存在") from exc


@app.post(
    "/api/v1/projects/{project_id}/risks/{risk_id}/transition",
    response_model=RiskRecord,
    dependencies=[Depends(require_session)],
)
def transition_risk(project_id: str, risk_id: str, payload: RiskTransition) -> dict:
    project_root_or_error(project_id)
    try:
        risk = risk_repository.transition(project_id, risk_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="风险卡不存在") from exc
    except RiskError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message, "action": exc.action},
        ) from exc
    logger.info(
        "risk.status_changed",
        extra={"project_id": project_id, "risk_id": risk_id, "status": payload.status},
    )
    return risk


@app.post(
    "/api/v1/projects/{project_id}/risks/{risk_id}/reassess",
    response_model=RiskRecord,
    dependencies=[Depends(require_session)],
)
def reassess_risk(
    project_id: str, risk_id: str, payload: RiskReassessment
) -> dict:
    project_root_or_error(project_id)
    try:
        risk = risk_repository.reassess_with_evidence(project_id, risk_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="风险卡不存在") from exc
    except RiskError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message, "action": exc.action},
        ) from exc
    logger.info(
        "risk.evidence_reassessed",
        extra={"project_id": project_id, "risk_id": risk_id, "version": risk["version"]},
    )
    return risk


@app.post(
    "/api/v1/projects/{project_id}/risks/{risk_id}/fake-explanation",
    response_model=FakeRiskDraftResult,
    dependencies=[Depends(require_session)],
)
def create_fake_risk_explanation(project_id: str, risk_id: str) -> dict:
    project_root_or_error(project_id)
    try:
        risk = risk_repository.get(project_id, risk_id)
        if risk["status"] != "待复核":
            raise RiskError(
                "RISK_EXPLANATION_REVIEW_REQUIRED",
                "只有待复核风险可以生成或更新模型解释",
                "如有新证据，先按受控流程生成新版本并重新进入待复核",
            )
        support_refs = [
            (
                f"{item['document_id']}:{item['page_number']}:{item['block_number']}"
                if item["kind"] == "document"
                else f"dataset:{item['dataset_id']}:lines:{item['line_start']}-{item['line_end']}"
            )
            for item in risk["evidence"]
            if item["direction"] == "support"
        ]
        counter_refs = [
            (
                f"{item['document_id']}:{item['page_number']}:{item['block_number']}"
                if item["kind"] == "document"
                else f"dataset:{item['dataset_id']}:lines:{item['line_start']}-{item['line_end']}"
            )
            for item in risk["evidence"]
            if item["direction"] == "counter"
        ]
        draft = model_gateway.draft_fake_risk_explanation(
            project_id,
            summary=risk["summary"],
            support_refs=support_refs,
            counter_refs=counter_refs,
        )
        updated = risk_repository.apply_fake_explanation(
            project_id,
            risk_id,
            explanation=draft["explanation"],
            uncertainty=draft["uncertainty"],
            provider=draft["provider"],
            actual_model=draft["actual_model"],
            model_call_id=draft["call_id"],
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="风险卡不存在") from exc
    except GatewayError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message, "action": exc.action},
        ) from exc
    except RiskError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message, "action": exc.action},
        ) from exc
    logger.info(
        "risk.fake_explanation_created",
        extra={"project_id": project_id, "risk_id": risk_id},
    )
    return {"risk": updated, "external_request": False}


@app.get(
    "/api/v1/projects/{project_id}/notes",
    response_model=list[AuditNoteRecord],
    dependencies=[Depends(require_session)],
)
def list_audit_notes(project_id: str) -> list[dict]:
    project_root_or_error(project_id)
    return note_repository.list(project_id)


@app.post(
    "/api/v1/projects/{project_id}/notes",
    response_model=AuditNoteRecord,
    status_code=201,
    dependencies=[Depends(require_session)],
)
def create_audit_note(project_id: str, payload: AuditNotePayload) -> dict:
    project_root_or_error(project_id)
    try:
        note = note_repository.create(project_id, payload)
    except NoteError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "message": exc.message, "action": exc.action},
        ) from exc
    logger.info("note.created", extra={"project_id": project_id, "note_id": note["id"]})
    return note


@app.put(
    "/api/v1/projects/{project_id}/notes/{note_id}",
    response_model=AuditNoteRecord,
    dependencies=[Depends(require_session)],
)
def update_audit_note(
    project_id: str, note_id: str, payload: AuditNotePayload
) -> dict:
    project_root_or_error(project_id)
    try:
        note = note_repository.update(project_id, note_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="备忘录不存在") from exc
    except NoteError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "message": exc.message, "action": exc.action},
        ) from exc
    logger.info("note.updated", extra={"project_id": project_id, "note_id": note_id})
    return note


@app.delete(
    "/api/v1/projects/{project_id}/notes/{note_id}",
    status_code=204,
    dependencies=[Depends(require_session)],
)
def delete_audit_note(project_id: str, note_id: str) -> Response:
    project_root_or_error(project_id)
    try:
        note_repository.delete(project_id, note_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="备忘录不存在") from exc
    logger.info("note.deleted", extra={"project_id": project_id, "note_id": note_id})
    return Response(status_code=204)


@app.get(
    "/api/v1/projects/{project_id}/assistant/threads",
    response_model=list[AssistantThreadRecord],
    dependencies=[Depends(require_session)],
)
def list_assistant_threads(project_id: str) -> list[dict]:
    project_root_or_error(project_id)
    return assistant_service.list_threads(project_id)


@app.post(
    "/api/v1/projects/{project_id}/assistant/threads",
    response_model=AssistantThreadRecord,
    status_code=201,
    dependencies=[Depends(require_session)],
)
def create_assistant_thread(
    project_id: str, payload: AssistantThreadCreate
) -> dict:
    project_root_or_error(project_id)
    thread = assistant_service.create_thread(project_id, payload)
    logger.info(
        "assistant.thread_created",
        extra={"project_id": project_id, "thread_id": thread["id"]},
    )
    return thread


@app.post(
    "/api/v1/projects/{project_id}/assistant/threads/{thread_id}/messages",
    response_model=AssistantThreadRecord,
    dependencies=[Depends(require_session)],
)
def create_assistant_message(
    project_id: str, thread_id: str, payload: AssistantMessageCreate
) -> dict:
    project_root_or_error(project_id)
    try:
        thread = assistant_service.send_message(project_id, thread_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="AI 对话不存在") from exc
    except AssistantError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message, "action": exc.action},
        ) from exc
    except GatewayError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message, "action": exc.action},
        ) from exc
    logger.info(
        "assistant.message_created",
        extra={
            "project_id": project_id,
            "thread_id": thread_id,
            "scope": payload.scope,
            "preset": payload.preset,
        },
    )
    return thread


@app.patch(
    "/api/v1/projects/{project_id}/assistant/threads/{thread_id}",
    response_model=AssistantThreadRecord,
    dependencies=[Depends(require_session)],
)
def rename_assistant_thread(
    project_id: str, thread_id: str, payload: AssistantThreadUpdate
) -> dict:
    project_root_or_error(project_id)
    try:
        thread = assistant_service.rename_thread(project_id, thread_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="AI 对话不存在") from exc
    logger.info(
        "assistant.thread_renamed",
        extra={"project_id": project_id, "thread_id": thread_id},
    )
    return thread


@app.delete(
    "/api/v1/projects/{project_id}/assistant/threads/{thread_id}/messages/{message_id}",
    status_code=204,
    dependencies=[Depends(require_session)],
)
def delete_assistant_message(
    project_id: str, thread_id: str, message_id: str
) -> Response:
    project_root_or_error(project_id)
    try:
        assistant_service.delete_message(project_id, thread_id, message_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="AI 对话消息不存在") from exc
    return Response(status_code=204)


@app.delete(
    "/api/v1/projects/{project_id}/assistant/threads/{thread_id}",
    status_code=204,
    dependencies=[Depends(require_session)],
)
def delete_assistant_thread(project_id: str, thread_id: str) -> Response:
    project_root_or_error(project_id)
    try:
        assistant_service.delete_thread(project_id, thread_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="AI 对话不存在") from exc
    logger.info(
        "assistant.thread_deleted",
        extra={"project_id": project_id, "thread_id": thread_id},
    )
    return Response(status_code=204)


@app.get(
    "/api/v1/projects/{project_id}/outputs/snapshots",
    response_model=list[OutputSnapshotSummary],
    dependencies=[Depends(require_session)],
)
def list_output_snapshots(project_id: str) -> list[dict]:
    project_root_or_error(project_id)
    return output_snapshots.list(project_id)


@app.get(
    "/api/v1/projects/{project_id}/outputs/snapshots/{snapshot_id}",
    response_model=OutputSnapshotDetail,
    dependencies=[Depends(require_session)],
)
def get_output_snapshot(project_id: str, snapshot_id: str) -> dict:
    project_root_or_error(project_id)
    try:
        return output_snapshots.get(project_id, snapshot_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="输出快照不存在") from exc


@app.post(
    "/api/v1/projects/{project_id}/outputs/risk-register/snapshots",
    response_model=OutputSnapshotDetail,
    status_code=201,
    dependencies=[Depends(require_session)],
)
def create_risk_register_snapshot(project_id: str) -> dict:
    project_root_or_error(project_id)
    try:
        snapshot = output_snapshots.create_risk_register(project_id)
    except OutputError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message, "action": exc.action},
        ) from exc
    logger.info(
        "output.snapshot_created",
        extra={
            "project_id": project_id,
            "snapshot_id": snapshot["id"],
            "risk_count": snapshot["risk_count"],
        },
    )
    return snapshot


@app.get(
    "/api/v1/projects/{project_id}/outputs/drafts",
    response_model=list[OutputDraftRecord],
    dependencies=[Depends(require_session)],
)
def list_output_drafts(project_id: str, snapshot_id: str | None = None) -> list[dict]:
    project_root_or_error(project_id)
    return output_drafts.list(project_id, snapshot_id)


@app.post(
    "/api/v1/projects/{project_id}/outputs/snapshots/{snapshot_id}/drafts",
    response_model=OutputDraftRecord,
    status_code=201,
    dependencies=[Depends(require_session)],
)
def create_output_draft(project_id: str, snapshot_id: str) -> dict:
    project_root_or_error(project_id)
    try:
        return output_drafts.create(project_id, snapshot_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="输出快照不存在") from exc


@app.get(
    "/api/v1/projects/{project_id}/outputs/drafts/{draft_id}",
    response_model=OutputDraftRecord,
    dependencies=[Depends(require_session)],
)
def get_output_draft(project_id: str, draft_id: str) -> dict:
    project_root_or_error(project_id)
    try:
        return output_drafts.get(project_id, draft_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="输出草稿不存在") from exc


@app.patch(
    "/api/v1/projects/{project_id}/outputs/drafts/{draft_id}",
    response_model=OutputDraftRecord,
    dependencies=[Depends(require_session)],
)
def update_output_draft(project_id: str, draft_id: str, payload: OutputDraftUpdate) -> dict:
    project_root_or_error(project_id)
    try:
        return output_drafts.update(
            project_id,
            draft_id,
            title=payload.title,
            notes=payload.notes,
            items=[item.model_dump() for item in payload.items],
            materials_title=payload.materials_title,
            materials=[item.model_dump() for item in payload.materials],
            interview_title=payload.interview_title,
            interviews=[item.model_dump() for item in payload.interviews],
            management_title=payload.management_title,
            management=[item.model_dump() for item in payload.management],
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="输出草稿不存在") from exc
    except OutputError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message, "action": exc.action},
        ) from exc


@app.post(
    "/api/v1/projects/{project_id}/outputs/drafts/{draft_id}/finalize",
    response_model=OutputDraftRecord,
    dependencies=[Depends(require_session)],
)
def finalize_output_draft(project_id: str, draft_id: str) -> dict:
    project_root_or_error(project_id)
    try:
        return output_drafts.finalize(project_id, draft_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="输出草稿不存在") from exc


@app.get(
    "/api/v1/projects/{project_id}/outputs/exports",
    response_model=list[OutputExportRecord],
    dependencies=[Depends(require_session)],
)
def list_output_exports(project_id: str, draft_id: str | None = None) -> list[dict]:
    project_root_or_error(project_id)
    return output_exports.list(project_id, draft_id)


@app.post(
    "/api/v1/projects/{project_id}/outputs/drafts/{draft_id}/exports/xlsx",
    response_model=OutputExportRecord,
    status_code=201,
    dependencies=[Depends(require_session)],
)
def create_excel_export(project_id: str, draft_id: str) -> dict:
    project_root_or_error(project_id)
    try:
        return output_exports.create_excel(project_id, draft_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="输出草稿或快照不存在") from exc
    except OutputError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message, "action": exc.action},
        ) from exc


@app.post(
    "/api/v1/projects/{project_id}/outputs/drafts/{draft_id}/exports/docx",
    response_model=OutputExportRecord,
    status_code=201,
    dependencies=[Depends(require_session)],
)
def create_word_export(project_id: str, draft_id: str) -> dict:
    project_root_or_error(project_id)
    try:
        return output_exports.create_word(project_id, draft_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="输出草稿或快照不存在") from exc
    except OutputError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message, "action": exc.action},
        ) from exc


@app.post(
    "/api/v1/projects/{project_id}/outputs/drafts/{draft_id}/exports/pdf",
    response_model=OutputExportRecord,
    status_code=201,
    dependencies=[Depends(require_session)],
)
def create_pdf_export(project_id: str, draft_id: str) -> dict:
    project_root_or_error(project_id)
    try:
        return output_exports.create_pdf(project_id, draft_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="输出草稿或快照不存在") from exc
    except OutputError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message, "action": exc.action},
        ) from exc


@app.post(
    "/api/v1/projects/{project_id}/outputs/drafts/{draft_id}/exports/evidence-package-xlsx",
    response_model=OutputExportRecord,
    status_code=201,
    dependencies=[Depends(require_session)],
)
def create_evidence_package_export(project_id: str, draft_id: str) -> dict:
    project_root_or_error(project_id)
    try:
        return output_exports.create_evidence_package(project_id, draft_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="输出草稿或快照不存在") from exc
    except OutputError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message, "action": exc.action},
        ) from exc


@app.get(
    "/api/v1/projects/{project_id}/outputs/exports/{export_id}/file",
    dependencies=[Depends(require_session)],
)
def download_output_export(project_id: str, export_id: str) -> FileResponse:
    project_root_or_error(project_id)
    try:
        record, path = output_exports.get(project_id, export_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="导出记录不存在") from exc
    except OutputError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message, "action": exc.action},
        ) from exc
    media_types = {
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pdf": "application/pdf",
    }
    return FileResponse(path, media_type=media_types[record["export_format"]], filename=record["filename"])


@app.get("/api/v1/projects/{project_id}/documents", response_model=list[DocumentRecord], dependencies=[Depends(require_session)])
def list_documents(project_id: str) -> list[dict]:
    root = project_root_or_error(project_id)
    with database.connect(root / "app.db") as db:
        rows = db.execute(
            """SELECT d.*,
            CASE WHEN COUNT(v.id)=0 THEN d.page_count
                 ELSE SUM(CASE WHEN v.status='not_required' THEN 1 ELSE 0 END) END
                 native_page_count,
            SUM(CASE WHEN v.status!='not_required' THEN 1 ELSE 0 END) scan_page_count,
            SUM(CASE WHEN v.status='completed' THEN 1 ELSE 0 END) vision_page_count,
            SUM(CASE WHEN v.external_request=1 THEN 1 ELSE 0 END) external_vision_page_count,
            CASE WHEN SUM(CASE WHEN v.status='failed' THEN 1 ELSE 0 END)>0 THEN 'failed'
                 WHEN SUM(CASE WHEN v.status='requires_vision' THEN 1 ELSE 0 END)>0
                      THEN 'requires_vision'
                 WHEN SUM(CASE WHEN v.status='completed' THEN 1 ELSE 0 END)>0 THEN 'completed'
                 ELSE 'not_required' END vision_status
            FROM documents d
            LEFT JOIN page_vision_results v ON v.document_id=d.id
            GROUP BY d.id ORDER BY d.created_at DESC"""
        ).fetchall()
    return [decode_document_row(row) for row in rows]


@app.patch(
    "/api/v1/projects/{project_id}/documents/{document_id}/metadata",
    response_model=DocumentRecord,
    dependencies=[Depends(require_session)],
)
def patch_document_metadata(
    project_id: str,
    document_id: str,
    payload: DocumentMetadataUpdate,
) -> dict:
    project = project_or_404(project_id)
    root = project_root_or_error(project_id)
    if payload.fiscal_year is not None and not (
        project["year_start"] <= payload.fiscal_year <= project["year_end"]
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "DOCUMENT_YEAR_OUTSIDE_PROJECT",
                "message": "文档年度不在项目年度范围内",
                "action": f"填写 {project['year_start']} 至 {project['year_end']} 之间的年度",
            },
        )
    try:
        with database.connect(root / "app.db") as db:
            updated = update_document_metadata(db, document_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="文档不存在") from exc
    database.record_project_event(
        root,
        "document.metadata_updated",
        details={
            "document_id": document_id,
            "metadata_version": updated["metadata_version"],
            "fields": ["fiscal_year", "entity_name", "document_type", "account_names"],
        },
    )
    logger.info(
        "document.metadata_updated",
        extra={"project_id": project_id, "document_id": document_id},
    )
    return next(document for document in list_documents(project_id) if document["id"] == document_id)


@app.get(
    "/api/v1/projects/{project_id}/documents/{document_id}/page-analyses",
    response_model=list[PageVisionRecord],
    dependencies=[Depends(require_session)],
)
def list_page_analyses(project_id: str, document_id: str) -> list[dict]:
    root = project_root_or_error(project_id)
    with database.connect(root / "app.db") as db:
        document = db.execute(
            "SELECT id FROM documents WHERE id=?", (document_id,)
        ).fetchone()
        if document is None:
            raise HTTPException(status_code=404, detail="文档不存在")
        rows = db.execute(
            """SELECT v.page_number, v.status, v.provider_name, v.actual_model,
            v.model_call_id, v.schema_version, v.confidence, v.image_sha256,
            v.external_request, v.remote_request_id, v.remote_cleanup_status,
            v.error_code, v.error_message,
            p.parse_method, p.parse_version
            FROM page_vision_results v
            JOIN pages p ON p.document_id=v.document_id
                        AND p.page_number=v.page_number AND p.block_number=1
            WHERE v.document_id=? ORDER BY v.page_number""",
            (document_id,),
        ).fetchall()
    return [dict(row) for row in rows]


@app.get(
    "/api/v1/projects/{project_id}/documents/{document_id}/pages/{page_number}/content",
    response_model=PageContentRecord,
    dependencies=[Depends(require_session)],
)
def read_page_content(project_id: str, document_id: str, page_number: int) -> dict:
    root = project_root_or_error(project_id)
    try:
        with database.connect(root / "app.db") as db:
            return get_page_content(db, document_id, page_number)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="文档不存在") from exc
    except DocumentCorrectionError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": exc.code, "message": exc.message, "action": exc.action},
        ) from exc


@app.post(
    "/api/v1/projects/{project_id}/documents/{document_id}/pages/{page_number}/corrections",
    response_model=PageTextCorrectionRecord,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_session)],
)
def create_page_text_correction(
    project_id: str,
    document_id: str,
    page_number: int,
    payload: PageTextCorrectionCreate,
) -> dict:
    root = project_root_or_error(project_id)
    try:
        with database.connect(root / "app.db") as db:
            correction = correct_page_text(db, document_id, page_number, payload)
    except DocumentCorrectionError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message, "action": exc.action},
        ) from exc
    logger.info(
        "document.page_text_corrected",
        extra={
            "project_id": project_id,
            "document_id": document_id,
            "page_number": page_number,
            "block_number": payload.block_number,
        },
    )
    return correction


@app.get("/api/v1/projects/{project_id}/tasks", response_model=list[TaskRecord], dependencies=[Depends(require_session)])
def list_tasks(project_id: str) -> list[TaskRecord]:
    root = project_root_or_error(project_id)
    with database.connect(root / "app.db") as db:
        rows = db.execute("SELECT * FROM tasks ORDER BY created_at DESC").fetchall()
    return [task_from_row(row) for row in rows]


@app.post(
    "/api/v1/projects/{project_id}/demo-data/load",
    response_model=DemoLoadResult,
    status_code=202,
    dependencies=[Depends(require_session)],
)
def load_demo_data(project_id: str) -> dict:
    project_or_404(project_id)
    project_root_or_error(project_id)
    try:
        result = demo_data.load(project_id)
    except DemoDataError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message, "action": exc.action},
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "DEMO_LOCAL_IO_ERROR",
                "message": f"演示资料载入失败：{exc}",
                "action": "检查 mock资料 与项目目录权限后重试",
            },
        ) from exc
    logger.info(
        "demo_data.load_requested",
        extra={
            "project_id": project_id,
            "queued_task_count": result["queued_task_count"],
            "external_request": False,
        },
    )
    return result


@app.post(
    "/api/v1/projects/{project_id}/financial-data/preview",
    response_model=FinancialPreview,
    dependencies=[Depends(require_session)],
)
async def preview_financial_data(project_id: str, file: UploadFile = File(...)) -> dict:
    root = project_root_or_error(project_id)
    filename = Path(file.filename or "trial-balance.csv").name
    if Path(filename).suffix.lower() != ".csv":
        raise HTTPException(
            status_code=415,
            detail={
                "code": "FILE_TYPE_UNSUPPORTED",
                "message": f"{filename} 不是 CSV",
                "action": "下载模板并选择 CSV 文件",
            },
        )
    preview_file_id = str(uuid.uuid4())
    incoming = root / "incoming" / f"financial-preview-{preview_file_id}.csv"
    size = 0
    try:
        with incoming.open("wb") as destination:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_CSV_BYTES:
                    raise FinancialDataError(
                        "CSV_SIZE_LIMIT_EXCEEDED",
                        "CSV 超过 100 MB 上限",
                        "拆分文件后重新上传",
                    )
                destination.write(chunk)
    except FinancialDataError as exc:
        incoming.unlink(missing_ok=True)
        raise HTTPException(
            status_code=413,
            detail={"code": exc.code, "message": exc.message, "action": exc.action},
        ) from exc
    finally:
        await file.close()
    try:
        return financial_data.preview(project_id, filename, incoming, sha256_file(incoming))
    except FinancialDataError as exc:
        incoming.unlink(missing_ok=True)
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "message": exc.message, "action": exc.action},
        ) from exc


@app.post(
    "/api/v1/projects/{project_id}/financial-data/confirm",
    response_model=FinancialConfirmResult,
    status_code=202,
    dependencies=[Depends(require_session)],
)
def confirm_financial_data(
    project_id: str, payload: FinancialPreviewConfirm
) -> dict[str, object]:
    project_root_or_error(project_id)
    try:
        return financial_data.confirm(project_id, payload.preview_id)
    except FinancialDataError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message, "action": exc.action},
        ) from exc


@app.get(
    "/api/v1/projects/{project_id}/financial-data",
    response_model=list[FinancialDataset],
    dependencies=[Depends(require_session)],
)
def list_financial_datasets(project_id: str) -> list[dict]:
    project_root_or_error(project_id)
    return financial_data.list_datasets(project_id)


@app.get(
    "/api/v1/projects/{project_id}/financial-data/{dataset_id}",
    response_model=FinancialDataset,
    dependencies=[Depends(require_session)],
)
def get_financial_dataset(project_id: str, dataset_id: str) -> dict:
    project_root_or_error(project_id)
    try:
        return financial_data.get_dataset(project_id, dataset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="财务数据集不存在") from exc


@app.get(
    "/api/v1/projects/{project_id}/financial-data/{dataset_id}/trend-accounts",
    response_model=list[FinancialTrendAccount],
    dependencies=[Depends(require_session)],
)
def list_financial_trend_accounts(project_id: str, dataset_id: str) -> list[dict]:
    project_root_or_error(project_id)
    try:
        return financial_data.list_trend_accounts(project_id, dataset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="财务数据集不存在") from exc


@app.get(
    "/api/v1/projects/{project_id}/financial-data/{dataset_id}/trend-analysis",
    response_model=FinancialTrendAnalysis,
    dependencies=[Depends(require_session)],
)
def get_financial_trend_analysis(
    project_id: str,
    dataset_id: str,
    account_code: str = Query(min_length=1, max_length=80),
    denominator_code: str | None = Query(default=None, min_length=1, max_length=80),
) -> dict:
    project_root_or_error(project_id)
    try:
        return financial_data.trend_analysis(
            project_id, dataset_id, account_code, denominator_code
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="财务数据集不存在") from exc
    except FinancialDataError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "message": exc.message, "action": exc.action},
        ) from exc


@app.get(
    "/api/v1/projects/{project_id}/financial-data/{dataset_id}/results/{result_id}/rows",
    response_model=FinancialResultRows,
    dependencies=[Depends(require_session)],
)
def financial_result_rows(
    project_id: str,
    dataset_id: str,
    result_id: str,
    offset: int = 0,
    limit: int = 100,
) -> dict:
    project_root_or_error(project_id)
    safe_offset = max(0, offset)
    safe_limit = min(max(1, limit), 200)
    try:
        return financial_data.result_rows(
            project_id,
            dataset_id,
            result_id,
            offset=safe_offset,
            limit=safe_limit,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="规则结果不存在") from exc


@app.post(
    "/api/v1/projects/{project_id}/financial-data/{dataset_id}/archive",
    response_model=FinancialDataset,
    dependencies=[Depends(require_session)],
)
def archive_financial_dataset(project_id: str, dataset_id: str) -> dict:
    project_root_or_error(project_id)
    try:
        return financial_data.archive_dataset(project_id, dataset_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "DATASET_ARCHIVE_INVALID",
                "message": "数据集不存在或已经归档",
                "action": "刷新数据集列表",
            },
        ) from exc


@app.post(
    "/api/v1/projects/{project_id}/financial-data/{dataset_id}/rule-runs",
    response_model=FinancialRuleRunReuse,
    dependencies=[Depends(require_session)],
)
def reuse_financial_rule_run(project_id: str, dataset_id: str) -> dict:
    project_root_or_error(project_id)
    try:
        run = financial_data.existing_rule_run(project_id, dataset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="数据集或规则运行不存在") from exc
    return {
        "reused": True,
        "run_id": run["id"],
        "rule_set_version": run["rule_set_version"],
        "message": "同一数据集与规则版本已完成，已复用既有结果",
    }


def _csv_response(filename: str, rows: list[list[str]]) -> FastAPIResponse:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerows(rows)
    content = codecs.BOM_UTF8 + stream.getvalue().encode("utf-8")
    return FastAPIResponse(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get(
    "/api/v1/financial-data/template",
    dependencies=[Depends(require_session)],
)
def download_financial_template() -> FastAPIResponse:
    return _csv_response("trial-balance-template.csv", [list(REQUIRED_COLUMNS)])


@app.get(
    "/api/v1/financial-data/synthetic-demo",
    dependencies=[Depends(require_session)],
)
def download_financial_demo() -> FastAPIResponse:
    rows = [
        list(REQUIRED_COLUMNS),
        ["2024", "FY", "1001", "库存现金", "0", "0", "1000", "0", "1000", "0", "CNY", "1"],
        ["2024", "FY", "4001", "实收资本", "0", "0", "0", "1000", "0", "1000", "CNY", "1"],
        ["2025", "FY", "1001", "库存现金", "900", "0", "200", "0", "1100", "0", "CNY", "1"],
        ["2025", "FY", "4001", "实收资本", "0", "1000", "0", "150", "0", "1150", "CNY", "1"],
    ]
    return _csv_response("synthetic-trial-balance-demo.csv", rows)


@app.post("/api/v1/projects/{project_id}/documents", response_model=UploadResult, status_code=202, dependencies=[Depends(require_session)])
async def upload_documents(project_id: str, files: list[UploadFile] = File(...)) -> UploadResult:
    root = project_root_or_error(project_id)
    accepted: list[TaskRecord] = []
    rejected: list[ApiError] = []
    for upload in files:
        filename = Path(upload.filename or "unnamed.pdf").name
        if Path(filename).suffix.lower() != ".pdf":
            rejected.append(ApiError(code="FILE_TYPE_UNSUPPORTED", message=f"{filename} 不是 PDF", action="仅选择 PDF 文件"))
            await upload.close()
            continue
        task_id = str(uuid.uuid4())
        incoming = root / "incoming" / f"{task_id}.part"
        try:
            if not _has_import_disk_capacity(root):
                raise _ImportDiskSpaceLow
            with incoming.open("wb") as destination:
                while chunk := await upload.read(1024 * 1024):
                    if not _has_import_disk_capacity(root, len(chunk)):
                        raise _ImportDiskSpaceLow
                    destination.write(chunk)
            now = utc_now()
            with database.connect(root / "app.db") as db:
                db.execute(
                    """INSERT INTO tasks
                    (id, task_type, filename, incoming_path, status, progress, current_step, created_at, updated_at)
                    VALUES (?, 'pdf_import', ?, ?, 'queued', 0, '等待单工作器', ?, ?)""",
                    (task_id, filename, str(incoming), now, now),
                )
                row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        except _ImportDiskSpaceLow:
            incoming.unlink(missing_ok=True)
            rejected.append(
                ApiError(
                    code="DISK_SPACE_LOW",
                    message=f"{filename} 未导入：项目磁盘剩余空间低于 10GB 安全线",
                    action="释放磁盘空间或选择其他项目目录后重试",
                )
            )
            continue
        except OSError:
            incoming.unlink(missing_ok=True)
            rejected.append(
                ApiError(
                    code="LOCAL_IO_ERROR",
                    message=f"{filename} 写入本地暂存目录失败",
                    action="检查磁盘空间和项目目录权限后重试",
                )
            )
            continue
        except Exception:
            incoming.unlink(missing_ok=True)
            raise
        finally:
            await upload.close()
        database.record_project_event(root, "task.queued", task_id=task_id)
        logger.info("task.queued", extra={"project_id": project_id, "task_id": task_id})
        accepted.append(task_from_row(row))
    return UploadResult(accepted=accepted, rejected=rejected)


@app.post("/api/v1/projects/{project_id}/tasks/{task_id}/{action}", response_model=TaskRecord, dependencies=[Depends(require_session)])
def change_task(project_id: str, task_id: str, action: str) -> TaskRecord:
    root = project_root_or_error(project_id)
    transitions = {
        ("running", "pause"): ("pausing", "正在等待安全点"),
        ("paused", "resume"): ("queued", "等待恢复"),
        ("failed", "retry"): ("queued", "等待重试"),
        ("queued", "cancel"): ("cancelled", "已取消"),
        ("running", "cancel"): ("cancelled", "将在安全点清理"),
        ("paused", "cancel"): ("cancelled", "已取消"),
    }
    with database.connect(root / "app.db") as db:
        row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        if row["status"] == "paused" and action == "resume" and row["pause_reason"] == "resource":
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "RESOURCE_PAUSE_AUTO_RESUME",
                    "message": "该任务由资源保护自动暂停",
                    "action": "等待整机 CPU 低于 30% 持续 10 秒后自动恢复，或取消任务",
                },
            )
        transition = transitions.get((row["status"], action))
        if transition is None:
            raise HTTPException(
                status_code=409,
                detail={"code": "TASK_ACTION_INVALID", "message": f"{row['status']} 状态不允许 {action}", "action": "刷新任务状态后重试"},
            )
        new_status, step = transition
        pause_reason = "user" if action == "pause" else None
        db.execute(
            """UPDATE tasks SET status=?, current_step=?, pause_reason=?,
            updated_at=? WHERE id=?""",
            (new_status, step, pause_reason, utc_now(), task_id),
        )
        changed = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    database.record_project_event(
        root,
        f"task.{new_status}",
        task_id=task_id,
        details={"action": action, "previous_status": row["status"]},
    )
    logger.info(
        "task.state_changed",
        extra={"project_id": project_id, "task_id": task_id, "status": new_status},
    )
    if new_status == "cancelled" and row["status"] in {"queued", "paused"}:
        Path(row["incoming_path"]).unlink(missing_ok=True)
    return task_from_row(changed)


@app.get("/api/v1/projects/{project_id}/documents/{document_id}/file", dependencies=[Depends(require_session)])
def document_file(project_id: str, document_id: str) -> FileResponse:
    root = project_root_or_error(project_id)
    with database.connect(root / "app.db") as db:
        row = db.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return FileResponse(row["stored_path"], media_type="application/pdf", filename=row["filename"])


@app.get(
    "/api/v1/projects/{project_id}/retrieval/status",
    response_model=RetrievalStatus,
    dependencies=[Depends(require_session)],
)
def project_retrieval_status(project_id: str) -> dict:
    root = project_root_or_error(project_id)
    with database.connect(root / "app.db") as db:
        return retrieval_status(db)


@app.post(
    "/api/v1/projects/{project_id}/retrieval/synthetic-index",
    response_model=RetrievalStatus,
    dependencies=[Depends(require_session)],
)
def build_project_synthetic_index(project_id: str) -> dict:
    project = project_or_404(project_id)
    try:
        require_synthetic_project(project["is_synthetic"])
    except SyntheticVectorError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message, "action": exc.action},
        ) from exc
    root = project_root_or_error(project_id)
    try:
        with database.connect(root / "app.db") as db:
            result = build_synthetic_vector_index(db)
    except SyntheticVectorError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message, "action": exc.action},
        ) from exc
    logger.info(
        "retrieval.synthetic_index_built",
        extra={
            "project_id": project_id,
            "chunk_count": result["indexed_chunk_count"],
            "external_request": False,
        },
    )
    return result


@app.get(
    "/api/v1/projects/{project_id}/search",
    response_model=list[DocumentSearchHit],
    dependencies=[Depends(require_session)],
)
def search_project(
    project_id: str,
    q: str = Query(max_length=200),
    document_id: str | None = None,
    page_number: int | None = Query(default=None, ge=1),
    fiscal_year: int | None = Query(default=None, ge=2000, le=2100),
    entity_name: str | None = Query(default=None, max_length=120),
    account_name: str | None = Query(default=None, max_length=80),
    document_type: str | None = Query(default=None, max_length=80),
    parse_method: str | None = Query(default=None, max_length=40),
    mode: Literal["keyword", "hybrid"] = "keyword",
    limit: int = Query(default=20, ge=1, le=50),
) -> list[dict]:
    project = project_or_404(project_id)
    root = project_root_or_error(project_id)
    with database.connect(root / "app.db") as db:
        if mode == "hybrid" and q.strip():
            try:
                require_synthetic_project(project["is_synthetic"])
            except SyntheticVectorError as exc:
                raise HTTPException(
                    status_code=409,
                    detail={"code": exc.code, "message": exc.message, "action": exc.action},
                ) from exc
            try:
                return search_synthetic_hybrid(
                    db,
                    q,
                    document_id=document_id,
                    page_number=page_number,
                    fiscal_year=fiscal_year,
                    entity_name=entity_name,
                    account_name=account_name,
                    document_type=document_type,
                    parse_method=parse_method,
                    limit=limit,
                )
            except SyntheticVectorError as exc:
                raise HTTPException(
                    status_code=409,
                    detail={"code": exc.code, "message": exc.message, "action": exc.action},
                ) from exc
        return search_project_pages(
            db,
            q,
            document_id=document_id,
            page_number=page_number,
            fiscal_year=fiscal_year,
            entity_name=entity_name,
            account_name=account_name,
            document_type=document_type,
            parse_method=parse_method,
            limit=limit,
        )


@app.get(
    "/api/v1/projects/{project_id}/documents/{document_id}/search",
    response_model=list[DocumentSearchHit],
    dependencies=[Depends(require_session)],
)
def search_document(
    project_id: str,
    document_id: str,
    q: str = Query(max_length=200),
) -> list[dict]:
    root = project_root_or_error(project_id)
    with database.connect(root / "app.db") as db:
        document = db.execute(
            "SELECT 1 FROM documents WHERE id=?", (document_id,)
        ).fetchone()
        if document is None:
            raise HTTPException(status_code=404, detail="文档不存在")
        return search_project_pages(db, q, document_id=document_id, limit=20)


@app.get("/api/v1/resources", response_model=ResourceSnapshot, dependencies=[Depends(require_session)])
def resources() -> ResourceSnapshot:
    disk = shutil.disk_usage(settings.data_dir)
    return ResourceSnapshot(
        cpu_percent=round(psutil.cpu_percent(interval=None), 1),
        memory_percent=round(psutil.virtual_memory().percent, 1),
        disk_free_gb=round(disk.free / 1024**3, 1),
    )
