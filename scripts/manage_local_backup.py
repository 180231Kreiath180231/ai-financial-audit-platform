"""Create, verify, and restore offline backups for the local audit application.

Backups are deliberately directory based. They contain the registry database,
DPAPI-protected secret blobs, every registered project database, and all project
files. The application must be stopped before backup or restore.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import time
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BACKUP_FORMAT = "hengjian-local-backup-v1"
MANIFEST_NAME = "manifest.json"
SQLITE_SIDECAR_SUFFIXES = ("-journal", "-shm", "-wal")


class BackupError(RuntimeError):
    """Raised when a backup operation cannot be completed safely."""


def _resolved(path: Path | str) -> Path:
    return Path(path).expanduser().resolve()


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _require_new_directory(path: Path, label: str) -> None:
    if path.exists():
        raise BackupError(f"{label} already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)


def _publish_directory(stage: Path, destination: Path) -> None:
    """Publish a prepared directory, tolerating short-lived Windows scan handles."""
    for attempt in range(10):
        try:
            stage.replace(destination)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.05)


def _sqlite_snapshot(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise BackupError(f"SQLite database not found: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_uri = f"file:{source.as_posix()}?mode=ro"
    with closing(sqlite3.connect(source_uri, uri=True)) as source_connection:
        with closing(sqlite3.connect(destination)) as destination_connection:
            source_connection.backup(destination_connection)
            destination_connection.commit()
            result = destination_connection.execute("PRAGMA integrity_check").fetchone()
            if result is None or result[0] != "ok":
                raise BackupError(f"SQLite snapshot integrity check failed: {source}")


def _skip_sqlite_sidecar(path: Path, database: Path) -> bool:
    if path == database:
        return True
    return any(path == Path(f"{database}{suffix}") for suffix in SQLITE_SIDECAR_SUFFIXES)


def _copy_tree(
    source: Path,
    destination: Path,
    *,
    excluded_roots: tuple[Path, ...] = (),
    snapshot_database: Path | None = None,
) -> None:
    if not source.is_dir():
        raise BackupError(f"Source directory not found: {source}")
    destination.mkdir(parents=True, exist_ok=False)

    for current_text, directory_names, file_names in os.walk(source, followlinks=False):
        current = Path(current_text).resolve()
        if current.is_symlink():
            raise BackupError(f"Symbolic links are not supported in backups: {current}")

        retained_directories: list[str] = []
        for name in directory_names:
            child = current / name
            if child.is_symlink():
                raise BackupError(f"Symbolic links are not supported in backups: {child}")
            resolved_child = child.resolve()
            if any(_is_within(resolved_child, excluded) for excluded in excluded_roots):
                continue
            retained_directories.append(name)
        directory_names[:] = retained_directories

        relative_current = current.relative_to(source)
        output_directory = destination / relative_current
        output_directory.mkdir(parents=True, exist_ok=True)
        for name in file_names:
            source_file = current / name
            if source_file.is_symlink():
                raise BackupError(f"Symbolic links are not supported in backups: {source_file}")
            if snapshot_database is not None and _skip_sqlite_sidecar(
                source_file.resolve(), snapshot_database
            ):
                continue
            shutil.copy2(source_file, output_directory / name)

    if snapshot_database is not None:
        database_relative_path = snapshot_database.relative_to(source)
        _sqlite_snapshot(snapshot_database, destination / database_relative_path)


def _read_projects(registry_database: Path) -> list[dict[str, str]]:
    source_uri = f"file:{registry_database.as_posix()}?mode=ro"
    try:
        with closing(sqlite3.connect(source_uri, uri=True)) as connection:
            rows = connection.execute(
                "SELECT id, name, storage_path FROM projects ORDER BY id"
            ).fetchall()
    except sqlite3.Error as error:
        raise BackupError(f"Cannot read registered projects: {error}") from error
    return [
        {"id": str(row[0]), "name": str(row[1]), "source_storage_path": str(row[2])}
        for row in rows
    ]


def _validate_source_layout(data_dir: Path, project_roots: list[Path], output_dir: Path) -> None:
    sources = [data_dir, *project_roots]
    if any(_is_within(output_dir, source) for source in sources):
        raise BackupError("Backup output must be outside the application and project directories")
    for index, left in enumerate(project_roots):
        if _is_within(data_dir, left):
            raise BackupError(f"Application data directory is inside a project directory: {left}")
        for right in project_roots[index + 1 :]:
            if _is_within(left, right) or _is_within(right, left):
                raise BackupError(f"Registered project directories overlap: {left} and {right}")


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inventory_files(root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name == MANIFEST_NAME and path.parent == root:
            continue
        entries.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": path.stat().st_size,
                "sha256": _hash_file(path),
            }
        )
    return entries


def create_backup(
    data_dir: Path | str,
    output_dir: Path | str,
    *,
    app_stopped_confirmed: bool,
) -> dict[str, Any]:
    if not app_stopped_confirmed:
        raise BackupError("Backup requires --confirm-app-stopped")

    resolved_data_dir = _resolved(data_dir)
    resolved_output_dir = _resolved(output_dir)
    if not resolved_data_dir.is_dir():
        raise BackupError(f"Application data directory not found: {resolved_data_dir}")
    registry_database = resolved_data_dir / "registry.db"
    projects = _read_projects(registry_database)
    project_roots = [_resolved(project["source_storage_path"]) for project in projects]
    _validate_source_layout(resolved_data_dir, project_roots, resolved_output_dir)
    _require_new_directory(resolved_output_dir, "Backup directory")

    stage = resolved_output_dir.parent / f".{resolved_output_dir.name}.building-{uuid.uuid4().hex}"
    try:
        stage.mkdir()
        excluded = tuple(root for root in project_roots if _is_within(root, resolved_data_dir))
        _copy_tree(
            resolved_data_dir,
            stage / "application",
            excluded_roots=excluded,
            snapshot_database=registry_database,
        )

        manifest_projects: list[dict[str, str]] = []
        for project, project_root in zip(projects, project_roots, strict=True):
            project_database = project_root / "app.db"
            backup_prefix = f"projects/{project['id']}"
            _copy_tree(
                project_root,
                stage / Path(backup_prefix),
                snapshot_database=project_database,
            )
            manifest_projects.append({**project, "backup_prefix": backup_prefix})

        manifest: dict[str, Any] = {
            "format": BACKUP_FORMAT,
            "created_at": datetime.now(UTC).isoformat(),
            "source_data_dir": str(resolved_data_dir),
            "app_stopped_confirmed": True,
            "projects": manifest_projects,
            "files": _inventory_files(stage),
        }
        (stage / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        _publish_directory(stage, resolved_output_dir)
        return manifest
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        raise


def _load_manifest(backup_dir: Path) -> dict[str, Any]:
    manifest_path = backup_dir / MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BackupError(f"Cannot read backup manifest: {error}") from error
    if manifest.get("format") != BACKUP_FORMAT:
        raise BackupError(f"Unsupported backup format: {manifest.get('format')!r}")
    if not isinstance(manifest.get("files"), list) or not isinstance(
        manifest.get("projects"), list
    ):
        raise BackupError("Backup manifest is incomplete")
    return manifest


def _safe_manifest_path(backup_dir: Path, relative_path: str) -> Path:
    candidate = (backup_dir / relative_path).resolve()
    if not _is_within(candidate, backup_dir):
        raise BackupError(f"Backup manifest contains an unsafe path: {relative_path}")
    return candidate


def _validated_project_id(value: Any) -> str:
    project_id = str(value)
    try:
        parsed = uuid.UUID(project_id)
    except ValueError as error:
        raise BackupError(f"Backup manifest contains an invalid project id: {project_id}") from error
    if str(parsed) != project_id:
        raise BackupError(f"Backup manifest contains an invalid project id: {project_id}")
    return project_id


def _validated_manifest_projects(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    projects: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for entry in manifest["projects"]:
        if not isinstance(entry, dict):
            raise BackupError("Backup manifest contains an invalid project entry")
        project_id = _validated_project_id(entry.get("id"))
        if project_id in seen_ids:
            raise BackupError(f"Backup manifest contains a duplicate project id: {project_id}")
        expected_prefix = f"projects/{project_id}"
        if entry.get("backup_prefix") != expected_prefix:
            raise BackupError(f"Backup manifest contains an invalid project prefix: {project_id}")
        if not isinstance(entry.get("name"), str):
            raise BackupError(f"Backup manifest contains an invalid project name: {project_id}")
        seen_ids.add(project_id)
        projects.append(entry)
    return projects


def _sqlite_integrity_check(path: Path) -> None:
    source_uri = f"file:{path.as_posix()}?mode=ro&immutable=1"
    try:
        with closing(sqlite3.connect(source_uri, uri=True)) as connection:
            result = connection.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.Error as error:
        raise BackupError(f"Cannot inspect SQLite database {path}: {error}") from error
    if result is None or result[0] != "ok":
        raise BackupError(f"SQLite integrity check failed: {path}")


def verify_backup(backup_dir: Path | str) -> dict[str, Any]:
    resolved_backup_dir = _resolved(backup_dir)
    if not resolved_backup_dir.is_dir():
        raise BackupError(f"Backup directory not found: {resolved_backup_dir}")
    manifest = _load_manifest(resolved_backup_dir)
    projects = _validated_manifest_projects(manifest)

    expected_paths: set[str] = set()
    total_bytes = 0
    for entry in manifest["files"]:
        try:
            relative_path = str(entry["path"])
            expected_size = int(entry["size"])
            expected_hash = str(entry["sha256"])
        except (KeyError, TypeError, ValueError) as error:
            raise BackupError("Backup manifest contains an invalid file entry") from error
        file_path = _safe_manifest_path(resolved_backup_dir, relative_path)
        if relative_path in expected_paths:
            raise BackupError(f"Backup manifest contains a duplicate file: {relative_path}")
        if not file_path.is_file():
            raise BackupError(f"Backup file is missing: {relative_path}")
        if file_path.stat().st_size != expected_size:
            raise BackupError(f"Backup file size mismatch: {relative_path}")
        if _hash_file(file_path) != expected_hash:
            raise BackupError(f"Backup file hash mismatch: {relative_path}")
        expected_paths.add(relative_path)
        total_bytes += expected_size

    discovered_paths = list(resolved_backup_dir.rglob("*"))
    symbolic_links = [
        path.relative_to(resolved_backup_dir).as_posix()
        for path in discovered_paths
        if path.is_symlink()
    ]
    if symbolic_links:
        raise BackupError(f"Backup contains unsupported symbolic links: {symbolic_links}")
    actual_paths = {
        path.relative_to(resolved_backup_dir).as_posix()
        for path in discovered_paths
        if path.is_file() and path != resolved_backup_dir / MANIFEST_NAME
    }
    unexpected = sorted(actual_paths - expected_paths)
    missing_from_inventory = sorted(expected_paths - actual_paths)
    if unexpected or missing_from_inventory:
        raise BackupError(
            f"Backup inventory mismatch; unexpected={unexpected}, missing={missing_from_inventory}"
        )

    _sqlite_integrity_check(resolved_backup_dir / "application" / "registry.db")
    for project in projects:
        prefix = str(project.get("backup_prefix", ""))
        project_database = _safe_manifest_path(resolved_backup_dir, f"{prefix}/app.db")
        _sqlite_integrity_check(project_database)

    return {
        "format": BACKUP_FORMAT,
        "files": len(expected_paths),
        "bytes": total_bytes,
        "projects": len(projects),
        "verified": True,
    }


def _validate_restore_targets(data_dir: Path, projects_dir: Path, backup_dir: Path) -> None:
    if _is_within(data_dir, backup_dir) or _is_within(projects_dir, backup_dir):
        raise BackupError("Restore targets must be outside the backup directory")
    if _is_within(data_dir, projects_dir) or _is_within(projects_dir, data_dir):
        raise BackupError("Restore data and project directories must not overlap")
    _require_new_directory(data_dir, "Restore data directory")
    _require_new_directory(projects_dir, "Restore projects directory")


def restore_backup(
    backup_dir: Path | str,
    target_data_dir: Path | str,
    target_projects_dir: Path | str,
    *,
    app_stopped_confirmed: bool,
) -> dict[str, Any]:
    if not app_stopped_confirmed:
        raise BackupError("Restore requires --confirm-app-stopped")

    resolved_backup_dir = _resolved(backup_dir)
    resolved_data_dir = _resolved(target_data_dir)
    resolved_projects_dir = _resolved(target_projects_dir)
    verification = verify_backup(resolved_backup_dir)
    manifest = _load_manifest(resolved_backup_dir)
    projects = _validated_manifest_projects(manifest)
    _validate_restore_targets(resolved_data_dir, resolved_projects_dir, resolved_backup_dir)

    data_stage = resolved_data_dir.parent / f".{resolved_data_dir.name}.restoring-{uuid.uuid4().hex}"
    projects_stage = (
        resolved_projects_dir.parent / f".{resolved_projects_dir.name}.restoring-{uuid.uuid4().hex}"
    )
    moved_projects = False
    try:
        shutil.copytree(resolved_backup_dir / "application", data_stage)
        projects_stage.mkdir()
        restored_projects: list[dict[str, str]] = []
        for project in projects:
            project_id = str(project["id"])
            prefix = str(project["backup_prefix"])
            source = _safe_manifest_path(resolved_backup_dir, prefix)
            project_stage = projects_stage / project_id
            shutil.copytree(source, project_stage)
            final_storage_path = resolved_projects_dir / project_id
            restored_projects.append(
                {
                    "id": project_id,
                    "name": str(project["name"]),
                    "storage_path": str(final_storage_path),
                }
            )

        restored_registry = data_stage / "registry.db"
        with closing(sqlite3.connect(restored_registry)) as connection:
            for project in restored_projects:
                connection.execute(
                    "UPDATE projects SET storage_path = ? WHERE id = ?",
                    (project["storage_path"], project["id"]),
                )
            connection.commit()
        _sqlite_integrity_check(restored_registry)
        for project in restored_projects:
            _sqlite_integrity_check(projects_stage / project["id"] / "app.db")

        _publish_directory(projects_stage, resolved_projects_dir)
        moved_projects = True
        _publish_directory(data_stage, resolved_data_dir)
        return {
            **verification,
            "restored": True,
            "target_data_dir": str(resolved_data_dir),
            "target_projects_dir": str(resolved_projects_dir),
            "restored_projects": restored_projects,
        }
    except Exception:
        if data_stage.exists():
            shutil.rmtree(data_stage)
        if projects_stage.exists():
            shutil.rmtree(projects_stage)
        if moved_projects and resolved_projects_dir.exists() and not resolved_data_dir.exists():
            shutil.rmtree(resolved_projects_dir)
        raise


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    backup = commands.add_parser("backup", help="Create a complete local backup")
    backup.add_argument("--data-dir", type=Path, required=True)
    backup.add_argument("--output-dir", type=Path, required=True)
    backup.add_argument("--confirm-app-stopped", action="store_true")

    verify = commands.add_parser("verify", help="Verify backup hashes and SQLite integrity")
    verify.add_argument("--backup-dir", type=Path, required=True)

    restore = commands.add_parser("restore", help="Restore into new isolated directories")
    restore.add_argument("--backup-dir", type=Path, required=True)
    restore.add_argument("--target-data-dir", type=Path, required=True)
    restore.add_argument("--target-projects-dir", type=Path, required=True)
    restore.add_argument("--confirm-app-stopped", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "backup":
            result = create_backup(
                arguments.data_dir,
                arguments.output_dir,
                app_stopped_confirmed=arguments.confirm_app_stopped,
            )
            summary = {
                "format": result["format"],
                "files": len(result["files"]),
                "projects": len(result["projects"]),
                "output_dir": str(arguments.output_dir.resolve()),
            }
        elif arguments.command == "verify":
            summary = verify_backup(arguments.backup_dir)
        else:
            summary = restore_backup(
                arguments.backup_dir,
                arguments.target_data_dir,
                arguments.target_projects_dir,
                app_stopped_confirmed=arguments.confirm_app_stopped,
            )
    except BackupError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
