import shutil
from pathlib import Path

import pytest

from backend.app.db import Database, ProjectStorageUnavailable
from backend.app.schemas import ProjectCreate


def payload(root: Path, name: str = "合成审计项目") -> ProjectCreate:
    return ProjectCreate(
        name=name,
        entity_name="合成测试主体",
        year_start=2023,
        year_end=2025,
        storage_path=str(root),
        model_profile="严格离线 / Fake Provider",
    )


def test_projects_use_isolated_databases(tmp_path: Path) -> None:
    database = Database(tmp_path / "registry")
    first = database.create_project(payload(tmp_path / "first", "项目一"), is_synthetic=True)
    second = database.create_project(payload(tmp_path / "second", "项目二"), is_synthetic=True)

    assert database.project_root(first["id"]) / "app.db" != database.project_root(second["id"]) / "app.db"
    assert (tmp_path / "first" / "app.db").exists()
    assert (tmp_path / "second" / "app.db").exists()


def test_duplicate_project_name_is_rejected(tmp_path: Path) -> None:
    database = Database(tmp_path / "registry")
    database.create_project(payload(tmp_path / "first"))

    with pytest.raises(Exception):
        database.create_project(payload(tmp_path / "second"))
    assert not (tmp_path / "second").exists()


def test_missing_project_storage_does_not_break_project_listing(tmp_path: Path) -> None:
    database = Database(tmp_path / "registry")
    project = database.create_project(payload(tmp_path / "project"))
    shutil.rmtree(tmp_path / "project")

    projects = database.list_projects()

    assert len(projects) == 1
    assert projects[0]["id"] == project["id"]
    assert projects[0]["storage_available"] is False
    assert projects[0]["storage_error_code"] == "PROJECT_STORAGE_UNAVAILABLE"
    assert projects[0]["document_count"] == 0
    database.recover_tasks()
    with pytest.raises(ProjectStorageUnavailable):
        database.project_root(project["id"])
