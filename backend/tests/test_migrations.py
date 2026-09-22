from pathlib import Path

from backend.app.db import Database
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

    assert [tuple(row) for row in registry_versions] == [(1, "initial_registry")]
    assert [tuple(row) for row in project_versions] == [(1, "initial_project")]
    assert {"documents", "pages", "tasks", "audit_events", "schema_migrations"} <= tables


def test_v1_migration_adopts_legacy_schema_without_losing_projects(tmp_path: Path) -> None:
    data_dir = tmp_path / "registry"
    database = Database(data_dir)
    project = create_project(database, tmp_path / "legacy-project")
    root = Path(project["storage_path"])

    with database.connect(database.registry_path) as db:
        db.execute("DELETE FROM schema_migrations WHERE scope='registry'")
    with database.connect(root / "app.db") as db:
        db.execute("DELETE FROM schema_migrations WHERE scope='project'")

    adopted = Database(data_dir)
    adopted.init_project_db(root)

    assert adopted.get_project(project["id"])["name"] == project["name"]
    with adopted.connect(root / "app.db") as db:
        versions = db.execute(
            "SELECT version FROM schema_migrations WHERE scope='project'"
        ).fetchall()
    assert [row["version"] for row in versions] == [1]
