from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.db import Database
from backend.app.worker import LocalTaskWorker
from backend.tests.helpers import create_project, enqueue, write_pdf


def process_all(worker: LocalTaskWorker) -> None:
    while claimed := worker._claim_next():
        worker._process(*claimed)


def test_f01_batch_continues_when_two_of_fifty_pdfs_are_corrupt(tmp_path: Path) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "project-f01")
    root = Path(project["storage_path"])

    for index in range(50):
        incoming = root / "incoming" / f"batch-{index}.part"
        if index in {17, 41}:
            incoming.write_bytes(b"synthetic-corrupt-pdf")
        else:
            write_pdf(incoming, f"f01-{index}")
        enqueue(database, root, f"synthetic-{index:02}.pdf", incoming)

    process_all(LocalTaskWorker(database))

    with database.connect(root / "app.db") as db:
        statuses = {
            row["status"]: row["count"]
            for row in db.execute(
                "SELECT status, COUNT(*) count FROM tasks GROUP BY status"
            ).fetchall()
        }
        document_count = db.execute("SELECT COUNT(*) count FROM documents").fetchone()["count"]
        failures = db.execute(
            "SELECT error_code FROM tasks WHERE status='failed'"
        ).fetchall()

    assert statuses == {"completed": 48, "failed": 2}
    assert document_count == 48
    assert {row["error_code"] for row in failures} == {"PDF_CORRUPT"}
    assert len(list((root / "quarantine").glob("*.pdf"))) == 2


def test_f03_pause_restart_and_resume_from_safe_point(tmp_path: Path) -> None:
    data_dir = tmp_path / "registry"
    database = Database(data_dir)
    project = create_project(database, tmp_path / "project-f03")
    root = Path(project["storage_path"])
    incoming = root / "incoming" / "recover.part"
    write_pdf(incoming, "f03-recovery", pages=3)
    task_id = enqueue(database, root, "recovery.pdf", incoming)
    worker = LocalTaskWorker(database)

    claimed = worker._claim_next()
    assert claimed is not None
    with database.connect(root / "app.db") as db:
        db.execute("UPDATE tasks SET status='pausing' WHERE id=?", (task_id,))
    worker._process(*claimed)

    restarted = Database(data_dir)
    restarted.recover_tasks()
    with restarted.connect(root / "app.db") as db:
        paused = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        assert paused["status"] == "paused"
        assert paused["progress"] == 35
        db.execute("UPDATE tasks SET status='queued' WHERE id=?", (task_id,))

    resumed_worker = LocalTaskWorker(restarted)
    resumed = resumed_worker._claim_next()
    assert resumed is not None
    resumed_worker._process(*resumed)

    with restarted.connect(root / "app.db") as db:
        completed = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        event_types = {
            row["event_type"] for row in db.execute("SELECT event_type FROM audit_events")
        }
    assert completed["status"] == "completed"
    assert completed["progress"] == 100
    assert completed["result_kind"] == "imported"
    assert "task.completed" in event_types


@pytest.mark.parametrize(
    ("requested_status", "expected_status", "source_exists"),
    [("cancelled", "cancelled", False), ("pausing", "paused", True)],
)
def test_f03_final_commit_does_not_overwrite_stop_request(
    tmp_path: Path,
    requested_status: str,
    expected_status: str,
    source_exists: bool,
) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / f"project-{requested_status}")
    root = Path(project["storage_path"])
    incoming = root / "incoming" / "race.part"
    write_pdf(incoming, f"race-{requested_status}")
    task_id = enqueue(database, root, "race.pdf", incoming)
    worker = LocalTaskWorker(database)
    claimed = worker._claim_next()
    assert claimed is not None

    original_safe_point = worker._safe_point
    calls = 0

    def request_stop_after_last_safe_point(
        project_root: Path, current_task_id: str, source: Path
    ) -> bool:
        nonlocal calls
        calls += 1
        allowed = original_safe_point(project_root, current_task_id, source)
        if calls == 3 and allowed:
            with database.connect(root / "app.db") as db:
                db.execute(
                    "UPDATE tasks SET status=? WHERE id=?", (requested_status, task_id)
                )
        return allowed

    worker._safe_point = request_stop_after_last_safe_point  # type: ignore[method-assign]
    worker._process(*claimed)

    with database.connect(root / "app.db") as db:
        task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        document_count = db.execute("SELECT COUNT(*) count FROM documents").fetchone()["count"]
    assert task["status"] == expected_status
    assert task["result_kind"] is None
    assert document_count == 0
    assert incoming.exists() is source_exists
