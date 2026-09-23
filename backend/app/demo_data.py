from __future__ import annotations

import shutil
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .db import Database, utc_now
from .financial_data import FinancialDataService, sha256_file

DEMO_PDF_FILENAMES = (
    "01_年度审计情况说明_合成.pdf",
    "02_销售合同与回款核对_合成.pdf",
    "03_扫描发票样本_合成.pdf",
)
DEMO_FINANCIAL_FILENAME = "04_科目余额表_2024_2025_合成.csv"
ACTIVE_TASK_STATUSES = ("queued", "running", "pausing", "paused", "retry_wait")


class DemoDataError(RuntimeError):
    def __init__(self, code: str, message: str, action: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.action = action


class DemoDataService:
    """Queue the checked-in synthetic fixtures without bypassing normal processing."""

    def __init__(
        self,
        database: Database,
        financial_data: FinancialDataService,
        fixture_dir: Path,
    ) -> None:
        self.database = database
        self.financial_data = financial_data
        self.fixture_dir = fixture_dir

    def load(self, project_id: str) -> dict[str, Any]:
        project = self.database.get_project(project_id)
        if not project["is_synthetic"]:
            raise DemoDataError(
                "DEMO_PROJECT_REQUIRED",
                "演示资料只能载入合成演示项目",
                "切换到标有“合成演示项目”的项目后重试",
            )

        sources = [self.fixture_dir / filename for filename in DEMO_PDF_FILENAMES]
        financial_source = self.fixture_dir / DEMO_FINANCIAL_FILENAME
        missing = [path.name for path in [*sources, financial_source] if not path.is_file()]
        if missing:
            raise DemoDataError(
                "DEMO_FIXTURES_MISSING",
                f"演示资料不完整：缺少 {', '.join(missing)}",
                "恢复仓库根目录的 mock资料 文件夹后重试",
            )

        root = self.database.project_root(project_id)
        queued_task_ids: list[str] = []
        reused_document_count = 0
        reused_task_count = 0

        for source in sources:
            outcome, task_id = self._queue_pdf(root, project_id, source)
            if outcome == "document":
                reused_document_count += 1
            elif outcome == "task":
                reused_task_count += 1
            elif task_id:
                queued_task_ids.append(task_id)

        financial_outcome, financial_task_id, reused_dataset_id = self._queue_financial(
            root,
            project_id,
            financial_source,
        )
        if financial_outcome == "task":
            reused_task_count += 1
        elif financial_task_id:
            queued_task_ids.append(financial_task_id)

        queued_count = len(queued_task_ids)
        if queued_count:
            message = f"已将 {queued_count} 项演示资料加入本地任务队列"
        else:
            message = "演示资料已存在，已复用当前项目数据"

        self.database.record_project_event(
            root,
            "demo_data.load_requested",
            details={
                "queued_task_count": queued_count,
                "reused_document_count": reused_document_count,
                "reused_task_count": reused_task_count,
                "reused_financial_dataset": bool(reused_dataset_id),
                "external_request": False,
            },
        )
        return {
            "queued_task_ids": queued_task_ids,
            "queued_task_count": queued_count,
            "reused_document_count": reused_document_count,
            "reused_task_count": reused_task_count,
            "reused_financial_dataset": bool(reused_dataset_id),
            "message": message,
            "external_request": False,
        }

    def _queue_pdf(
        self,
        root: Path,
        project_id: str,
        source: Path,
    ) -> tuple[str, str | None]:
        digest = sha256_file(source)
        placeholders = ",".join("?" for _ in ACTIVE_TASK_STATUSES)
        with self.database.connect(root / "app.db") as db:
            existing_document = db.execute(
                "SELECT id FROM documents WHERE sha256=?",
                (digest,),
            ).fetchone()
            if existing_document:
                return "document", None
            existing_task = db.execute(
                f"""SELECT id FROM tasks WHERE task_type='pdf_import' AND filename=?
                AND status IN ({placeholders}) ORDER BY created_at DESC LIMIT 1""",
                (source.name, *ACTIVE_TASK_STATUSES),
            ).fetchone()
            if existing_task:
                return "task", existing_task["id"]

        task_id = str(uuid.uuid4())
        incoming = root / "incoming" / f"{task_id}.part"
        shutil.copyfile(source, incoming)
        now = utc_now()
        try:
            with self.database.connect(root / "app.db") as db:
                db.execute(
                    """INSERT INTO tasks
                    (id, task_type, filename, incoming_path, status, progress,
                     current_step, created_at, updated_at)
                    VALUES (?, 'pdf_import', ?, ?, 'queued', 0, '等待单工作器', ?, ?)""",
                    (task_id, source.name, str(incoming), now, now),
                )
        except sqlite3.Error:
            incoming.unlink(missing_ok=True)
            raise
        self.database.record_project_event(root, "task.queued", task_id=task_id)
        return "queued", task_id

    def _queue_financial(
        self,
        root: Path,
        project_id: str,
        source: Path,
    ) -> tuple[str, str | None, str | None]:
        digest = sha256_file(source)
        placeholders = ",".join("?" for _ in ACTIVE_TASK_STATUSES)
        with self.database.connect(root / "app.db") as db:
            existing_dataset = db.execute(
                "SELECT id FROM financial_datasets WHERE sha256=?",
                (digest,),
            ).fetchone()
            if existing_dataset:
                return "dataset", None, existing_dataset["id"]
            existing_task = db.execute(
                f"""SELECT id FROM tasks WHERE task_type='trial_balance_import'
                AND filename=? AND status IN ({placeholders})
                ORDER BY created_at DESC LIMIT 1""",
                (source.name, *ACTIVE_TASK_STATUSES),
            ).fetchone()
            if existing_task:
                return "task", existing_task["id"], None

        preview_path = root / "incoming" / f"financial-preview-{uuid.uuid4()}.csv"
        shutil.copyfile(source, preview_path)
        try:
            preview = self.financial_data.preview(
                project_id,
                source.name,
                preview_path,
                digest,
            )
            if not preview["valid"] or not preview["preview_id"]:
                first_error = preview["errors"][0] if preview["errors"] else None
                raise DemoDataError(
                    "DEMO_FINANCIAL_INVALID",
                    first_error["message"] if first_error else "演示财务数据校验失败",
                    first_error["action"] if first_error else "检查合成 CSV 后重试",
                )
            confirmed = self.financial_data.confirm(project_id, preview["preview_id"])
        except Exception:
            preview_path.unlink(missing_ok=True)
            raise

        task = confirmed["task"]
        if task:
            return "queued", task["id"], None
        return "dataset", None, confirmed["reused_dataset_id"]
