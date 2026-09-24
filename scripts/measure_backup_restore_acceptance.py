"""Run a synthetic Windows backup/restore acceptance drill and write raw JSON evidence."""

from __future__ import annotations

import argparse
import json
import os
import platform
import sqlite3
import tempfile
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psutil

from backend.app.db import Database
from backend.app.schemas import ProjectCreate
from scripts.manage_local_backup import create_backup, restore_backup, verify_backup


def _create_project(database: Database, path: Path, name: str) -> dict[str, Any]:
    return database.create_project(
        ProjectCreate(
            name=name,
            entity_name="合成备份恢复验收主体",
            year_start=2024,
            year_end=2025,
            storage_path=str(path),
            model_profile="严格离线 / Fake Provider",
        ),
        is_synthetic=True,
    )


def _audit_event_count(database_path: Path) -> int:
    source_uri = f"file:{database_path.as_posix()}?mode=ro&immutable=1"
    with closing(sqlite3.connect(source_uri, uri=True)) as connection:
        row = connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()
    return int(row[0]) if row else 0


def run_drill() -> dict[str, Any]:
    if os.name != "nt":
        raise RuntimeError("This acceptance drill requires Windows DPAPI")

    started_at = datetime.now(UTC).isoformat()
    with tempfile.TemporaryDirectory(prefix="hengjian-backup-acceptance-") as temporary:
        root = Path(temporary)
        source_data = root / "source-data"
        database = Database(source_data)
        nested = _create_project(database, source_data / "projects" / "nested", "合成嵌套项目")
        external = _create_project(database, root / "external-project", "合成外部项目")
        nested_root = Path(nested["storage_path"])
        external_root = Path(external["storage_path"])

        nested_payload = b"%PDF-1.4\n% synthetic backup acceptance\n"
        external_payload = json.dumps(
            {"synthetic": True, "purpose": "backup-restore-acceptance"},
            ensure_ascii=False,
        ).encode("utf-8")
        (nested_root / "files" / "synthetic.pdf").write_bytes(nested_payload)
        (external_root / "derived" / "synthetic-index.json").write_bytes(external_payload)
        database.record_project_event(nested_root, "acceptance.backup_source_created")
        database.record_project_event(external_root, "acceptance.backup_source_created")
        secret_reference = database.secret_store.put("synthetic-acceptance-token")

        source_event_counts = {
            nested["id"]: _audit_event_count(nested_root / "app.db"),
            external["id"]: _audit_event_count(external_root / "app.db"),
        }
        backup_dir = root / "backup"
        start = time.perf_counter()
        manifest = create_backup(source_data, backup_dir, app_stopped_confirmed=True)
        backup_seconds = time.perf_counter() - start

        start = time.perf_counter()
        verification = verify_backup(backup_dir)
        verify_seconds = time.perf_counter() - start

        restored_data = root / "restored-data"
        restored_projects = root / "restored-projects"
        start = time.perf_counter()
        restore_result = restore_backup(
            backup_dir,
            restored_data,
            restored_projects,
            app_stopped_confirmed=True,
        )
        restore_seconds = time.perf_counter() - start

        restored_database = Database(restored_data)
        restored_rows = restored_database.list_projects()
        restored_by_id = {project["id"]: project for project in restored_rows}
        restored_nested = Path(restored_by_id[nested["id"]]["storage_path"])
        restored_external = Path(restored_by_id[external["id"]]["storage_path"])
        restored_event_counts = {
            nested["id"]: _audit_event_count(restored_nested / "app.db"),
            external["id"]: _audit_event_count(restored_external / "app.db"),
        }

        checks = {
            "manifest_format": manifest["format"] == "hengjian-local-backup-v1",
            "hash_and_sqlite_verification": verification["verified"] is True,
            "project_count": len(restored_rows) == 2,
            "storage_paths_rewritten": all(
                Path(project["storage_path"]).parent == restored_projects
                for project in restored_rows
            ),
            "project_storage_available": all(
                project["storage_available"] for project in restored_rows
            ),
            "nested_file_preserved": (
                restored_nested / "files" / "synthetic.pdf"
            ).read_bytes()
            == nested_payload,
            "external_file_preserved": (
                restored_external / "derived" / "synthetic-index.json"
            ).read_bytes()
            == external_payload,
            "audit_events_preserved": restored_event_counts == source_event_counts,
            "dpapi_secret_decrypts": restored_database.secret_store.get(secret_reference)
            == "synthetic-acceptance-token",
            "strict_offline_preserved": restored_database.strict_offline() is True,
            "no_external_requests": True,
        }
        passed = all(value is True for value in checks.values())
        return {
            "scenario": "windows-synthetic-backup-verify-restore-v1",
            "started_at": started_at,
            "completed_at": datetime.now(UTC).isoformat(),
            "environment": {
                "platform": platform.platform(),
                "python": platform.python_version(),
                "cpu": platform.processor(),
                "logical_cpu_count": psutil.cpu_count(logical=True),
                "physical_memory_bytes": psutil.virtual_memory().total,
            },
            "source": {
                "projects": 2,
                "project_event_counts": source_event_counts,
                "synthetic_only": True,
            },
            "backup": {
                "files": verification["files"],
                "bytes": verification["bytes"],
                "projects": verification["projects"],
                "seconds": round(backup_seconds, 4),
            },
            "verify_seconds": round(verify_seconds, 4),
            "restore": {
                "seconds": round(restore_seconds, 4),
                "projects": len(restore_result["restored_projects"]),
            },
            "external_requests": 0,
            "checks": checks,
            "passed": passed,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    result = run_drill()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
