import json
from pathlib import Path

from reportlab.pdfgen import canvas

from backend.app.db import Database, utc_now
from backend.app.documents import correct_page_text, get_page_content
from backend.app.pdf_layout import extract_pdf_layout
from backend.app.retrieval import replace_page_chunks
from backend.app.schemas import PageTextCorrectionCreate
from backend.app.search import search_project_pages
from backend.tests.helpers import create_project


def _seed_page(database: Database, root: Path) -> tuple[str, str]:
    document_id = "document-correction"
    page_id = "page-correction"
    with database.connect(root / "app.db") as db:
        db.execute(
            """INSERT INTO documents
            (id, filename, sha256, size_bytes, page_count, parse_method, parse_version,
             stored_path, created_at)
            VALUES (?, 'scan.pdf', ?, 100, 1, 'fake_vision', 'v1', 'scan.pdf', ?)""",
            (document_id, "d" * 64, utc_now()),
        )
        db.execute(
            """INSERT INTO pages
            (id, document_id, page_number, block_number, original_text, parse_method,
             parse_version, source_text, text_version)
            VALUES (?, ?, 1, 1, '原始识别金额 100', 'fake_vision', 'v1',
                    '原始识别金额 100', 1)""",
            (page_id, document_id),
        )
        replace_page_chunks(
            db,
            page_id=page_id,
            document_id=document_id,
            page_number=1,
            block_number=1,
            original_text="原始识别金额 100",
            parse_method="fake_vision",
            parse_version="v1",
        )
    return document_id, page_id


def test_page_text_correction_preserves_source_and_rebuilds_search(tmp_path: Path) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "project")
    root = Path(project["storage_path"])
    document_id, _ = _seed_page(database, root)

    with database.connect(root / "app.db") as db:
        correction = correct_page_text(
            db,
            document_id,
            1,
            PageTextCorrectionCreate(
                block_number=1,
                corrected_text="人工校正金额 1,000",
                change_reason="对照来源页修正 OCR",
            ),
        )
        content = get_page_content(db, document_id, 1)
        new_hits = search_project_pages(db, "人工校正", document_id=document_id)
        old_hits = search_project_pages(db, "原始识别", document_id=document_id)
        chunk = db.execute(
            "SELECT text FROM retrieval_chunks WHERE document_id=?", (document_id,)
        ).fetchone()
        audit = db.execute(
            """SELECT details_json FROM audit_events
            WHERE event_type='document.page_text_corrected'"""
        ).fetchone()

    assert correction["version"] == 2
    assert correction["source"] == "human"
    assert content["blocks"][0]["source_text"] == "原始识别金额 100"
    assert content["blocks"][0]["current_text"] == "人工校正金额 1,000"
    assert content["blocks"][0]["text_version"] == 2
    assert content["corrections"][0]["before_text"] == "原始识别金额 100"
    assert content["corrections"][0]["after_text"] == "人工校正金额 1,000"
    assert len(new_hits) == 1
    assert old_hits == []
    assert chunk["text"] == "人工校正金额 1,000"
    audit_details = json.loads(audit["details_json"])
    assert audit_details["before_sha256"] == correction["before_sha256"]
    assert audit_details["after_sha256"] == correction["after_sha256"]
    assert "原始识别金额 100" not in audit["details_json"]
    assert "人工校正金额 1,000" not in audit["details_json"]


def test_native_pdf_layout_exposes_coordinates_and_unconfirmed_table_candidates(
    tmp_path: Path,
) -> None:
    path = tmp_path / "layout.pdf"
    pdf = canvas.Canvas(str(path))
    pdf.drawString(72, 720, "Account 2024 1000 2025 1200")
    pdf.drawString(72, 700, "Narrative evidence line")
    pdf.save()

    pages = extract_pdf_layout(path)

    assert len(pages) == 1
    assert pages[0]["page_width"] > 0
    assert pages[0]["page_height"] > 0
    assert pages[0]["blocks"]
    candidate = next(
        block for block in pages[0]["blocks"] if block["block_kind"] == "table_candidate"
    )
    assert candidate["table_candidate"]["confirmed"] is False
    normalized = candidate["bbox"]["normalized_top_left"]
    assert all(0 <= normalized[key] <= 1 for key in ("x", "y", "width", "height"))
