import sqlite3
from pathlib import Path

from backend.app.db import Database
from backend.app.migrations import REGISTRY_MIGRATIONS, apply_migrations
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
    ]
    assert [tuple(row) for row in project_versions] == [
        (1, "initial_project"),
        (2, "risk_evidence_versions"),
    ]
    assert {
        "documents",
        "pages",
        "tasks",
        "risk_items",
        "risk_evidence",
        "risk_versions",
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
    assert [row["version"] for row in versions] == [1, 2]


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
    assert [row["version"] for row in versions] == [1, 2, 3]
    assert "external_access_enabled" in columns
    assert {
        "app_settings",
        "model_providers",
        "model_profiles",
        "model_calls",
        "cache_entries",
    } <= tables
