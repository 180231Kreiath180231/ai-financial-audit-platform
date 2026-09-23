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
    assert [row["version"] for row in versions] == [1, 2, 3, 4, 5, 6, 7, 8]


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
