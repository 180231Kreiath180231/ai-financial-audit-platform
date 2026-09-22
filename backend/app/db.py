from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from .schemas import ProjectCreate


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.registry_path = data_dir / "registry.db"
        self._init_registry()

    @contextmanager
    def connect(self, path: Path) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
        finally:
            connection.close()

    def _init_registry(self) -> None:
        with self.connect(self.registry_path) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    entity_name TEXT NOT NULL,
                    year_start INTEGER NOT NULL,
                    year_end INTEGER NOT NULL,
                    storage_path TEXT NOT NULL UNIQUE,
                    model_profile TEXT NOT NULL,
                    is_synthetic INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    archived_at TEXT
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    project_id TEXT,
                    event_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    details_json TEXT NOT NULL
                );
                """
            )

    def init_project_db(self, root: Path) -> None:
        for folder in ("files", "incoming", "quarantine", "exports"):
            (root / folder).mkdir(parents=True, exist_ok=True)
        with self.connect(root / "app.db") as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    page_count INTEGER NOT NULL,
                    parse_method TEXT NOT NULL,
                    parse_version TEXT NOT NULL,
                    stored_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(sha256)
                );
                CREATE TABLE IF NOT EXISTS pages (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES documents(id),
                    page_number INTEGER NOT NULL,
                    block_number INTEGER NOT NULL,
                    original_text TEXT NOT NULL,
                    parse_method TEXT NOT NULL,
                    parse_version TEXT NOT NULL,
                    UNIQUE(document_id, page_number, block_number)
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
                    original_text,
                    content='pages',
                    content_rowid='rowid'
                );
                CREATE TRIGGER IF NOT EXISTS pages_ai AFTER INSERT ON pages BEGIN
                    INSERT INTO pages_fts(rowid, original_text) VALUES (new.rowid, new.original_text);
                END;
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    task_type TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    incoming_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    current_step TEXT NOT NULL,
                    error_code TEXT,
                    error_message TEXT,
                    next_action TEXT,
                    result_kind TEXT,
                    document_id TEXT REFERENCES documents(id),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_status_created ON tasks(status, created_at);
                """
            )

    def create_project(self, payload: ProjectCreate, *, is_synthetic: bool = False) -> dict[str, Any]:
        project_id = str(uuid.uuid4())
        root = Path(payload.storage_path).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".hengjian-write-test"
        try:
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            raise PermissionError(f"项目目录不可写：{root}") from exc
        self.init_project_db(root)
        now = utc_now()
        with self.connect(self.registry_path) as db:
            db.execute(
                """INSERT INTO projects
                (id, name, entity_name, year_start, year_end, storage_path, model_profile, is_synthetic, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    project_id,
                    payload.name,
                    payload.entity_name,
                    payload.year_start,
                    payload.year_end,
                    str(root),
                    payload.model_profile,
                    int(is_synthetic),
                    now,
                ),
            )
            db.execute(
                "INSERT INTO audit_events VALUES (?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    project_id,
                    "project.created",
                    now,
                    json.dumps({"synthetic": is_synthetic}, ensure_ascii=False),
                ),
            )
        return self.get_project(project_id)

    def get_project(self, project_id: str) -> dict[str, Any]:
        with self.connect(self.registry_path) as db:
            row = db.execute(
                "SELECT * FROM projects WHERE id = ? AND archived_at IS NULL", (project_id,)
            ).fetchone()
        if row is None:
            raise KeyError(project_id)
        result = dict(row)
        result["is_synthetic"] = bool(result["is_synthetic"])
        return result

    def list_projects(self) -> list[dict[str, Any]]:
        with self.connect(self.registry_path) as db:
            rows = db.execute(
                "SELECT * FROM projects WHERE archived_at IS NULL ORDER BY created_at DESC"
            ).fetchall()
        projects: list[dict[str, Any]] = []
        for row in rows:
            project = dict(row)
            project["is_synthetic"] = bool(project["is_synthetic"])
            project.update(self.project_counts(Path(project["storage_path"])))
            projects.append(project)
        return projects

    def project_counts(self, root: Path) -> dict[str, int]:
        with self.connect(root / "app.db") as db:
            doc = db.execute(
                "SELECT COUNT(*) count, COALESCE(SUM(page_count), 0) pages FROM documents"
            ).fetchone()
            tasks = {
                row["status"]: row["count"]
                for row in db.execute(
                    "SELECT status, COUNT(*) count FROM tasks GROUP BY status"
                ).fetchall()
            }
        return {
            "document_count": doc["count"],
            "page_count": doc["pages"],
            "queued_count": tasks.get("queued", 0),
            "running_count": tasks.get("running", 0) + tasks.get("pausing", 0),
            "failed_count": tasks.get("failed", 0),
            "completed_count": tasks.get("completed", 0),
        }

    def project_root(self, project_id: str) -> Path:
        return Path(self.get_project(project_id)["storage_path"])

    def recover_tasks(self) -> None:
        for project in self.list_projects():
            root = Path(project["storage_path"])
            with self.connect(root / "app.db") as db:
                db.execute(
                    "UPDATE tasks SET status='queued', current_step='等待恢复', updated_at=? WHERE status='running'",
                    (utc_now(),),
                )
                db.execute(
                    "UPDATE tasks SET status='paused', current_step='已在安全点暂停', updated_at=? WHERE status='pausing'",
                    (utc_now(),),
                )
