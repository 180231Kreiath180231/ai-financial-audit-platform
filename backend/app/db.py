from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .migrations import PROJECT_MIGRATIONS, REGISTRY_MIGRATIONS, apply_migrations
from .schemas import ModelProfileCreate, ModelProviderCreate, ProjectCreate
from .secret_store import DpapiSecretStore

CAPABILITY_COLUMNS = {
    "text": "supports_text",
    "vision": "supports_vision",
    "json_schema": "supports_json_schema",
    "tools": "supports_tools",
    "embedding": "supports_embedding",
    "file_upload": "supports_file_upload",
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class ProjectStorageUnavailable(RuntimeError):
    pass


class Database:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.registry_path = data_dir / "registry.db"
        self.secret_store = DpapiSecretStore(data_dir / "secrets")
        self._init_registry()
        self._seed_gateway_defaults()

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
            apply_migrations(db, "registry", REGISTRY_MIGRATIONS)

    def _seed_gateway_defaults(self) -> None:
        now = utc_now()
        with self.connect(self.registry_path) as db:
            db.execute(
                """INSERT OR IGNORE INTO model_providers
                (id, provider_kind, display_name, base_url, api_key_ref, default_headers_json,
                 timeout_seconds, max_retries, enabled, created_at, updated_at)
                VALUES ('fake-provider', 'fake', 'Fake Provider', 'local://fake', NULL, '{}',
                        1, 0, 1, ?, ?)""",
                (now, now),
            )
            db.execute(
                """INSERT OR IGNORE INTO model_profiles
                (id, provider_id, display_name, model_name, supports_text, supports_vision,
                 supports_json_schema, supports_tools, supports_embedding, supports_file_upload,
                 context_window, max_output_tokens, input_cost_per_million,
                 output_cost_per_million, is_fallback, enabled, created_at, updated_at)
                VALUES ('fake-structured-v1', 'fake-provider', 'Fake Structured Model',
                        'fake-structured-v1', 1, 1, 1, 1, 1, 0, 32768, 4096,
                        '0', '0', 0, 1, ?, ?)""",
                (now, now),
            )

    def init_project_db(self, root: Path) -> None:
        for folder in ("files", "incoming", "quarantine", "exports"):
            (root / folder).mkdir(parents=True, exist_ok=True)
        with self.connect(root / "app.db") as db:
            apply_migrations(db, "project", PROJECT_MIGRATIONS)

    def record_project_event(
        self,
        root: Path,
        event_type: str,
        *,
        task_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        with self.connect(root / "app.db") as db:
            db.execute(
                "INSERT INTO audit_events VALUES (?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    task_id,
                    event_type,
                    utc_now(),
                    json.dumps(details or {}, ensure_ascii=False),
                ),
            )

    def create_project(self, payload: ProjectCreate, *, is_synthetic: bool = False) -> dict[str, Any]:
        project_id = str(uuid.uuid4())
        root = Path(payload.storage_path).expanduser().resolve()
        with self.connect(self.registry_path) as db:
            conflict = db.execute(
                "SELECT 1 FROM projects WHERE name = ? COLLATE NOCASE OR storage_path = ?",
                (payload.name, str(root)),
            ).fetchone()
        if conflict is not None:
            raise sqlite3.IntegrityError("project name or storage path already exists")
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
        result["external_access_enabled"] = bool(result["external_access_enabled"])
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
            project["external_access_enabled"] = bool(project["external_access_enabled"])
            try:
                project.update(self.project_counts(Path(project["storage_path"])))
                project["storage_available"] = True
                project["storage_error_code"] = None
            except (OSError, sqlite3.Error, ProjectStorageUnavailable):
                project.update(self.empty_project_counts())
                project["storage_available"] = False
                project["storage_error_code"] = "PROJECT_STORAGE_UNAVAILABLE"
            projects.append(project)
        return projects

    def strict_offline(self) -> bool:
        with self.connect(self.registry_path) as db:
            row = db.execute(
                "SELECT value_json FROM app_settings WHERE key='strict_offline'"
            ).fetchone()
        return True if row is None else bool(json.loads(row["value_json"]))

    def set_strict_offline(self, enabled: bool) -> None:
        now = utc_now()
        with self.connect(self.registry_path) as db:
            db.execute(
                """INSERT INTO app_settings(key, value_json, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,
                    updated_at=excluded.updated_at""",
                ("strict_offline", json.dumps(enabled), now),
            )
            db.execute(
                "INSERT INTO audit_events VALUES (?, NULL, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    "gateway.strict_offline_changed",
                    now,
                    json.dumps({"enabled": enabled}),
                ),
            )

    def set_project_external_access(self, project_id: str, enabled: bool) -> dict[str, Any]:
        now = utc_now()
        with self.connect(self.registry_path) as db:
            changed = db.execute(
                "UPDATE projects SET external_access_enabled=? WHERE id=? AND archived_at IS NULL",
                (int(enabled), project_id),
            )
            if changed.rowcount == 0:
                raise KeyError(project_id)
            db.execute(
                "INSERT INTO audit_events VALUES (?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    project_id,
                    "project.external_access_changed",
                    now,
                    json.dumps({"enabled": enabled}),
                ),
            )
        return self.get_project(project_id)

    def list_model_providers(self) -> list[dict[str, Any]]:
        with self.connect(self.registry_path) as db:
            rows = db.execute(
                "SELECT * FROM model_providers ORDER BY provider_kind, display_name"
            ).fetchall()
        return [self._provider_from_row(row) for row in rows]

    @staticmethod
    def _provider_from_row(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["secret_configured"] = bool(result.pop("api_key_ref"))
        result["default_headers"] = json.loads(result.pop("default_headers_json"))
        result["enabled"] = bool(result["enabled"])
        return result

    def create_model_provider(self, payload: ModelProviderCreate) -> dict[str, Any]:
        provider_id = str(uuid.uuid4())
        secret_ref = None
        if payload.api_key is not None:
            secret_ref = self.secret_store.put(payload.api_key.get_secret_value())
        now = utc_now()
        try:
            with self.connect(self.registry_path) as db:
                db.execute(
                    """INSERT INTO model_providers
                    (id, provider_kind, display_name, base_url, api_key_ref,
                     default_headers_json, timeout_seconds, max_retries, enabled,
                     created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        provider_id,
                        payload.provider_kind,
                        payload.display_name,
                        payload.base_url,
                        secret_ref,
                        json.dumps(payload.default_headers, ensure_ascii=False),
                        payload.timeout_seconds,
                        payload.max_retries,
                        int(payload.enabled),
                        now,
                        now,
                    ),
                )
                row = db.execute(
                    "SELECT * FROM model_providers WHERE id=?", (provider_id,)
                ).fetchone()
                db.execute(
                    "INSERT INTO audit_events VALUES (?, NULL, ?, ?, ?)",
                    (
                        str(uuid.uuid4()),
                        "gateway.provider_created",
                        now,
                        json.dumps(
                            {"provider_id": provider_id, "provider_kind": payload.provider_kind}
                        ),
                    ),
                )
        except Exception:
            self.secret_store.delete(secret_ref)
            raise
        return self._provider_from_row(row)

    def toggle_model_provider(self, provider_id: str) -> dict[str, Any]:
        if provider_id == "fake-provider":
            raise ValueError("Fake Provider must remain enabled")
        with self.connect(self.registry_path) as db:
            now = utc_now()
            changed = db.execute(
                "UPDATE model_providers SET enabled=1-enabled, updated_at=? WHERE id=?",
                (now, provider_id),
            )
            if changed.rowcount == 0:
                raise KeyError(provider_id)
            row = db.execute("SELECT * FROM model_providers WHERE id=?", (provider_id,)).fetchone()
            db.execute(
                "INSERT INTO audit_events VALUES (?, NULL, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    "gateway.provider_toggled",
                    now,
                    json.dumps({"provider_id": provider_id, "enabled": bool(row["enabled"])}),
                ),
            )
        return self._provider_from_row(row)

    def list_model_profiles(self) -> list[dict[str, Any]]:
        with self.connect(self.registry_path) as db:
            rows = db.execute(
                "SELECT * FROM model_profiles ORDER BY is_fallback, display_name"
            ).fetchall()
        return [self._model_from_row(row) for row in rows]

    @staticmethod
    def _model_from_row(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["capabilities"] = [
            capability
            for capability, column in CAPABILITY_COLUMNS.items()
            if bool(result.pop(column))
        ]
        for key in ("is_fallback", "enabled"):
            result[key] = bool(result[key])
        return result

    def create_model_profile(self, payload: ModelProfileCreate) -> dict[str, Any]:
        model_id = str(uuid.uuid4())
        now = utc_now()
        flags = {column: int(capability in payload.capabilities) for capability, column in CAPABILITY_COLUMNS.items()}
        with self.connect(self.registry_path) as db:
            provider = db.execute(
                "SELECT 1 FROM model_providers WHERE id=?", (payload.provider_id,)
            ).fetchone()
            if provider is None:
                raise KeyError(payload.provider_id)
            db.execute(
                """INSERT INTO model_profiles
                (id, provider_id, display_name, model_name, supports_text, supports_vision,
                 supports_json_schema, supports_tools, supports_embedding, supports_file_upload,
                 context_window, max_output_tokens, input_cost_per_million,
                 output_cost_per_million, is_fallback, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    model_id,
                    payload.provider_id,
                    payload.display_name,
                    payload.model_name,
                    flags["supports_text"],
                    flags["supports_vision"],
                    flags["supports_json_schema"],
                    flags["supports_tools"],
                    flags["supports_embedding"],
                    flags["supports_file_upload"],
                    payload.context_window,
                    payload.max_output_tokens,
                    str(payload.input_cost_per_million),
                    str(payload.output_cost_per_million),
                    int(payload.is_fallback),
                    int(payload.enabled),
                    now,
                    now,
                ),
            )
            row = db.execute("SELECT * FROM model_profiles WHERE id=?", (model_id,)).fetchone()
            db.execute(
                "INSERT INTO audit_events VALUES (?, NULL, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    "gateway.model_created",
                    now,
                    json.dumps({"model_profile_id": model_id, "provider_id": payload.provider_id}),
                ),
            )
        return self._model_from_row(row)

    def toggle_model_profile(self, model_id: str) -> dict[str, Any]:
        if model_id == "fake-structured-v1":
            raise ValueError("Fake model must remain enabled")
        with self.connect(self.registry_path) as db:
            now = utc_now()
            changed = db.execute(
                "UPDATE model_profiles SET enabled=1-enabled, updated_at=? WHERE id=?",
                (now, model_id),
            )
            if changed.rowcount == 0:
                raise KeyError(model_id)
            row = db.execute("SELECT * FROM model_profiles WHERE id=?", (model_id,)).fetchone()
            db.execute(
                "INSERT INTO audit_events VALUES (?, NULL, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    "gateway.model_toggled",
                    now,
                    json.dumps({"model_profile_id": model_id, "enabled": bool(row["enabled"])}),
                ),
            )
        return self._model_from_row(row)

    def recent_model_calls(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect(self.registry_path) as db:
            rows = db.execute(
                """SELECT id, project_id, provider_id, model_profile_id, capability,
                started_at, completed_at, status, error_code
                FROM model_calls ORDER BY started_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def empty_project_counts() -> dict[str, int]:
        return {
            "document_count": 0,
            "page_count": 0,
            "queued_count": 0,
            "running_count": 0,
            "failed_count": 0,
            "completed_count": 0,
        }

    def project_counts(self, root: Path) -> dict[str, int]:
        database_path = root / "app.db"
        if not root.is_dir() or not database_path.is_file():
            raise ProjectStorageUnavailable(str(root))
        with self.connect(database_path) as db:
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
        root = Path(self.get_project(project_id)["storage_path"])
        if not root.is_dir() or not (root / "app.db").is_file():
            raise ProjectStorageUnavailable(str(root))
        return root

    def recover_tasks(self) -> None:
        for project in self.list_projects():
            if not project["storage_available"]:
                continue
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
