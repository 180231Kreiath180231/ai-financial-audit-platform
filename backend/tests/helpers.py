from __future__ import annotations

import uuid
from pathlib import Path

from pypdf import PdfWriter

from backend.app.db import Database, utc_now
from backend.app.schemas import ProjectCreate


def create_project(
    database: Database,
    root: Path,
    name: str | None = None,
    *,
    is_synthetic: bool = True,
) -> dict:
    return database.create_project(
        ProjectCreate(
            name=name or f"合成项目-{root.name}",
            entity_name="合成测试主体",
            year_start=2024,
            year_end=2025,
            storage_path=str(root),
            model_profile="严格离线 / Fake Provider",
        ),
        is_synthetic=is_synthetic,
    )


def write_pdf(path: Path, marker: str, pages: int = 1) -> None:
    writer = PdfWriter()
    for index in range(pages):
        writer.add_blank_page(width=612 + index, height=792)
    writer.add_metadata({"/Title": f"Synthetic {marker}"})
    with path.open("wb") as stream:
        writer.write(stream)


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
