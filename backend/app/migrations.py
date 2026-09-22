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


REGISTRY_MIGRATIONS: Sequence[Migration] = ((1, "initial_registry", _registry_v1),)
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
