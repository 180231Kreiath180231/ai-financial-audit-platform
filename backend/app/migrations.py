from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence

Migration = tuple[int, str, Callable[[sqlite3.Connection], None]]


def _registry_v1(db: sqlite3.Connection) -> None:
    db.execute(
        """CREATE TABLE IF NOT EXISTS projects (
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
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS audit_events (
            id TEXT PRIMARY KEY,
            project_id TEXT,
            event_type TEXT NOT NULL,
            created_at TEXT NOT NULL,
            details_json TEXT NOT NULL
        )"""
    )


def _registry_v2(db: sqlite3.Connection) -> None:
    project_columns = {
        row[1] for row in db.execute("PRAGMA table_info(projects)").fetchall()
    }
    if "external_access_enabled" not in project_columns:
        db.execute(
            "ALTER TABLE projects ADD COLUMN external_access_enabled INTEGER NOT NULL DEFAULT 0"
        )
    db.execute(
        """CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS model_providers (
            id TEXT PRIMARY KEY,
            provider_kind TEXT NOT NULL,
            display_name TEXT NOT NULL COLLATE NOCASE UNIQUE,
            base_url TEXT NOT NULL,
            api_key_ref TEXT,
            default_headers_json TEXT NOT NULL DEFAULT '{}',
            timeout_seconds INTEGER NOT NULL,
            max_retries INTEGER NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS model_profiles (
            id TEXT PRIMARY KEY,
            provider_id TEXT NOT NULL REFERENCES model_providers(id),
            display_name TEXT NOT NULL,
            model_name TEXT NOT NULL,
            supports_text INTEGER NOT NULL DEFAULT 0,
            supports_vision INTEGER NOT NULL DEFAULT 0,
            supports_json_schema INTEGER NOT NULL DEFAULT 0,
            supports_tools INTEGER NOT NULL DEFAULT 0,
            supports_embedding INTEGER NOT NULL DEFAULT 0,
            supports_file_upload INTEGER NOT NULL DEFAULT 0,
            context_window INTEGER NOT NULL,
            max_output_tokens INTEGER NOT NULL,
            input_cost_per_million TEXT NOT NULL DEFAULT '0',
            output_cost_per_million TEXT NOT NULL DEFAULT '0',
            is_fallback INTEGER NOT NULL DEFAULT 0,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(provider_id, model_name)
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS model_calls (
            id TEXT PRIMARY KEY,
            project_id TEXT,
            task_id TEXT,
            provider_id TEXT,
            model_profile_id TEXT,
            capability TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            duration_ms INTEGER,
            evidence_refs_json TEXT NOT NULL DEFAULT '[]',
            request_summary TEXT NOT NULL,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            estimated_cost TEXT NOT NULL DEFAULT '0',
            cache_hit INTEGER NOT NULL DEFAULT 0,
            retry_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL,
            error_code TEXT
        )"""
    )
    db.execute(
        "INSERT OR IGNORE INTO app_settings(key, value_json, updated_at) VALUES ('strict_offline', 'true', CURRENT_TIMESTAMP)"
    )


def _registry_v3(db: sqlite3.Connection) -> None:
    call_columns = {
        row[1] for row in db.execute("PRAGMA table_info(model_calls)").fetchall()
    }
    if "route_role" not in call_columns:
        db.execute(
            "ALTER TABLE model_calls ADD COLUMN route_role TEXT NOT NULL DEFAULT 'primary'"
        )
    if "fallback_from_model_profile_id" not in call_columns:
        db.execute(
            "ALTER TABLE model_calls ADD COLUMN fallback_from_model_profile_id TEXT"
        )
    db.execute(
        """CREATE TABLE IF NOT EXISTS cache_entries (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            model_profile_id TEXT NOT NULL REFERENCES model_profiles(id) ON DELETE CASCADE,
            capability TEXT NOT NULL,
            request_fingerprint TEXT NOT NULL UNIQUE,
            prompt_hash TEXT NOT NULL,
            evidence_hash TEXT NOT NULL,
            response_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_hit_at TEXT,
            hit_count INTEGER NOT NULL DEFAULT 0
        )"""
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_cache_project_created ON cache_entries(project_id, created_at DESC)"
    )
    db.execute(
        "INSERT OR IGNORE INTO app_settings(key, value_json, updated_at) VALUES ('model_cache_enabled', 'true', CURRENT_TIMESTAMP)"
    )


def _project_v1(db: sqlite3.Connection) -> None:
    db.execute(
        """CREATE TABLE IF NOT EXISTS documents (
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
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS pages (
            id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL REFERENCES documents(id),
            page_number INTEGER NOT NULL,
            block_number INTEGER NOT NULL,
            original_text TEXT NOT NULL,
            parse_method TEXT NOT NULL,
            parse_version TEXT NOT NULL,
            UNIQUE(document_id, page_number, block_number)
        )"""
    )
    db.execute(
        """CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
            original_text,
            content='pages',
            content_rowid='rowid'
        )"""
    )
    db.execute(
        """CREATE TRIGGER IF NOT EXISTS pages_ai AFTER INSERT ON pages BEGIN
            INSERT INTO pages_fts(rowid, original_text) VALUES (new.rowid, new.original_text);
        END"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS tasks (
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
        )"""
    )
    db.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status_created ON tasks(status, created_at)")
    db.execute(
        """CREATE TABLE IF NOT EXISTS audit_events (
            id TEXT PRIMARY KEY,
            task_id TEXT,
            event_type TEXT NOT NULL,
            created_at TEXT NOT NULL,
            details_json TEXT NOT NULL
        )"""
    )


REGISTRY_MIGRATIONS: Sequence[Migration] = (
    (1, "initial_registry", _registry_v1),
    (2, "model_gateway", _registry_v2),
    (3, "model_gateway_fallback_cache", _registry_v3),
)
PROJECT_MIGRATIONS: Sequence[Migration] = ((1, "initial_project", _project_v1),)


def apply_migrations(
    db: sqlite3.Connection, scope: str, migrations: Sequence[Migration]
) -> None:
    db.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
            scope TEXT NOT NULL,
            version INTEGER NOT NULL,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (scope, version)
        )"""
    )
    applied = {
        row[0]
        for row in db.execute(
            "SELECT version FROM schema_migrations WHERE scope = ?", (scope,)
        ).fetchall()
    }
    for version, name, migrate in migrations:
        if version in applied:
            continue
        db.execute("BEGIN IMMEDIATE")
        try:
            migrate(db)
            db.execute(
                "INSERT INTO schema_migrations(scope, version, name) VALUES (?, ?, ?)",
                (scope, version, name),
            )
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
