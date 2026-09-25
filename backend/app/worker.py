from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import shutil
import time
import uuid
from collections.abc import Callable
from pathlib import Path

import psutil
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .db import Database, utc_now
from .financial_data import FinancialDataError, FinancialDataService
from .resource_guard import ResourceGuard, ResourceTransition
from .retrieval import replace_page_chunks
from .vision import ScanVisionService, vision_row_values

logger = logging.getLogger("hengjian.worker")

CPU_WAIT_STEP = "整机 CPU 持续超过 50%，等待资源恢复"
CPU_PAUSING_STEP = "整机 CPU 持续超过 50%，正在等待安全点暂停"
CPU_PAUSED_STEP = "因整机 CPU 负载自动暂停，低于 30% 持续 10 秒后恢复"
MEMORY_WAIT_STEP = "系统内存使用超过 70%，等待资源释放"
DEFAULT_QUEUE_STEP = "等待单工作器"


class LocalTaskWorker:
    """Single persistent worker. Every step is safe to retry."""

    def __init__(
        self,
        database: Database,
        *,
        resource_sampler: Callable[[], tuple[float, float]] | None = None,
        clock: Callable[[], float] = time.monotonic,
        resource_interval: float = 1.0,
    ) -> None:
        self.database = database
        self.financial_data = FinancialDataService(database)
        self.scan_vision = ScanVisionService(database)
        self.resource_guard = ResourceGuard()
        self.resource_sampler = resource_sampler or self._sample_system_resources
        self.clock = clock
        self.resource_interval = resource_interval
        self._pending_resource_transitions: dict[str, ResourceTransition] = {}
        self._stopping = False

    def stop(self) -> None:
        self._stopping = True

    async def run(self) -> None:
        try:
            await asyncio.to_thread(self._observe_resources)
        except Exception:
            logger.exception("worker.resource_initial_sample_failed")
        await asyncio.gather(self._run_tasks(), self._monitor_resources())

    async def _run_tasks(self) -> None:
        while not self._stopping:
            try:
                claimed = await asyncio.to_thread(self._claim_next)
            except Exception:
                logger.exception("worker.claim_failed")
                await asyncio.sleep(1)
                continue
            if claimed is None:
                await asyncio.sleep(0.25)
                continue
            project_id, project_root, task_id = claimed
            try:
                await asyncio.to_thread(self._process, project_id, project_root, task_id)
            except Exception:
                logger.exception("worker.task_boundary_failed", extra={"task_id": task_id})
                try:
                    await asyncio.to_thread(
                        self._fail,
                        project_root,
                        task_id,
                        "UNEXPECTED_PROCESSING_ERROR",
                        "本地任务遇到未预期错误",
                        "保留原文件并重试；若问题持续，请查看本地日志",
                    )
                except Exception:
                    logger.exception("worker.failure_record_failed", extra={"task_id": task_id})

    async def _monitor_resources(self) -> None:
        while not self._stopping:
            try:
                await asyncio.to_thread(self._observe_resources)
            except Exception:
                logger.exception("worker.resource_monitor_failed")
            await asyncio.sleep(self.resource_interval)

    @staticmethod
    def _sample_system_resources() -> tuple[float, float]:
        return psutil.cpu_percent(interval=None), psutil.virtual_memory().percent

    def _observe_resources(self) -> list[ResourceTransition]:
        cpu_percent, memory_percent = self.resource_sampler()
        transitions = self.resource_guard.observe(
            cpu_percent, memory_percent, now=self.clock()
        )
        for transition in transitions:
            opposite = {
                "cpu_pause": "cpu_resume",
                "cpu_resume": "cpu_pause",
                "memory_block": "memory_resume",
                "memory_resume": "memory_block",
            }[transition.kind]
            self._pending_resource_transitions.pop(opposite, None)
            self._pending_resource_transitions[transition.kind] = transition
        for kind, transition in list(self._pending_resource_transitions.items()):
            if transition.kind == "cpu_pause":
                self._request_resource_pause(transition)
            elif transition.kind == "cpu_resume":
                self._resume_resource_pauses(transition)
            elif transition.kind == "memory_block":
                self._set_memory_waiting(transition)
            elif transition.kind == "memory_resume":
                self._clear_memory_waiting(transition)
            self._pending_resource_transitions.pop(kind, None)
        if self.resource_guard.admission_blocked:
            self._sync_queued_waiting()
        return transitions

    def _waiting_step(self) -> str:
        if self.resource_guard.memory_blocked:
            return MEMORY_WAIT_STEP
        if self.resource_guard.cpu_paused:
            return CPU_WAIT_STEP
        return DEFAULT_QUEUE_STEP

    def _project_roots(self) -> list[Path]:
        return [
            Path(project["storage_path"])
            for project in self.database.list_projects()
            if project["storage_available"]
        ]

    def _request_resource_pause(self, transition: ResourceTransition) -> None:
        for root in self._project_roots():
            with self.database.connect(root / "app.db") as db:
                db.execute("BEGIN IMMEDIATE")
                running = [
                    row["id"]
                    for row in db.execute(
                        "SELECT id FROM tasks WHERE status='running'"
                    ).fetchall()
                ]
                db.execute(
                    """UPDATE tasks SET status='pausing', pause_reason='resource',
                    current_step=?, updated_at=? WHERE status='running'""",
                    (CPU_PAUSING_STEP, utc_now()),
                )
                db.execute(
                    """UPDATE tasks SET current_step=?, updated_at=?
                    WHERE status='queued' AND current_step<>?""",
                    (self._waiting_step(), utc_now(), self._waiting_step()),
                )
                db.execute("COMMIT")
            for task_id in running:
                self.database.record_project_event(
                    root,
                    "task.resource_pause_requested",
                    task_id=task_id,
                    details={
                        "cpu_percent": transition.cpu_percent,
                        "sustain_seconds": self.resource_guard.cpu_sustain_seconds,
                    },
                )

    def _resume_resource_pauses(self, transition: ResourceTransition) -> None:
        queued_step = self._waiting_step()
        for root in self._project_roots():
            with self.database.connect(root / "app.db") as db:
                db.execute("BEGIN IMMEDIATE")
                rows = db.execute(
                    """SELECT id, status FROM tasks
                    WHERE pause_reason='resource' AND status IN ('pausing', 'paused')"""
                ).fetchall()
                db.execute(
                    """UPDATE tasks SET status='running', pause_reason=NULL,
                    current_step='资源恢复，继续处理', updated_at=?
                    WHERE status='pausing' AND pause_reason='resource'""",
                    (utc_now(),),
                )
                db.execute(
                    """UPDATE tasks SET status='queued', pause_reason=NULL,
                    current_step=?, updated_at=?
                    WHERE status='paused' AND pause_reason='resource'""",
                    (queued_step, utc_now()),
                )
                db.execute(
                    """UPDATE tasks SET current_step=?, updated_at=?
                    WHERE status='queued' AND current_step=?""",
                    (queued_step, utc_now(), CPU_WAIT_STEP),
                )
                db.execute("COMMIT")
            for row in rows:
                self.database.record_project_event(
                    root,
                    "task.resource_resumed",
                    task_id=row["id"],
                    details={
                        "previous_status": row["status"],
                        "cpu_percent": transition.cpu_percent,
                    },
                )

    def _set_memory_waiting(self, transition: ResourceTransition) -> None:
        for root in self._project_roots():
            with self.database.connect(root / "app.db") as db:
                db.execute(
                    "UPDATE tasks SET current_step=?, updated_at=? WHERE status='queued'",
                    (MEMORY_WAIT_STEP, utc_now()),
                )
            self.database.record_project_event(
                root,
                "resource.memory_blocked",
                details={"memory_percent": transition.memory_percent},
            )

    def _clear_memory_waiting(self, transition: ResourceTransition) -> None:
        next_step = self._waiting_step()
        for root in self._project_roots():
            with self.database.connect(root / "app.db") as db:
                db.execute(
                    """UPDATE tasks SET current_step=?, updated_at=?
                    WHERE status='queued' AND current_step=?""",
                    (next_step, utc_now(), MEMORY_WAIT_STEP),
                )
            self.database.record_project_event(
                root,
                "resource.memory_recovered",
                details={"memory_percent": transition.memory_percent},
            )

    def _sync_queued_waiting(self) -> None:
        waiting_step = self._waiting_step()
        for root in self._project_roots():
            with self.database.connect(root / "app.db") as db:
                db.execute(
                    """UPDATE tasks SET current_step=?, updated_at=?
                    WHERE status='queued' AND current_step<>?""",
                    (waiting_step, utc_now(), waiting_step),
                )

    def _claim_next(self) -> tuple[str, Path, str] | None:
        if self.resource_guard.admission_blocked:
            self._sync_queued_waiting()
            return None
        for project in self.database.list_projects():
            if not project["storage_available"]:
                continue
            root = Path(project["storage_path"])
            with self.database.connect(root / "app.db") as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT id, task_type FROM tasks WHERE status='queued' ORDER BY created_at LIMIT 1"
                ).fetchone()
                if row is None:
                    db.execute("COMMIT")
                    continue
                first_step = (
                    "校验科目余额表"
                    if row["task_type"] == "trial_balance_import"
                    else "计算文件哈希"
                )
                changed = db.execute(
                    """UPDATE tasks SET status='running',
                    progress=CASE WHEN progress < 5 THEN 5 ELSE progress END,
                    current_step=?, error_code=NULL, error_message=NULL,
                    next_action=NULL, result_kind=NULL, document_id=NULL,
                    pause_reason=NULL, updated_at=?
                    WHERE id=? AND status='queued'""",
                    (first_step, utc_now(), row["id"]),
                ).rowcount
                db.execute("COMMIT")
                if changed:
                    return project["id"], root, row["id"]
        return None

    def _task_control(self, root: Path, task_id: str) -> tuple[str, str | None]:
        with self.database.connect(root / "app.db") as db:
            row = db.execute(
                "SELECT status, pause_reason FROM tasks WHERE id=?", (task_id,)
            ).fetchone()
        return (row["status"], row["pause_reason"]) if row else ("cancelled", None)

    def _safe_point(self, root: Path, task_id: str, incoming: Path) -> bool:
        status, pause_reason = self._task_control(root, task_id)
        if status == "pausing":
            current_step = CPU_PAUSED_STEP if pause_reason == "resource" else "已在安全点暂停"
            self._update_task(root, task_id, status="paused", current_step=current_step)
            self.database.record_project_event(
                root,
                "task.paused",
                task_id=task_id,
                details={"pause_reason": pause_reason or "user"},
            )
            return False
        if status == "cancelled":
            self._cleanup_cancelled(incoming, task_id)
            return False
        return status == "running"

    @staticmethod
    def _cleanup_cancelled(incoming: Path, task_id: str) -> None:
        try:
            incoming.unlink(missing_ok=True)
        except OSError:
            logger.exception("task.cancel_cleanup_failed", extra={"task_id": task_id})

    def _update_task(self, root: Path, task_id: str, **fields) -> None:
        fields["updated_at"] = utc_now()
        assignments = ", ".join(f"{key}=?" for key in fields)
        with self.database.connect(root / "app.db") as db:
            db.execute(
                f"UPDATE tasks SET {assignments} WHERE id=?",
                (*fields.values(), task_id),
            )

    def _fail(self, root: Path, task_id: str, code: str, message: str, action: str) -> None:
        with self.database.connect(root / "app.db") as db:
            changed = db.execute(
                """UPDATE tasks SET status='failed', current_step='处理失败',
                error_code=?, error_message=?, next_action=?, updated_at=?,
                pause_reason=NULL
                WHERE id=? AND status NOT IN ('cancelled', 'completed')""",
                (code, message, action, utc_now(), task_id),
            ).rowcount
        if not changed:
            return
        self.database.record_project_event(
            root, "task.failed", task_id=task_id, details={"error_code": code}
        )
        logger.error(
            "task.failed", extra={"task_id": task_id, "status": "failed", "error_code": code}
        )

    def _process(self, project_id: str, root: Path, task_id: str) -> None:
        with self.database.connect(root / "app.db") as db:
            task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if task is None:
            return
        if task["task_type"] == "trial_balance_import":
            try:
                self.financial_data.process_import(
                    root, task_id, self._safe_point, self._update_task
                )
            except FinancialDataError as exc:
                self._fail(root, task_id, exc.code, exc.message, exc.action)
            except OSError as exc:
                self._fail(
                    root,
                    task_id,
                    "LOCAL_IO_ERROR",
                    f"本地文件处理失败：{exc}",
                    "检查磁盘空间与目录权限后重试",
                )
            except Exception:
                logger.exception(
                    "task.unexpected_financial_processing_error", extra={"task_id": task_id}
                )
                self._fail(
                    root,
                    task_id,
                    "UNEXPECTED_PROCESSING_ERROR",
                    "财务数据处理遇到未预期错误",
                    "原文件已保留；请重试，若问题持续请查看本地日志",
                )
            return
        self._process_pdf(project_id, root, task_id, task)

    def _process_pdf(self, project_id: str, root: Path, task_id: str, task) -> None:
        incoming = Path(task["incoming_path"])
        if not incoming.exists():
            self._fail(root, task_id, "FILE_MISSING", "待处理文件不存在", "重新选择该 PDF 上传")
            return
        try:
            digest = hashlib.sha256()
            size = incoming.stat().st_size
            with incoming.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
            sha256 = digest.hexdigest()
            self._update_task(root, task_id, progress=35, current_step="校验 PDF 结构")
            if not self._safe_point(root, task_id, incoming):
                return

            with self.database.connect(root / "app.db") as db:
                duplicate = db.execute(
                    "SELECT id FROM documents WHERE sha256=?", (sha256,)
                ).fetchone()
            if duplicate:
                self._complete_duplicate(root, task_id, incoming, duplicate["id"])
                return

            reader = PdfReader(str(incoming))
            if reader.is_encrypted:
                try:
                    unlocked = reader.decrypt("")
                except Exception:
                    unlocked = 0
                if not unlocked:
                    raise PermissionError("PDF 已加密")
            page_count = len(reader.pages)
            if page_count == 0:
                raise PdfReadError("PDF 不包含页面")

            self._update_task(root, task_id, progress=60, current_step="提取原生文本")
            if not self._safe_point(root, task_id, incoming):
                return
            page_text: list[str] = []
            for page in reader.pages:
                if not self._safe_point(root, task_id, incoming):
                    return
                page_text.append(page.extract_text() or "")

            self._update_task(root, task_id, progress=75, current_step="识别扫描页并准备视觉解析")
            page_analyses = self.scan_vision.analyze_pages(
                project_id=project_id,
                root=root,
                task_id=task_id,
                source=incoming,
                filename=task["filename"],
                page_text=page_text,
                safe_point=self._safe_point,
            )
            if page_analyses is None:
                return

            document_id = str(uuid.uuid4())
            self._commit_import(
                root,
                task_id,
                incoming,
                task["filename"],
                document_id,
                sha256,
                size,
                page_count,
                page_analyses,
            )
        except PermissionError:
            self._quarantine(root, incoming, task_id)
            self._fail(root, task_id, "PDF_PASSWORD_PROTECTED", "PDF 受密码保护", "移除密码后重试")
        except (PdfReadError, ValueError, EOFError) as exc:
            self._quarantine(root, incoming, task_id)
            self._fail(root, task_id, "PDF_CORRUPT", f"PDF 无法读取：{exc}", "检查原文件或跳过该项")
        except OSError as exc:
            self._fail(root, task_id, "LOCAL_IO_ERROR", f"本地文件处理失败：{exc}", "检查磁盘空间与目录权限后重试")
        except Exception:
            logger.exception("task.unexpected_processing_error", extra={"task_id": task_id})
            self._fail(
                root,
                task_id,
                "UNEXPECTED_PROCESSING_ERROR",
                "PDF 处理遇到未预期错误",
                "保留原文件并重试；若问题持续，请查看本地日志",
            )

    def _complete_duplicate(
        self, root: Path, task_id: str, incoming: Path, document_id: str
    ) -> None:
        outcome = "cancelled"
        with self.database.connect(root / "app.db") as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute(
                    "SELECT status, pause_reason FROM tasks WHERE id=?", (task_id,)
                ).fetchone()
                outcome = row["status"] if row else "cancelled"
                pause_reason = row["pause_reason"] if row else None
                if outcome == "pausing":
                    pause_reason = pause_reason or "user"
                    paused_step = (
                        CPU_PAUSED_STEP if pause_reason == "resource" else "已在安全点暂停"
                    )
                    db.execute(
                        """UPDATE tasks SET status='paused', current_step=?,
                        pause_reason=?, updated_at=? WHERE id=?""",
                        (paused_step, pause_reason, utc_now(), task_id),
                    )
                    outcome = "paused"
                elif outcome == "running":
                    db.execute(
                        """UPDATE tasks SET status='completed', progress=100,
                        current_step='已复用现有解析结果', result_kind='duplicate',
                        document_id=?, error_code=NULL, error_message=NULL, next_action=NULL,
                        pause_reason=NULL, updated_at=? WHERE id=? AND status='running'""",
                        (document_id, utc_now(), task_id),
                    )
                    outcome = "completed"
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        if outcome == "completed":
            incoming.unlink(missing_ok=True)
            self.database.record_project_event(
                root, "task.completed", task_id=task_id, details={"result_kind": "duplicate"}
            )
            logger.info("task.completed", extra={"task_id": task_id, "status": "completed"})
        elif outcome == "paused":
            self.database.record_project_event(
                root,
                "task.paused",
                task_id=task_id,
                details={"pause_reason": pause_reason},
            )
        elif outcome == "cancelled":
            self._cleanup_cancelled(incoming, task_id)

    def _commit_import(
        self,
        root: Path,
        task_id: str,
        incoming: Path,
        filename: str,
        document_id: str,
        sha256: str,
        size: int,
        page_count: int,
        page_analyses: list[dict],
    ) -> None:
        destination = root / "files" / f"{document_id}.pdf"
        outcome = "cancelled"
        moved = False
        with self.database.connect(root / "app.db") as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute(
                    "SELECT status, pause_reason FROM tasks WHERE id=?", (task_id,)
                ).fetchone()
                outcome = row["status"] if row else "cancelled"
                pause_reason = row["pause_reason"] if row else None
                if outcome == "pausing":
                    pause_reason = pause_reason or "user"
                    paused_step = (
                        CPU_PAUSED_STEP if pause_reason == "resource" else "已在安全点暂停"
                    )
                    db.execute(
                        """UPDATE tasks SET status='paused', current_step=?,
                        pause_reason=?, updated_at=? WHERE id=?""",
                        (paused_step, pause_reason, utc_now(), task_id),
                    )
                    outcome = "paused"
                elif outcome == "running":
                    shutil.move(str(incoming), destination)
                    moved = True
                    now = utc_now()
                    scan_count = sum(
                        analysis["status"] != "not_required" for analysis in page_analyses
                    )
                    vision_count = sum(
                        analysis["status"] == "completed" for analysis in page_analyses
                    )
                    failed_count = sum(
                        analysis["status"] == "failed" for analysis in page_analyses
                    )
                    external_count = sum(
                        analysis["external_request"] for analysis in page_analyses
                    )
                    if not scan_count:
                        document_parse_method = "native_pdf"
                        completed_step = "本地解析完成"
                    elif vision_count == scan_count and scan_count == page_count:
                        if external_count:
                            document_parse_method = "paddleocr_vision"
                            completed_step = "PaddleOCR 页级结果已提交（合成联调）"
                        else:
                            document_parse_method = "fake_vision"
                            completed_step = "合成视觉页结果已提交"
                    elif vision_count == scan_count:
                        document_parse_method = "hybrid_pdf"
                        completed_step = (
                            "本地文本与 PaddleOCR 页级结果已提交（合成联调）"
                            if external_count
                            else "本地文本与合成视觉页结果已提交"
                        )
                    elif failed_count:
                        document_parse_method = "scan_detected"
                        completed_step = f"本地解析完成；{failed_count} 个扫描页视觉解析失败"
                    else:
                        document_parse_method = "scan_detected"
                        completed_step = "本地解析完成；扫描页等待视觉模型"
                    db.execute(
                        """INSERT INTO documents
                        (id, filename, sha256, size_bytes, page_count, parse_method, parse_version, stored_path, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, 'document-pipeline-v4', ?, ?)""",
                        (
                            document_id,
                            filename,
                            sha256,
                            size,
                            page_count,
                            document_parse_method,
                            str(destination),
                            now,
                        ),
                    )
                    for analysis in page_analyses:
                        for block_number, block in enumerate(analysis["blocks"], start=1):
                            page_id = str(uuid.uuid4())
                            block_text = block["text"]
                            db.execute(
                                """INSERT INTO pages
                                (id, document_id, page_number, block_number, original_text,
                                 parse_method, parse_version, source_text, bbox_json,
                                 page_width, page_height, block_kind, table_candidate_json)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                (
                                    page_id,
                                    document_id,
                                    analysis["page_number"],
                                    block_number,
                                    block_text,
                                    analysis["parse_method"],
                                    analysis["parse_version"],
                                    block_text,
                                    json.dumps(block["bbox"], ensure_ascii=False, sort_keys=True),
                                    analysis["page_width"],
                                    analysis["page_height"],
                                    block["block_kind"],
                                    json.dumps(
                                        block["table_candidate"],
                                        ensure_ascii=False,
                                        sort_keys=True,
                                    ),
                                ),
                            )
                            replace_page_chunks(
                                db,
                                page_id=page_id,
                                document_id=document_id,
                                page_number=analysis["page_number"],
                                block_number=block_number,
                                original_text=block_text,
                                parse_method=analysis["parse_method"],
                                parse_version=analysis["parse_version"],
                            )
                        db.execute(
                            """INSERT INTO page_vision_results
                            (id, document_id, page_number, status, provider_id,
                             model_profile_id, provider_name, actual_model, model_call_id,
                             schema_version, recognized_text, confidence, result_json,
                             image_sha256, external_request, error_code, error_message,
                             remote_request_id, remote_cleanup_status, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            vision_row_values(document_id, analysis),
                        )
                    db.execute(
                        """UPDATE tasks SET status='completed', progress=100,
                        current_step=?, result_kind='imported', document_id=?,
                        error_code=NULL, error_message=NULL, next_action=NULL,
                        pause_reason=NULL, updated_at=?
                        WHERE id=? AND status='running'""",
                        (completed_step, document_id, now, task_id),
                    )
                    outcome = "completed"
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                if moved and destination.exists() and not incoming.exists():
                    shutil.move(str(destination), incoming)
                raise
        if outcome == "completed":
            self.database.record_project_event(
                root,
                "task.completed",
                task_id=task_id,
                details={
                    "result_kind": "imported",
                    "document_id": document_id,
                    "scan_page_count": sum(
                        analysis["status"] != "not_required" for analysis in page_analyses
                    ),
                    "vision_page_count": sum(
                        analysis["status"] == "completed" for analysis in page_analyses
                    ),
                    "external_requests": sum(
                        analysis["external_request"] for analysis in page_analyses
                    ),
                },
            )
            logger.info("task.completed", extra={"task_id": task_id, "status": "completed"})
        elif outcome == "paused":
            self.database.record_project_event(
                root,
                "task.paused",
                task_id=task_id,
                details={"pause_reason": pause_reason},
            )
        elif outcome == "cancelled":
            self._cleanup_cancelled(incoming, task_id)

    def _quarantine(self, root: Path, incoming: Path, task_id: str) -> None:
        if incoming.exists():
            destination = root / "quarantine" / f"{task_id}.pdf"
            if incoming.resolve() != destination.resolve():
                shutil.move(str(incoming), destination)
            self._update_task(root, task_id, incoming_path=str(destination))
