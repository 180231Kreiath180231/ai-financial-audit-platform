from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from backend.app.db import Database
from backend.tests.helpers import create_project
from scripts.manage_local_backup import (
    BackupError,
    create_backup,
    restore_backup,
    verify_backup,
)


def _project_paths(database: Database) -> dict[str, Path]:
    with sqlite3.connect(database.registry_path) as connection:
        return {
            str(row[0]): Path(str(row[1]))
            for row in connection.execute("SELECT id, storage_path FROM projects")
        }


def test_backup_verify_and_isolated_restore_preserve_registered_projects(tmp_path: Path) -> None:
    source_data = tmp_path / "source-data"
    database = Database(source_data)
    nested = create_project(database, source_data / "projects" / "nested", "嵌套项目")
    external = create_project(database, tmp_path / "external-project", "外部项目")
    database.set_strict_offline(False)

    nested_root = Path(nested["storage_path"])
    external_root = Path(external["storage_path"])
    (nested_root / "files" / "nested-source.pdf").write_bytes(b"synthetic nested PDF")
    (external_root / "derived" / "index.json").write_text(
        '{"synthetic": true}', encoding="utf-8"
    )
    (source_data / "secrets" / "synthetic-dpapi.bin").write_bytes(b"ciphertext-placeholder")

    backup_dir = tmp_path / "backup"
    manifest = create_backup(
        source_data,
        backup_dir,
        app_stopped_confirmed=True,
    )

    assert manifest["format"] == "hengjian-local-backup-v1"
    assert len(manifest["projects"]) == 2
    assert not (backup_dir / "application" / "projects" / "nested" / "app.db").exists()
    verification = verify_backup(backup_dir)
    assert verification["verified"] is True
    assert verification["projects"] == 2
    assert verification["files"] >= 5

    restored_data = tmp_path / "restored-data"
    restored_projects = tmp_path / "restored-projects"
    result = restore_backup(
        backup_dir,
        restored_data,
        restored_projects,
        app_stopped_confirmed=True,
    )

    assert result["restored"] is True
    restored_database = Database(restored_data)
    assert restored_database.strict_offline() is False
    restored_paths = _project_paths(restored_database)
    assert restored_paths[nested["id"]] == restored_projects / nested["id"]
    assert restored_paths[external["id"]] == restored_projects / external["id"]
    assert (
        restored_paths[nested["id"]] / "files" / "nested-source.pdf"
    ).read_bytes() == b"synthetic nested PDF"
    assert (
        restored_paths[external["id"]] / "derived" / "index.json"
    ).read_text(encoding="utf-8") == '{"synthetic": true}'
    assert (
        restored_data / "secrets" / "synthetic-dpapi.bin"
    ).read_bytes() == b"ciphertext-placeholder"
    assert all(project["storage_available"] for project in restored_database.list_projects())

    source_paths = _project_paths(database)
    assert source_paths[nested["id"]] == nested_root
    assert source_paths[external["id"]] == external_root


def test_backup_refuses_live_app_confirmation_and_existing_output(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    Database(data_dir)
    backup_dir = tmp_path / "backup"

    with pytest.raises(BackupError, match="confirm-app-stopped"):
        create_backup(data_dir, backup_dir, app_stopped_confirmed=False)

    backup_dir.mkdir()
    with pytest.raises(BackupError, match="already exists"):
        create_backup(data_dir, backup_dir, app_stopped_confirmed=True)


def test_backup_refuses_project_root_that_contains_application_data(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    database = Database(data_dir)
    create_project(database, data_dir, "冲突项目")

    with pytest.raises(BackupError, match="inside a project directory"):
        create_backup(data_dir, tmp_path / "backup", app_stopped_confirmed=True)


def test_verify_detects_tampered_file(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    Database(data_dir)
    backup_dir = tmp_path / "backup"
    create_backup(data_dir, backup_dir, app_stopped_confirmed=True)
    (backup_dir / "application" / "registry.db").write_bytes(b"tampered")

    with pytest.raises(BackupError, match="size mismatch|hash mismatch"):
        verify_backup(backup_dir)


def test_restore_refuses_existing_targets_and_unsafe_manifest_paths(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    Database(data_dir)
    backup_dir = tmp_path / "backup"
    create_backup(data_dir, backup_dir, app_stopped_confirmed=True)

    existing_target = tmp_path / "existing"
    existing_target.mkdir()
    with pytest.raises(BackupError, match="already exists"):
        restore_backup(
            backup_dir,
            existing_target,
            tmp_path / "projects",
            app_stopped_confirmed=True,
        )

    manifest_path = backup_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["path"] = "../outside"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(BackupError, match="unsafe path"):
        verify_backup(backup_dir)
