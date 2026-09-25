from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from typing import Any

from .db import utc_now
from .retrieval import replace_page_chunks
from .schemas import DocumentMetadataUpdate, PageTextCorrectionCreate


class DocumentCorrectionError(RuntimeError):
    def __init__(self, code: str, message: str, action: str) -> None:
        self.code = code
        self.message = message
        self.action = action
        super().__init__(message)


def decode_document_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    document = dict(row)
    document["account_names"] = json.loads(
        document.pop("account_names_json", "[]") or "[]"
    )
    return document


def update_document_metadata(
    db: sqlite3.Connection,
    document_id: str,
    payload: DocumentMetadataUpdate,
) -> dict[str, Any]:
    existing = db.execute(
        "SELECT * FROM documents WHERE id=?", (document_id,)
    ).fetchone()
    if existing is None:
        raise KeyError(document_id)

    version = existing["metadata_version"] + 1
    updated_at = utc_now()
    snapshot = {
        "fiscal_year": payload.fiscal_year,
        "entity_name": payload.entity_name,
        "document_type": payload.document_type,
        "account_names": payload.account_names,
    }
    db.execute(
        """UPDATE documents
        SET fiscal_year=?, entity_name=?, document_type=?, account_names_json=?,
            metadata_version=?, metadata_updated_at=?
        WHERE id=?""",
        (
            payload.fiscal_year,
            payload.entity_name,
            payload.document_type,
            json.dumps(payload.account_names, ensure_ascii=False),
            version,
            updated_at,
            document_id,
        ),
    )
    db.execute(
        """INSERT INTO document_metadata_versions
        (id, document_id, version, snapshot_json, change_reason, created_at)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (
            str(uuid.uuid4()),
            document_id,
            version,
            json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
            payload.change_reason,
            updated_at,
        ),
    )
    return snapshot | {"metadata_version": version, "metadata_updated_at": updated_at}


def _decode_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    decoded = json.loads(value)
    return decoded if isinstance(decoded, dict) else {}


def get_page_content(
    db: sqlite3.Connection,
    document_id: str,
    page_number: int,
) -> dict[str, Any]:
    document = db.execute(
        "SELECT id, filename FROM documents WHERE id=?", (document_id,)
    ).fetchone()
    if document is None:
        raise KeyError(document_id)
    rows = db.execute(
        """SELECT block_number, source_text, original_text current_text,
        parse_method, parse_version, bbox_json, page_width, page_height,
        block_kind, table_candidate_json, text_version, corrected_at
        FROM pages WHERE document_id=? AND page_number=? ORDER BY block_number""",
        (document_id, page_number),
    ).fetchall()
    if not rows:
        raise DocumentCorrectionError(
            "PAGE_NOT_FOUND",
            "文档中不存在该页的解析内容",
            "刷新文档后选择有效页码",
        )
    corrections = db.execute(
        """SELECT id, document_id, page_number, block_number, version,
        before_text, after_text, change_reason, source, created_at
        FROM page_text_corrections
        WHERE document_id=? AND page_number=?
        ORDER BY created_at DESC, version DESC""",
        (document_id, page_number),
    ).fetchall()
    blocks = [
        {
            **dict(row),
            "source_text": row["source_text"]
            if row["source_text"] is not None
            else row["current_text"],
            "bbox": _decode_json(row["bbox_json"]),
            "table_candidate": _decode_json(row["table_candidate_json"]),
        }
        for row in rows
    ]
    for block in blocks:
        block.pop("bbox_json", None)
        block.pop("table_candidate_json", None)
    return {
        "document_id": document_id,
        "document_name": document["filename"],
        "page_number": page_number,
        "page_width": rows[0]["page_width"],
        "page_height": rows[0]["page_height"],
        "blocks": blocks,
        "corrections": [dict(row) for row in corrections],
    }


def correct_page_text(
    db: sqlite3.Connection,
    document_id: str,
    page_number: int,
    payload: PageTextCorrectionCreate,
) -> dict[str, Any]:
    db.execute("BEGIN IMMEDIATE")
    try:
        row = db.execute(
            """SELECT id, original_text, source_text, parse_method, parse_version,
            text_version FROM pages
            WHERE document_id=? AND page_number=? AND block_number=?""",
            (document_id, page_number, payload.block_number),
        ).fetchone()
        if row is None:
            raise DocumentCorrectionError(
                "PAGE_BLOCK_NOT_FOUND",
                "未找到需要校正的文本块",
                "刷新页面版面后重新选择文本块",
            )
        before = row["original_text"]
        after = payload.corrected_text
        if before == after:
            raise DocumentCorrectionError(
                "PAGE_TEXT_UNCHANGED",
                "校正内容与当前有效文本相同",
                "修改文本后再保存，或取消本次校正",
            )
        version = int(row["text_version"]) + 1
        now = utc_now()
        correction_id = str(uuid.uuid4())
        before_sha256 = hashlib.sha256(before.encode("utf-8")).hexdigest()
        after_sha256 = hashlib.sha256(after.encode("utf-8")).hexdigest()
        db.execute(
            """INSERT INTO page_text_corrections
            (id, document_id, page_number, block_number, version, before_text,
             after_text, change_reason, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'human', ?)""",
            (
                correction_id,
                document_id,
                page_number,
                payload.block_number,
                version,
                before,
                after,
                payload.change_reason,
                now,
            ),
        )
        db.execute(
            """UPDATE pages SET original_text=?, source_text=COALESCE(source_text, ?),
            text_version=?, corrected_at=? WHERE id=?""",
            (after, before, version, now, row["id"]),
        )
        replace_page_chunks(
            db,
            page_id=row["id"],
            document_id=document_id,
            page_number=page_number,
            block_number=payload.block_number,
            original_text=after,
            parse_method=row["parse_method"],
            parse_version=row["parse_version"],
        )
        db.execute(
            "INSERT INTO audit_events VALUES (?, NULL, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                "document.page_text_corrected",
                now,
                json.dumps(
                    {
                        "document_id": document_id,
                        "page_number": page_number,
                        "block_number": payload.block_number,
                        "version": version,
                        "source": "human",
                        "before_sha256": before_sha256,
                        "after_sha256": after_sha256,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            ),
        )
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    return {
        "id": correction_id,
        "document_id": document_id,
        "page_number": page_number,
        "block_number": payload.block_number,
        "version": version,
        "before_text": before,
        "after_text": after,
        "change_reason": payload.change_reason,
        "source": "human",
        "created_at": now,
        "before_sha256": before_sha256,
        "after_sha256": after_sha256,
    }
