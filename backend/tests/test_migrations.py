import sqlite3
from pathlib import Path

from backend.app.db import Database
from backend.app.migrations import PROJECT_MIGRATIONS, REGISTRY_MIGRATIONS, apply_migrations
from backend.tests.helpers import create_project


def test_registry_and_project_migrations_are_versioned_and_idempotent(tmp_path: Path) -> None:
    data_dir = tmp_path / "registry"
    database = Database(data_dir)
    project = create_project(database, tmp_path / "project")
    root = Path(project["storage_path"])

    database.init_project_db(root)
    reloaded = Database(data_dir)

    with reloaded.connect(reloaded.registry_path) as db:
        registry_versions = db.execute(
            "SELECT version, name FROM schema_migrations WHERE scope='registry'"
        ).fetchall()
    with reloaded.connect(root / "app.db") as db:
        project_versions = db.execute(
            "SELECT version, name FROM schema_migrations WHERE scope='project'"
        ).fetchall()
        tables = {
            row["name"]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }

    assert [tuple(row) for row in registry_versions] == [
        (1, "initial_registry"),
        (2, "model_gateway"),
        (3, "model_gateway_fallback_cache"),
        (4, "external_request_lifecycle_audit"),
    ]
    assert [tuple(row) for row in project_versions] == [
        (1, "initial_project"),
        (2, "risk_evidence_versions"),
        (3, "financial_datasets_and_rules"),
        (4, "scanned_page_vision_results"),
        (5, "scanned_page_remote_lifecycle"),
        (6, "cjk_trigram_full_text_index"),
        (7, "document_search_metadata"),
        (8, "retrieval_chunks_and_vector_versions"),
        (9, "immutable_output_snapshots"),
        (10, "output_drafts_and_exports"),
        (11, "deterministic_materials_and_interview_drafts"),
        (12, "word_output_exports"),
        (13, "external_vision_page_checkpoints"),
        (14, "pdf_output_exports"),
        (15, "resource_pause_reasons"),
        (16, "audit_notes"),
    ]
    assert {
        "documents",
        "pages",
        "tasks",
        "risk_items",
        "risk_evidence",
        "risk_versions",
        "financial_datasets",
        "financial_import_previews",
        "financial_rule_runs",
        "financial_risk_evidence",
        "page_vision_results",
        "document_metadata_versions",
        "retrieval_chunks",
        "vector_index_versions",
        "chunk_embeddings",
        "output_snapshots",
        "output_snapshot_risks",
        "output_drafts",
        "output_draft_versions",
        "output_exports",
        "task_page_checkpoints",
        "notes",
        "note_risks",
        "note_pages",
        "audit_events",
        "schema_migrations",
    } <= tables


def test_v1_migration_adopts_legacy_schema_without_losing_projects(tmp_path: Path) -> None:
    data_dir = tmp_path / "registry"
    database = Database(data_dir)
    project = create_project(database, tmp_path / "legacy-project")
    root = Path(project["storage_path"])

    with database.connect(database.registry_path) as db:
        db.execute("DELETE FROM schema_migrations WHERE scope='registry'")
    with database.connect(root / "app.db") as db:
        db.execute("DROP TABLE risk_versions")
        db.execute("DROP TABLE risk_evidence")
        db.execute("DROP TABLE risk_items")
        db.execute("DELETE FROM schema_migrations WHERE scope='project' AND version=2")

    adopted = Database(data_dir)

    assert adopted.get_project(project["id"])["name"] == project["name"]
    with adopted.connect(root / "app.db") as db:
        versions = db.execute(
            "SELECT version FROM schema_migrations WHERE scope='project'"
        ).fetchall()
    assert [row["version"] for row in versions] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]


