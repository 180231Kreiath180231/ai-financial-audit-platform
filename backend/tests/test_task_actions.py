from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.app import main
from backend.app.db import Database
from backend.tests.helpers import create_project, enqueue, write_pdf


def create_task(database: Database, root: Path, name: str) -> str:
    source = root / "incoming" / f"{name}.part"
    write_pdf(source, name)
    return enqueue(database, root, f"{name}.pdf", source)


def test_resource_pause_rejects_manual_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "project-resource")
    root = Path(project["storage_path"])
    task_id = create_task(database, root, "resource")
    with database.connect(root / "app.db") as db:
        db.execute(
            """UPDATE tasks SET status='paused', pause_reason='resource'
            WHERE id=?""",
            (task_id,),
        )
    monkeypatch.setattr(main, "database", database)

    with pytest.raises(HTTPException) as raised:
        main.change_task(project["id"], task_id, "resume")

    assert raised.value.status_code == 409
    assert raised.value.detail["code"] == "RESOURCE_PAUSE_AUTO_RESUME"


def test_user_pause_and_resume_keep_pause_ownership_explicit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "project-user")
    root = Path(project["storage_path"])
    task_id = create_task(database, root, "user")
    with database.connect(root / "app.db") as db:
        db.execute("UPDATE tasks SET status='running' WHERE id=?", (task_id,))
    monkeypatch.setattr(main, "database", database)

    pausing = main.change_task(project["id"], task_id, "pause")
    assert pausing.status == "pausing"
    assert pausing.pause_reason == "user"
    with database.connect(root / "app.db") as db:
        db.execute("UPDATE tasks SET status='paused' WHERE id=?", (task_id,))

    resumed = main.change_task(project["id"], task_id, "resume")
    assert resumed.status == "queued"
    assert resumed.pause_reason is None
