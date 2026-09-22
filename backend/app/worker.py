from __future__ import annotations

import asyncio
import hashlib
import shutil
import uuid
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .db import Database, utc_now


class LocalTaskWorker:
    """Single persistent worker. Every step is safe to retry."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self._stopping = False

    def stop(self) -> None:
        self._stopping = True

    async def run(self) -> None:
        while not self._stopping:
            claimed = await asyncio.to_thread(self._claim_next)
            if claimed is None:
                await asyncio.sleep(0.25)
                continue
            project_root, task_id = claimed
            await asyncio.to_thread(self._process, project_root, task_id)

    def _claim_next(self) -> tuple[Path, str] | None:
        for project in self.database.list_projects():
            root = Path(project["storage_path"])
            with self.database.connect(root / "app.db") as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT id FROM tasks WHERE status='queued' ORDER BY created_at LIMIT 1"
                ).fetchone()
                if row is None:
                    db.execute("COMMIT")
                    continue
                changed = db.execute(
                    """UPDATE tasks SET status='running', progress=5,
                    current_step='计算文件哈希', updated_at=? WHERE id=? AND status='queued'""",
                    (utc_now(), row["id"]),
                ).rowcount
                db.execute("COMMIT")
                if changed:
                    return root, row["id"]
        return None

    def _task_status(self, root: Path, task_id: str) -> str:
        with self.database.connect(root / "app.db") as db:
            row = db.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
        return row["status"] if row else "cancelled"

    def _safe_point(self, root: Path, task_id: str) -> bool:
        status = self._task_status(root, task_id)
        if status == "pausing":
            self._update_task(root, task_id, status="paused", current_step="已在安全点暂停")
            return False
        return status == "running"

    def _update_task(self, root: Path, task_id: str, **fields) -> None:
        fields["updated_at"] = utc_now()
        assignments = ", ".join(f"{key}=?" for key in fields)
        with self.database.connect(root / "app.db") as db:
            db.execute(
                f"UPDATE tasks SET {assignments} WHERE id=?",
                (*fields.values(), task_id),
            )

    def _fail(self, root: Path, task_id: str, code: str, message: str, action: str) -> None:
        self._update_task(
            root,
            task_id,
            status="failed",
            current_step="处理失败",
            error_code=code,
            error_message=message,
            next_action=action,
        )

    def _process(self, root: Path, task_id: str) -> None:
        with self.database.connect(root / "app.db") as db:
            task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if task is None:
            return
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
            if not self._safe_point(root, task_id):
                return

            with self.database.connect(root / "app.db") as db:
                duplicate = db.execute(
                    "SELECT id FROM documents WHERE sha256=?", (sha256,)
                ).fetchone()
            if duplicate:
                incoming.unlink(missing_ok=True)
                self._update_task(
                    root,
                    task_id,
                    status="completed",
                    progress=100,
                    current_step="已复用现有解析结果",
                    result_kind="duplicate",
                    document_id=duplicate["id"],
                )
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
            if not self._safe_point(root, task_id):
                return
            page_text: list[str] = []
            for page in reader.pages:
                page_text.append(page.extract_text() or "")

            document_id = str(uuid.uuid4())
            destination = root / "files" / f"{document_id}.pdf"
            shutil.move(str(incoming), destination)
            now = utc_now()
            with self.database.connect(root / "app.db") as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    """INSERT INTO documents
                    (id, filename, sha256, size_bytes, page_count, parse_method, parse_version, stored_path, created_at)
                    VALUES (?, ?, ?, ?, ?, 'native_pdf', 'pypdf-v1', ?, ?)""",
                    (
                        document_id,
                        task["filename"],
                        sha256,
                        size,
                        page_count,
                        str(destination),
                        now,
                    ),
                )
                for index, text in enumerate(page_text, start=1):
                    db.execute(
                        """INSERT INTO pages
                        (id, document_id, page_number, block_number, original_text, parse_method, parse_version)
                        VALUES (?, ?, ?, 1, ?, 'native_pdf', 'pypdf-v1')""",
                        (str(uuid.uuid4()), document_id, index, text),
                    )
                db.execute("COMMIT")
            self._update_task(
                root,
                task_id,
                status="completed",
                progress=100,
                current_step="本地解析完成",
                result_kind="imported",
                document_id=document_id,
            )
        except PermissionError:
            self._quarantine(root, incoming, task_id)
            self._fail(root, task_id, "PDF_PASSWORD_PROTECTED", "PDF 受密码保护", "移除密码后重试")
        except (PdfReadError, ValueError, EOFError) as exc:
            self._quarantine(root, incoming, task_id)
            self._fail(root, task_id, "PDF_CORRUPT", f"PDF 无法读取：{exc}", "检查原文件或跳过该项")
        except OSError as exc:
            self._fail(root, task_id, "LOCAL_IO_ERROR", f"本地文件处理失败：{exc}", "检查磁盘空间与目录权限后重试")

    def _quarantine(self, root: Path, incoming: Path, task_id: str) -> None:
        if incoming.exists():
            destination = root / "quarantine" / f"{task_id}.pdf"
            shutil.move(str(incoming), destination)
