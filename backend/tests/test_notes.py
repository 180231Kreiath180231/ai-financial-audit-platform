import json
from pathlib import Path

import pytest

from backend.app.db import Database
from backend.app.notes import AuditNoteRepository, NoteError
from backend.app.schemas import AuditNotePayload
from backend.tests.helpers import create_project


def seed_links(database: Database, root: Path) -> None:
    with database.connect(root / "app.db") as db:
        db.execute(
            """INSERT INTO documents
            (id, filename, sha256, size_bytes, page_count, parse_method,
             parse_version, stored_path, created_at)
            VALUES ('document-1', 'synthetic.pdf', ?, 12, 2, 'native_pdf',
                    'v1', 'synthetic.pdf', 'now')""",
            ("a" * 64,),
        )
        db.executemany(
            """INSERT INTO pages
            (id, document_id, page_number, block_number, original_text,
             parse_method, parse_version)
            VALUES (?, 'document-1', ?, 1, ?, 'native_pdf', 'v1')""",
            [
                ("page-1", 1, "合成第一页"),
                ("page-2", 2, "合成第二页"),
            ],
        )
        db.execute(
            """INSERT INTO risk_items
            (id, risk_number, risk_type, risk_level, status, summary,
             trigger_rule_id, trigger_rule_version, uncertainty, created_at, updated_at)
            VALUES ('risk-1', 'R-0001', '人工线索', '待评估', '待复核',
                    '核对合成事项', 'MANUAL-DRAFT', 'v1', '尚未解释', 'now', 'now')"""
        )


def test_note_create_update_delete_preserves_resolved_links_and_audit(tmp_path: Path) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "notes-project")
    root = Path(project["storage_path"])
    seed_links(database, root)
    repository = AuditNoteRepository(database)

    created = repository.create(
        project["id"],
        AuditNotePayload(
            title="  现场核对记录  ",
            body="  已核对合成第一页。  ",
            tags=["凭证", "凭证", " 现场 "],
            model_readable=False,
            risk_ids=["risk-1", "risk-1"],
            pages=[
                {"document_id": "document-1", "page_number": 1},
                {"document_id": "document-1", "page_number": 1},
            ],
        ),
    )

    assert created["title"] == "现场核对记录"
    assert created["body"] == "已核对合成第一页。"
    assert created["tags"] == ["凭证", "现场"]
    assert created["model_readable"] is False
    assert created["risks"] == [
        {"risk_id": "risk-1", "risk_number": "R-0001", "summary": "核对合成事项"}
    ]
    assert created["pages"] == [
        {
            "document_id": "document-1",
            "document_name": "synthetic.pdf",
            "page_number": 1,
        }
    ]

    updated = repository.update(
        project["id"],
        created["id"],
        AuditNotePayload(
            title="现场核对记录（更新）",
            body="补充第二页核对结果。",
            tags=["更新"],
            model_readable=True,
            risk_ids=[],
            pages=[{"document_id": "document-1", "page_number": 2}],
        ),
    )
    assert updated["model_readable"] is True
    assert updated["risks"] == []
    assert updated["pages"][0]["page_number"] == 2

    repository.delete(project["id"], created["id"])
    assert repository.list(project["id"]) == []
    with database.connect(root / "app.db") as db:
        events = db.execute(
            "SELECT event_type, details_json FROM audit_events ORDER BY rowid"
        ).fetchall()
        links = db.execute("SELECT COUNT(*) FROM note_pages").fetchone()[0]
    assert [row["event_type"] for row in events] == [
        "note.created",
        "note.updated",
        "note.deleted",
    ]
    assert links == 0
    deleted = json.loads(events[-1]["details_json"])
    assert deleted["title"] == "现场核对记录（更新）"
    assert "body" not in deleted


def test_note_rejects_missing_page_without_partial_insert(tmp_path: Path) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "invalid-note-project")
    root = Path(project["storage_path"])
    seed_links(database, root)
    repository = AuditNoteRepository(database)

    with pytest.raises(NoteError) as raised:
        repository.create(
            project["id"],
            AuditNotePayload(
                title="无效页码",
                body="不应保存",
                pages=[{"document_id": "document-1", "page_number": 9}],
            ),
        )

    assert raised.value.code == "NOTE_PAGE_NOT_FOUND"
    assert repository.list(project["id"]) == []
