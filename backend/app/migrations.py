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


def _registry_v4(db: sqlite3.Connection) -> None:
    call_columns = {
        row[1] for row in db.execute("PRAGMA table_info(model_calls)").fetchall()
    }
    if "remote_request_id" not in call_columns:
        db.execute("ALTER TABLE model_calls ADD COLUMN remote_request_id TEXT")
    if "remote_cleanup_status" not in call_columns:
        db.execute(
            "ALTER TABLE model_calls ADD COLUMN remote_cleanup_status TEXT NOT NULL DEFAULT 'not_applicable'"
        )
    if "data_scope_json" not in call_columns:
        db.execute(
            "ALTER TABLE model_calls ADD COLUMN data_scope_json TEXT NOT NULL DEFAULT '{}'"
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


def _project_v2(db: sqlite3.Connection) -> None:
    db.execute(
        """CREATE TABLE IF NOT EXISTS risk_items (
            id TEXT PRIMARY KEY,
            risk_number TEXT NOT NULL UNIQUE,
            risk_type TEXT NOT NULL,
            risk_level TEXT NOT NULL CHECK(risk_level IN ('高', '中', '低', '待评估')),
            status TEXT NOT NULL CHECK(status IN ('待复核', '已核实', '已排除', '待补证', '已关闭')),
            summary TEXT NOT NULL,
            trigger_rule_id TEXT NOT NULL,
            trigger_rule_version TEXT NOT NULL,
            input_values_json TEXT NOT NULL DEFAULT '{}',
            baseline_values_json TEXT NOT NULL DEFAULT '{}',
            calculation_result_json TEXT NOT NULL DEFAULT '{}',
            model_explanation TEXT,
            uncertainty TEXT NOT NULL,
            human_opinion TEXT NOT NULL DEFAULT '',
            model_provider TEXT,
            actual_model TEXT,
            model_call_id TEXT,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS risk_evidence (
            id TEXT PRIMARY KEY,
            risk_id TEXT NOT NULL REFERENCES risk_items(id) ON DELETE CASCADE,
            document_id TEXT NOT NULL REFERENCES documents(id),
            page_number INTEGER NOT NULL,
            block_number INTEGER NOT NULL,
            quote TEXT NOT NULL,
            direction TEXT NOT NULL CHECK(direction IN ('support', 'counter')),
            parse_method TEXT NOT NULL,
            parse_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(risk_id, document_id, page_number, block_number, direction)
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS risk_versions (
            id TEXT PRIMARY KEY,
            risk_id TEXT NOT NULL REFERENCES risk_items(id) ON DELETE CASCADE,
            version INTEGER NOT NULL,
            snapshot_json TEXT NOT NULL,
            change_reason TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(risk_id, version)
        )"""
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_risk_items_status_updated ON risk_items(status, updated_at DESC)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_risk_evidence_risk_direction ON risk_evidence(risk_id, direction)"
    )


def _project_v3(db: sqlite3.Connection) -> None:
    db.execute(
        """CREATE TABLE IF NOT EXISTS financial_datasets (
            id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            sha256 TEXT NOT NULL UNIQUE,
            size_bytes INTEGER NOT NULL,
            source_path TEXT NOT NULL,
            encoding TEXT NOT NULL,
            period_type TEXT NOT NULL CHECK(period_type IN ('monthly', 'annual')),
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            row_count INTEGER NOT NULL,
            currency TEXT NOT NULL,
            amount_unit TEXT NOT NULL DEFAULT '元',
            status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'archived')),
            created_at TEXT NOT NULL,
            archived_at TEXT
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS financial_import_previews (
            id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            stored_path TEXT NOT NULL,
            encoding TEXT NOT NULL,
            period_type TEXT NOT NULL,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            row_count INTEGER NOT NULL,
            currency TEXT NOT NULL,
            extra_columns_json TEXT NOT NULL DEFAULT '[]',
            warnings_json TEXT NOT NULL DEFAULT '[]',
            sample_rows_json TEXT NOT NULL DEFAULT '[]',
            duplicate_dataset_id TEXT REFERENCES financial_datasets(id),
            created_at TEXT NOT NULL,
            confirmed_at TEXT
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS financial_rule_runs (
            id TEXT PRIMARY KEY,
            dataset_id TEXT NOT NULL REFERENCES financial_datasets(id),
            rule_set_version TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('running', 'completed', 'failed')),
            passed_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            unavailable_count INTEGER NOT NULL DEFAULT 0,
            error_code TEXT,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            UNIQUE(dataset_id, rule_set_version)
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS financial_risk_evidence (
            id TEXT PRIMARY KEY,
            risk_id TEXT NOT NULL REFERENCES risk_items(id) ON DELETE CASCADE,
            dataset_id TEXT NOT NULL REFERENCES financial_datasets(id),
            line_start INTEGER NOT NULL,
            line_end INTEGER NOT NULL,
            period_key TEXT NOT NULL,
            account_code TEXT,
            quote TEXT NOT NULL,
            direction TEXT NOT NULL DEFAULT 'support' CHECK(direction IN ('support', 'counter')),
            created_at TEXT NOT NULL,
            UNIQUE(risk_id, dataset_id, line_start, line_end, direction)
        )"""
    )
    task_columns = {row[1] for row in db.execute("PRAGMA table_info(tasks)").fetchall()}
    if "dataset_id" not in task_columns:
        db.execute("ALTER TABLE tasks ADD COLUMN dataset_id TEXT")
    risk_columns = {
        row[1] for row in db.execute("PRAGMA table_info(risk_items)").fetchall()
    }
    if "source_rule_result_id" not in risk_columns:
        db.execute("ALTER TABLE risk_items ADD COLUMN source_rule_result_id TEXT")
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_risk_source_rule_result ON risk_items(source_rule_result_id) WHERE source_rule_result_id IS NOT NULL"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_financial_datasets_status_created ON financial_datasets(status, created_at DESC)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_financial_rule_runs_dataset ON financial_rule_runs(dataset_id, created_at DESC)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_financial_evidence_risk ON financial_risk_evidence(risk_id)"
    )


