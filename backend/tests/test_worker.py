from pathlib import Path

from backend.app.db import Database
from backend.app.worker import LocalTaskWorker
from backend.tests.helpers import create_project, enqueue, write_pdf


def test_worker_imports_pdf_and_reuses_hash(tmp_path: Path) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "project")
    root = Path(project["storage_path"])
    first = root / "incoming" / "first.part"
    write_pdf(first, "duplicate")
    task_one = enqueue(database, root, "synthetic.pdf", first)
    worker = LocalTaskWorker(database)

    claimed = worker._claim_next()
    assert claimed is not None
    worker._process(*claimed)

    with database.connect(root / "app.db") as db:
        imported = db.execute("SELECT * FROM tasks WHERE id=?", (task_one,)).fetchone()
        document = db.execute("SELECT * FROM documents").fetchone()
    assert imported["status"] == "completed"
    assert imported["result_kind"] == "imported"
    assert document["page_count"] == 1

    second = root / "incoming" / "second.part"
    second.write_bytes((root / "files" / f"{document['id']}.pdf").read_bytes())
    task_two = enqueue(database, root, "same-again.pdf", second)
    claimed = worker._claim_next()
    assert claimed is not None
    worker._process(*claimed)
    with database.connect(root / "app.db") as db:
        duplicate = db.execute("SELECT * FROM tasks WHERE id=?", (task_two,)).fetchone()
        count = db.execute("SELECT COUNT(*) count FROM documents").fetchone()["count"]
    assert duplicate["result_kind"] == "duplicate"
    assert count == 1


def test_corrupt_pdf_is_quarantined_without_losing_task(tmp_path: Path) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "project-corrupt")
    root = Path(project["storage_path"])
    incoming = root / "incoming" / "broken.part"
    incoming.write_bytes(b"not-a-pdf")
    task_id = enqueue(database, root, "broken.pdf", incoming)
    worker = LocalTaskWorker(database)

    claimed = worker._claim_next()
    assert claimed is not None
    worker._process(*claimed)

    with database.connect(root / "app.db") as db:
        failed = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    assert failed["status"] == "failed"
    assert failed["error_code"] == "PDF_CORRUPT"
    assert (root / "quarantine" / f"{task_id}.pdf").exists()

    with database.connect(root / "app.db") as db:
        db.execute("UPDATE tasks SET status='queued' WHERE id=?", (task_id,))
    claimed = worker._claim_next()
    assert claimed is not None
    worker._process(*claimed)
    with database.connect(root / "app.db") as db:
        retried = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    assert retried["status"] == "failed"
    assert retried["error_code"] == "PDF_CORRUPT"
