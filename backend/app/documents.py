from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from .db import utc_now
from .schemas import DocumentMetadataUpdate


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
