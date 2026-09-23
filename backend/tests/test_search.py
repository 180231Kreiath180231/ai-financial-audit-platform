from __future__ import annotations

import uuid
from pathlib import Path

from backend.app.db import Database, utc_now
from backend.app.search import search_project_pages
from backend.tests.helpers import create_project


def add_document(
    database: Database,
    root: Path,
    *,
    document_id: str,
    filename: str,
    pages: list[str],
) -> None:
    now = utc_now()
    with database.connect(root / "app.db") as db:
        db.execute(
            """INSERT INTO documents
            (id, filename, sha256, size_bytes, page_count, parse_method,
             parse_version, stored_path, created_at)
            VALUES (?, ?, ?, 12, ?, 'native_pdf', 'test-v1', ?, ?)""",
            (
                document_id,
                filename,
                document_id.encode().hex().ljust(64, "0")[:64],
                len(pages),
                str(root / "files" / f"{document_id}.pdf"),
                now,
            ),
        )
        for page_number, text in enumerate(pages, start=1):
            db.execute(
                "INSERT INTO pages VALUES (?, ?, ?, 1, ?, 'native_pdf', 'test-v1')",
                (str(uuid.uuid4()), document_id, page_number, text),
            )


def test_project_search_uses_cjk_fts_and_returns_exact_evidence_quote(tmp_path: Path) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "project")
    root = Path(project["storage_path"])
    source = "本页包含合成审计证据，并明确标记为测试资料。"
    add_document(
        database,
        root,
        document_id="doc-a",
        filename="年度报告.pdf",
        pages=["无关首页", source],
    )

    with database.connect(root / "app.db") as db:
        hits = search_project_pages(db, "审计证据")

    assert len(hits) == 1
    assert hits[0]["document_id"] == "doc-a"
    assert hits[0]["page_number"] == 2
    assert hits[0]["match_kind"] == "content"
    assert hits[0]["snippet"] in source


def test_project_search_supports_short_exact_terms_filename_and_filters(tmp_path: Path) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "project")
    root = Path(project["storage_path"])
    add_document(
        database,
        root,
        document_id="doc-a",
        filename="专项检查报告.pdf",
        pages=["科目 42 的合成金额为零。", "第二页没有目标。"],
    )
    add_document(
        database,
        root,
        document_id="doc-b",
        filename="其他资料.pdf",
        pages=["科目 42 仅用于过滤测试。"],
    )

    with database.connect(root / "app.db") as db:
        exact_hits = search_project_pages(db, "42", document_id="doc-a", page_number=1)
        filename_hits = search_project_pages(db, "专项检查")

    assert [(hit["document_id"], hit["page_number"]) for hit in exact_hits] == [
        ("doc-a", 1)
    ]
    assert len(filename_hits) == 1
    assert filename_hits[0]["document_id"] == "doc-a"
    assert filename_hits[0]["match_kind"] == "filename"
