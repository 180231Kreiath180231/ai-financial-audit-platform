import shutil
from pathlib import Path

import pytest

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
    with database.connect(root / "app.db") as db:
        retrying = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    assert retrying["error_code"] is None
    assert retrying["error_message"] is None
    assert retrying["next_action"] is None
    worker._process(*claimed)
    with database.connect(root / "app.db") as db:
        retried = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    assert retried["status"] == "failed"
    assert retried["error_code"] == "PDF_CORRUPT"


def test_unexpected_parser_error_fails_task_without_escaping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "project-unexpected")
    root = Path(project["storage_path"])
    incoming = root / "incoming" / "unexpected.part"
    write_pdf(incoming, "unexpected")
    task_id = enqueue(database, root, "unexpected.pdf", incoming)
    worker = LocalTaskWorker(database)

    def raise_unexpected(_: str) -> None:
        raise RuntimeError("synthetic parser failure")

    monkeypatch.setattr("backend.app.worker.PdfReader", raise_unexpected)
    claimed = worker._claim_next()
    assert claimed is not None
    worker._process(*claimed)

    with database.connect(root / "app.db") as db:
        failed = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    assert failed["status"] == "failed"
    assert failed["error_code"] == "UNEXPECTED_PROCESSING_ERROR"
    assert incoming.exists()


def test_worker_skips_unavailable_project_and_processes_next_project(tmp_path: Path) -> None:
    database = Database(tmp_path / "registry")
    available = create_project(database, tmp_path / "available", "可用项目")
    unavailable = create_project(database, tmp_path / "unavailable", "失效项目")
    shutil.rmtree(Path(unavailable["storage_path"]))
    root = Path(available["storage_path"])
    incoming = root / "incoming" / "available.part"
    write_pdf(incoming, "available")
    task_id = enqueue(database, root, "available.pdf", incoming)

    worker = LocalTaskWorker(database)
    claimed = worker._claim_next()
    assert claimed == (available["id"], root, task_id)
    worker._process(*claimed)

    with database.connect(root / "app.db") as db:
        task = db.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
    assert task["status"] == "completed"


def test_synthetic_scanned_page_uses_fake_vision_and_cleans_temp(tmp_path: Path) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "synthetic-scan")
    root = Path(project["storage_path"])
    incoming = root / "incoming" / "scan.part"
    write_pdf(incoming, "scan")
    task_id = enqueue(database, root, "synthetic-scan.pdf", incoming)

    worker = LocalTaskWorker(database)
    claimed = worker._claim_next()
    assert claimed is not None
    worker._process(*claimed)

    with database.connect(root / "app.db") as db:
        document = db.execute("SELECT * FROM documents").fetchone()
        page = db.execute("SELECT * FROM pages").fetchone()
        vision = db.execute("SELECT * FROM page_vision_results").fetchone()
    with database.connect(database.registry_path) as db:
        call = db.execute(
            "SELECT * FROM model_calls WHERE task_id=?", (task_id,)
        ).fetchone()

    assert document["parse_method"] == "fake_vision"
    assert document["parse_version"] == "document-pipeline-v2"
    assert page["parse_method"] == "fake_vision"
    assert "合成扫描页 1" in page["original_text"]
    assert vision["status"] == "completed"
    assert vision["actual_model"] == "fake-structured-v1"
    assert vision["external_request"] == 0
    assert len(vision["image_sha256"]) == 64
    assert call["capability"] == "vision"
    assert call["status"] == "completed"
    assert call["task_id"] == task_id
    assert list((root / "temp").iterdir()) == []


def test_real_project_scanned_page_waits_without_model_call(tmp_path: Path) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(
        database,
        tmp_path / "real-scan",
        is_synthetic=False,
    )
    root = Path(project["storage_path"])
    incoming = root / "incoming" / "scan.part"
    write_pdf(incoming, "scan")
    task_id = enqueue(database, root, "real-scan.pdf", incoming)

    worker = LocalTaskWorker(database)
    claimed = worker._claim_next()
    assert claimed is not None
    worker._process(*claimed)

    with database.connect(root / "app.db") as db:
        document = db.execute("SELECT * FROM documents").fetchone()
        page = db.execute("SELECT * FROM pages").fetchone()
        vision = db.execute("SELECT * FROM page_vision_results").fetchone()
    with database.connect(database.registry_path) as db:
        call_count = db.execute(
            "SELECT COUNT(*) FROM model_calls WHERE task_id=?", (task_id,)
        ).fetchone()[0]

    assert document["parse_method"] == "scan_detected"
    assert page["parse_method"] == "scan_detected"
    assert page["original_text"] == ""
    assert vision["status"] == "requires_vision"
    assert vision["external_request"] == 0
    assert call_count == 0
    assert list((root / "temp").iterdir()) == []
