import uuid
from pathlib import Path

from pypdf import PdfWriter

from backend.app.db import Database, utc_now
from backend.app.schemas import ProjectCreate
from backend.app.worker import LocalTaskWorker


def create_project(database: Database, root: Path) -> dict:
    return database.create_project(
        ProjectCreate(
            name=f"合成项目-{root.name}",
            entity_name="合成测试主体",
            year_start=2024,
            year_end=2025,
            storage_path=str(root),
            model_profile="严格离线 / Fake Provider",
        ),
        is_synthetic=True,
    )


def enqueue(database: Database, root: Path, filename: str, content_path: Path) -> str:
    task_id = str(uuid.uuid4())
    now = utc_now()
    with database.connect(root / "app.db") as db:
        db.execute(
            """INSERT INTO tasks
            (id, task_type, filename, incoming_path, status, progress, current_step, created_at, updated_at)
            VALUES (?, 'pdf_import', ?, ?, 'queued', 0, '等待单工作器', ?, ?)""",
            (task_id, filename, str(content_path), now, now),
        )
    return task_id


def test_worker_imports_pdf_and_reuses_hash(tmp_path: Path) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "project")
    root = Path(project["storage_path"])
    first = root / "incoming" / "first.part"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with first.open("wb") as stream:
        writer.write(stream)
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
