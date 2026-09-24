from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import UploadFile

from backend.app import main
from backend.app.db import Database
from backend.tests.helpers import create_project


def test_pdf_upload_stops_before_crossing_disk_reserve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "project")
    root = Path(project["storage_path"])
    monkeypatch.setattr(main, "database", database)
    monkeypatch.setattr(main, "_has_import_disk_capacity", lambda *_args: False)
    upload = UploadFile(filename="blocked.pdf", file=BytesIO(b"synthetic-pdf"))

    result = asyncio.run(main.upload_documents(project["id"], [upload]))

    assert result.accepted == []
    assert [item.code for item in result.rejected] == ["DISK_SPACE_LOW"]
    assert list((root / "incoming").iterdir()) == []
    with database.connect(root / "app.db") as db:
        assert db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


def test_pdf_upload_removes_partial_file_when_space_drops_mid_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "project")
    root = Path(project["storage_path"])
    monkeypatch.setattr(main, "database", database)
    checks = iter((True, True, False))
    monkeypatch.setattr(main, "_has_import_disk_capacity", lambda *_args: next(checks))
    upload = UploadFile(
        filename="partial.pdf",
        file=BytesIO(b"a" * (1024 * 1024 + 1)),
    )

    result = asyncio.run(main.upload_documents(project["id"], [upload]))

    assert result.accepted == []
    assert [item.code for item in result.rejected] == ["DISK_SPACE_LOW"]
    assert list((root / "incoming").iterdir()) == []
    with database.connect(root / "app.db") as db:
        assert db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