def _project_v4(db: sqlite3.Connection) -> None:
    db.execute(
        """CREATE TABLE IF NOT EXISTS page_vision_results (
            id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            page_number INTEGER NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('not_required', 'completed', 'requires_vision', 'failed')),
            provider_id TEXT,
            model_profile_id TEXT,
            provider_name TEXT,
            actual_model TEXT,
            model_call_id TEXT,
            schema_version TEXT NOT NULL,
            recognized_text TEXT NOT NULL DEFAULT '',
            confidence REAL,
            result_json TEXT NOT NULL DEFAULT '{}',
            image_sha256 TEXT,
            external_request INTEGER NOT NULL DEFAULT 0 CHECK(external_request IN (0, 1)),
            error_code TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(document_id, page_number)
        )"""
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_page_vision_document_status ON page_vision_results(document_id, status, page_number)"
    )


def _project_v5(db: sqlite3.Connection) -> None:
    vision_columns = {
        row[1] for row in db.execute("PRAGMA table_info(page_vision_results)").fetchall()
    }
    if "remote_request_id" not in vision_columns:
        db.execute("ALTER TABLE page_vision_results ADD COLUMN remote_request_id TEXT")
    if "remote_cleanup_status" not in vision_columns:
        db.execute(
            "ALTER TABLE page_vision_results ADD COLUMN remote_cleanup_status TEXT NOT NULL DEFAULT 'not_applicable'"
        )


def _project_v6(db: sqlite3.Connection) -> None:
    """Rebuild the derived full-text index for CJK substring search."""
    db.execute("DROP TRIGGER IF EXISTS pages_ai")
    db.execute("DROP TRIGGER IF EXISTS pages_ad")
    db.execute("DROP TRIGGER IF EXISTS pages_au")
    db.execute("DROP TABLE IF EXISTS pages_fts")
    db.execute(
        """CREATE VIRTUAL TABLE pages_fts USING fts5(
            original_text,
            content='pages',
            content_rowid='rowid',
            tokenize='trigram'
        )"""
    )
    db.execute("INSERT INTO pages_fts(pages_fts) VALUES ('rebuild')")
    db.execute(
        """CREATE TRIGGER pages_ai AFTER INSERT ON pages BEGIN
            INSERT INTO pages_fts(rowid, original_text) VALUES (new.rowid, new.original_text);
        END"""
    )
    db.execute(
        """CREATE TRIGGER pages_ad AFTER DELETE ON pages BEGIN
            INSERT INTO pages_fts(pages_fts, rowid, original_text)
            VALUES ('delete', old.rowid, old.original_text);
        END"""
    )
    db.execute(
        """CREATE TRIGGER pages_au AFTER UPDATE OF original_text ON pages BEGIN
            INSERT INTO pages_fts(pages_fts, rowid, original_text)
            VALUES ('delete', old.rowid, old.original_text);
            INSERT INTO pages_fts(rowid, original_text) VALUES (new.rowid, new.original_text);
        END"""
    )


REGISTRY_MIGRATIONS: Sequence[Migration] = (
    (1, "initial_registry", _registry_v1),
    (2, "model_gateway", _registry_v2),
    (3, "model_gateway_fallback_cache", _registry_v3),
    (4, "external_request_lifecycle_audit", _registry_v4),
)
PROJECT_MIGRATIONS: Sequence[Migration] = (
    (1, "initial_project", _project_v1),
    (2, "risk_evidence_versions", _project_v2),
    (3, "financial_datasets_and_rules", _project_v3),
    (4, "scanned_page_vision_results", _project_v4),
    (5, "scanned_page_remote_lifecycle", _project_v5),
    (6, "cjk_trigram_full_text_index", _project_v6),
)


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
