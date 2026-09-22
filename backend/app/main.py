from __future__ import annotations

import asyncio
import logging
import shutil
import sqlite3
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import psutil
from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .config import load_settings
from .db import Database, ProjectStorageUnavailable, utc_now
from .gateway import GatewayError, ModelGateway
from .logging_config import configure_logging
from .schemas import (
    ApiError,
    DocumentRecord,
    ExternalAccessUpdate,
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
    ProjectCreate,
    ProjectSummary,
    ResourceSnapshot,
    TaskRecord,
    UploadResult,
)
from .security import SESSION_COOKIE, LocalSessionGuard
from .worker import LocalTaskWorker

settings = load_settings()
configure_logging(settings.log_level)
logger = logging.getLogger("hengjian.api")
database = Database(settings.data_dir)
session_guard = LocalSessionGuard()
worker = LocalTaskWorker(database)
model_gateway = ModelGateway(database)


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
    allow_methods=["GET", "POST", "PUT"],
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


@app.get("/api/v1/projects/{project_id}/documents", response_model=list[DocumentRecord], dependencies=[Depends(require_session)])
def list_documents(project_id: str) -> list[dict]:
    root = project_root_or_error(project_id)
    with database.connect(root / "app.db") as db:
        rows = db.execute("SELECT * FROM documents ORDER BY created_at DESC").fetchall()
    return [dict(row) for row in rows]


@app.get("/api/v1/projects/{project_id}/tasks", response_model=list[TaskRecord], dependencies=[Depends(require_session)])
def list_tasks(project_id: str) -> list[TaskRecord]:
    root = project_root_or_error(project_id)
    with database.connect(root / "app.db") as db:
        rows = db.execute("SELECT * FROM tasks ORDER BY created_at DESC").fetchall()
    return [task_from_row(row) for row in rows]


@app.post("/api/v1/projects/{project_id}/documents", response_model=UploadResult, status_code=202, dependencies=[Depends(require_session)])
async def upload_documents(project_id: str, files: list[UploadFile] = File(...)) -> UploadResult:
    root = project_root_or_error(project_id)
    accepted: list[TaskRecord] = []
    rejected: list[ApiError] = []
    for upload in files:
        filename = Path(upload.filename or "unnamed.pdf").name
        if Path(filename).suffix.lower() != ".pdf":
            rejected.append(ApiError(code="FILE_TYPE_UNSUPPORTED", message=f"{filename} 不是 PDF", action="仅选择 PDF 文件"))
            continue
        task_id = str(uuid.uuid4())
        incoming = root / "incoming" / f"{task_id}.part"
        try:
            with incoming.open("wb") as destination:
                while chunk := await upload.read(1024 * 1024):
                    destination.write(chunk)
        finally:
            await upload.close()
        now = utc_now()
        with database.connect(root / "app.db") as db:
            db.execute(
                """INSERT INTO tasks
                (id, task_type, filename, incoming_path, status, progress, current_step, created_at, updated_at)
                VALUES (?, 'pdf_import', ?, ?, 'queued', 0, '等待单工作器', ?, ?)""",
                (task_id, filename, str(incoming), now, now),
            )
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
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
        transition = transitions.get((row["status"], action))
        if transition is None:
            raise HTTPException(
                status_code=409,
                detail={"code": "TASK_ACTION_INVALID", "message": f"{row['status']} 状态不允许 {action}", "action": "刷新任务状态后重试"},
            )
        new_status, step = transition
        db.execute(
            "UPDATE tasks SET status=?, current_step=?, updated_at=? WHERE id=?",
            (new_status, step, utc_now(), task_id),
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


@app.get("/api/v1/projects/{project_id}/documents/{document_id}/search", dependencies=[Depends(require_session)])
def search_document(project_id: str, document_id: str, q: str) -> list[dict]:
    root = project_root_or_error(project_id)
    term = q.strip()
    if not term:
        return []
    with database.connect(root / "app.db") as db:
        rows = db.execute(
            """SELECT page_number, substr(original_text, 1, 320) snippet
            FROM pages WHERE document_id=? AND original_text LIKE ? ORDER BY page_number LIMIT 20""",
            (document_id, f"%{term}%"),
        ).fetchall()
    return [dict(row) for row in rows]


@app.get("/api/v1/resources", response_model=ResourceSnapshot, dependencies=[Depends(require_session)])
def resources() -> ResourceSnapshot:
    disk = shutil.disk_usage(settings.data_dir)
    return ResourceSnapshot(
        cpu_percent=round(psutil.cpu_percent(interval=None), 1),
        memory_percent=round(psutil.virtual_memory().percent, 1),
        disk_free_gb=round(disk.free / 1024**3, 1),
    )
