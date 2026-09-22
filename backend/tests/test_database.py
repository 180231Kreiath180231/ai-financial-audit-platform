from pathlib import Path

import pytest

from backend.app.db import Database
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