def test_project_v15_backfills_existing_pauses_as_user_owned(tmp_path: Path) -> None:
    path = tmp_path / "legacy-pauses.db"
    connection = sqlite3.connect(path, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        apply_migrations(connection, "project", PROJECT_MIGRATIONS[:14])
        connection.execute(
            """INSERT INTO tasks
            (id, task_type, filename, incoming_path, status, progress, current_step,
             created_at, updated_at)
            VALUES ('paused-1', 'pdf_import', 'legacy.pdf', 'legacy.part', 'paused',
                    35, '已在安全点暂停', 'before', 'before')"""
        )

        apply_migrations(connection, "project", PROJECT_MIGRATIONS)
        row = connection.execute(
            "SELECT pause_reason FROM tasks WHERE id='paused-1'"
        ).fetchone()
    finally:
        connection.close()

    assert row["pause_reason"] == "user"


def test_registry_v1_upgrades_to_model_gateway_without_rebuild(tmp_path: Path) -> None:
    data_dir = tmp_path / "registry"
    data_dir.mkdir()
    connection = sqlite3.connect(data_dir / "registry.db", isolation_level=None)
    try:
        apply_migrations(connection, "registry", REGISTRY_MIGRATIONS[:1])
    finally:
        connection.close()

    upgraded = Database(data_dir)

    with upgraded.connect(upgraded.registry_path) as db:
        versions = db.execute(
            "SELECT version FROM schema_migrations WHERE scope='registry' ORDER BY version"
        ).fetchall()
        columns = {
            row["name"] for row in db.execute("PRAGMA table_info(projects)").fetchall()
        }
        tables = {
            row["name"]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    assert [row["version"] for row in versions] == [1, 2, 3, 4]
    assert "external_access_enabled" in columns
    assert {
        "app_settings",
        "model_providers",
        "model_profiles",
        "model_calls",
        "cache_entries",
    } <= tables


def test_project_v6_rebuilds_existing_pages_into_trigram_index(tmp_path: Path) -> None:
    path = tmp_path / "legacy-project.db"
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        apply_migrations(connection, "project", PROJECT_MIGRATIONS[:5])
        connection.execute(
            "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("doc-1", "合成审计报告.pdf", "a" * 64, 12, 1, "native_pdf", "v1", "x.pdf", "now"),
        )
        connection.execute(
            "INSERT INTO pages VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("page-1", "doc-1", 1, 1, "这是迁移前的合成审计证据。", "native_pdf", "v1"),
        )
        apply_migrations(connection, "project", PROJECT_MIGRATIONS)

        hit = connection.execute(
            "SELECT original_text FROM pages_fts WHERE pages_fts MATCH ?",
            ('"审计证据"',),
        ).fetchone()
    finally:
        connection.close()

    assert hit == ("这是迁移前的合成审计证据。",)


def test_project_v7_adds_nullable_metadata_without_guessing_values(tmp_path: Path) -> None:
    path = tmp_path / "legacy-project.db"
    connection = sqlite3.connect(path, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        apply_migrations(connection, "project", PROJECT_MIGRATIONS[:6])
        connection.execute(
            "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("doc-1", "合成资料.pdf", "b" * 64, 12, 1, "native_pdf", "v1", "x.pdf", "now"),
        )
        apply_migrations(connection, "project", PROJECT_MIGRATIONS)
        document = connection.execute(
            "SELECT fiscal_year, entity_name, document_type, account_names_json, metadata_version FROM documents"
        ).fetchone()
    finally:
        connection.close()

    assert tuple(document) == (None, None, None, "[]", 0)


def test_project_v8_backfills_traceable_chunks_without_creating_vectors(tmp_path: Path) -> None:
    path = tmp_path / "legacy-project.db"
    connection = sqlite3.connect(path, isolation_level=None)
    connection.row_factory = sqlite3.Row
    source = "这是迁移前的合成审计证据。" * 100
    try:
        apply_migrations(connection, "project", PROJECT_MIGRATIONS[:7])
        connection.execute(
            """INSERT INTO documents
            (id, filename, sha256, size_bytes, page_count, parse_method, parse_version,
             stored_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("doc-1", "合成资料.pdf", "c" * 64, 12, 2, "native_pdf", "v1", "x.pdf", "now"),
        )
        connection.executemany(
            "INSERT INTO pages VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("page-1", "doc-1", 1, 1, source, "native_pdf", "v1"),
                ("page-2", "doc-1", 2, 1, "   ", "native_pdf", "v1"),
            ],
        )

        apply_migrations(connection, "project", PROJECT_MIGRATIONS)
        chunks = connection.execute(
            """SELECT page_id, page_number, chunk_number, char_start, char_end, text,
            text_sha256, chunk_version FROM retrieval_chunks ORDER BY chunk_number"""
        ).fetchall()
        vector_count = connection.execute("SELECT COUNT(*) FROM vector_index_versions").fetchone()[0]
    finally:
        connection.close()

    assert len(chunks) == 2
    assert {row["page_id"] for row in chunks} == {"page-1"}
    assert all(row["text"] == source[row["char_start"] : row["char_end"]] for row in chunks)
    assert all(row["chunk_version"] == "char-window-v1" for row in chunks)
    assert vector_count == 0


def test_project_v11_adds_empty_sections_without_rewriting_existing_draft(tmp_path: Path) -> None:
    path = tmp_path / "legacy-project.db"
    connection = sqlite3.connect(path, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        apply_migrations(connection, "project", PROJECT_MIGRATIONS[:10])
        connection.execute(
            """INSERT INTO output_snapshots
            (id, output_kind, schema_version, template_version, risk_count,
             content_sha256, snapshot_json, created_at)
            VALUES ('snapshot-1', 'risk_register', 'v1', 'v1', 1, ?, '{}', 'now')""",
            ("a" * 64,),
        )
        connection.execute(
            """INSERT INTO output_drafts
            (id, snapshot_id, output_kind, status, version, title, notes, items_json,
             created_at, updated_at, finalized_at)
            VALUES ('draft-1', 'snapshot-1', 'risk_register', 'finalized', 2,
                    '旧草稿', '', '[]', 'before', 'before', 'before')"""
        )

        apply_migrations(connection, "project", PROJECT_MIGRATIONS)
        row = connection.execute(
            """SELECT version, title, materials_title, materials_json,
            interview_title, interview_json FROM output_drafts WHERE id='draft-1'"""
        ).fetchone()
    finally:
        connection.close()

    assert tuple(row) == (2, "旧草稿", "资料清单", "[]", "访谈提纲", "[]")


def test_project_v14_preserves_excel_and_word_exports_and_allows_pdf(tmp_path: Path) -> None:
    path = tmp_path / "legacy-project.db"
    connection = sqlite3.connect(path, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        apply_migrations(connection, "project", PROJECT_MIGRATIONS[:13])
        connection.execute(
            """INSERT INTO output_snapshots
            (id, output_kind, schema_version, template_version, risk_count,
             content_sha256, snapshot_json, created_at)
            VALUES ('snapshot-1', 'risk_register', 'v1', 'v1', 1, ?, '{}', 'now')""",
            ("a" * 64,),
        )
        connection.execute(
            """INSERT INTO output_drafts
            (id, snapshot_id, output_kind, status, version, title, notes, items_json,
             created_at, updated_at, finalized_at, materials_title, materials_json,
             interview_title, interview_json)
            VALUES ('draft-1', 'snapshot-1', 'risk_register', 'finalized', 1,
                    '草稿', '', '[]', 'now', 'now', 'now', '资料清单', '[]',
                    '访谈提纲', '[]')"""
        )
        connection.execute(
            """INSERT INTO output_draft_versions
            (draft_id, version, change_reason, draft_json, created_at)
            VALUES ('draft-1', 1, '最终固化输出草稿', '{}', 'now')"""
        )
        connection.execute(
            """INSERT INTO output_exports
            (id, draft_id, draft_version, snapshot_id, export_format, template_version,
             filename, stored_path, file_sha256, size_bytes, created_at)
            VALUES ('excel-1', 'draft-1', 1, 'snapshot-1', 'xlsx', 'excel-v1',
                    '风险清单.xlsx', 'exports/excel-1.xlsx', ?, 12, 'now')""",
            ("b" * 64,),
        )
        connection.execute(
            """INSERT INTO output_exports
            (id, draft_id, draft_version, snapshot_id, export_format, template_version,
             filename, stored_path, file_sha256, size_bytes, created_at)
            VALUES ('word-1', 'draft-1', 1, 'snapshot-1', 'docx', 'word-v1',
                    '审计工作成果.docx', 'exports/word-1.docx', ?, 12, 'later')""",
            ("c" * 64,),
        )

        apply_migrations(connection, "project", PROJECT_MIGRATIONS)
        preserved = connection.execute(
            "SELECT id, export_format, filename FROM output_exports ORDER BY id"
        ).fetchall()
        connection.execute(
            """INSERT INTO output_exports
            (id, draft_id, draft_version, snapshot_id, export_format, template_version,
             filename, stored_path, file_sha256, size_bytes, created_at)
            VALUES ('pdf-1', 'draft-1', 1, 'snapshot-1', 'pdf', 'pdf-v1',
                    '审计工作成果归档件.pdf', 'exports/pdf-1.pdf', ?, 12, 'latest')""",
            ("d" * 64,),
        )
        formats = connection.execute(
            "SELECT export_format FROM output_exports ORDER BY id"
        ).fetchall()
    finally:
        connection.close()

    assert [tuple(row) for row in preserved] == [
        ("excel-1", "xlsx", "风险清单.xlsx"),
        ("word-1", "docx", "审计工作成果.docx"),
    ]
    assert [row["export_format"] for row in formats] == ["xlsx", "pdf", "docx"]
