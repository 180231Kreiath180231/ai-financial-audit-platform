from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from .db import Database, utc_now
from .schemas import AuditNotePayload


class NoteError(RuntimeError):
    def __init__(self, code: str, message: str, action: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.action = action


class AuditNoteRepository:
    """Project-scoped audit notes with resolved local associations."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def list(self, project_id: str) -> list[dict[str, Any]]:
        root = self.database.project_root(project_id)
        with self.database.connect(root / "app.db") as db:
            rows = db.execute(
                "SELECT * FROM notes ORDER BY updated_at DESC, created_at DESC"
            ).fetchall()
            return [self._hydrate(db, row) for row in rows]

    def get(self, project_id: str, note_id: str) -> dict[str, Any]:
        root = self.database.project_root(project_id)
        with self.database.connect(root / "app.db") as db:
            row = db.execute("SELECT * FROM notes WHERE id=?", (note_id,)).fetchone()
            if row is None:
                raise KeyError(note_id)
            return self._hydrate(db, row)

    def create(self, project_id: str, payload: AuditNotePayload) -> dict[str, Any]:
        root = self.database.project_root(project_id)
        note_id = str(uuid.uuid4())
        now = utc_now()
        with self.database.connect(root / "app.db") as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                risk_ids, pages = self._resolve_links(db, payload)
                db.execute(
                    """INSERT INTO notes
                    (id, title, body, tags_json, model_readable, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        note_id,
                        payload.title,
                        payload.body,
                        json.dumps(payload.tags, ensure_ascii=False),
                        int(payload.model_readable),
                        now,
                        now,
                    ),
                )
                self._replace_links(db, note_id, risk_ids, pages)
                self._insert_event(
                    db,
                    "note.created",
                    note_id,
                    now,
                    payload.model_readable,
                    len(risk_ids),
                    len(pages),
                )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return self.get(project_id, note_id)

    def update(
        self, project_id: str, note_id: str, payload: AuditNotePayload
    ) -> dict[str, Any]:
        root = self.database.project_root(project_id)
        now = utc_now()
        with self.database.connect(root / "app.db") as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                current = db.execute(
                    "SELECT id FROM notes WHERE id=?", (note_id,)
                ).fetchone()
                if current is None:
                    raise KeyError(note_id)
                risk_ids, pages = self._resolve_links(db, payload)
                db.execute(
                    """UPDATE notes SET title=?, body=?, tags_json=?,
                    model_readable=?, updated_at=? WHERE id=?""",
                    (
                        payload.title,
                        payload.body,
                        json.dumps(payload.tags, ensure_ascii=False),
                        int(payload.model_readable),
                        now,
                        note_id,
                    ),
                )
                self._replace_links(db, note_id, risk_ids, pages)
                self._insert_event(
                    db,
                    "note.updated",
                    note_id,
                    now,
                    payload.model_readable,
                    len(risk_ids),
                    len(pages),
                )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return self.get(project_id, note_id)

    def delete(self, project_id: str, note_id: str) -> None:
        root = self.database.project_root(project_id)
        now = utc_now()
        with self.database.connect(root / "app.db") as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                note = db.execute(
                    "SELECT title, model_readable FROM notes WHERE id=?", (note_id,)
                ).fetchone()
                if note is None:
                    raise KeyError(note_id)
                risk_count = db.execute(
                    "SELECT COUNT(*) FROM note_risks WHERE note_id=?", (note_id,)
                ).fetchone()[0]
                page_count = db.execute(
                    "SELECT COUNT(*) FROM note_pages WHERE note_id=?", (note_id,)
                ).fetchone()[0]
                db.execute("DELETE FROM notes WHERE id=?", (note_id,))
                self._insert_event(
                    db,
                    "note.deleted",
                    note_id,
                    now,
                    bool(note["model_readable"]),
                    risk_count,
                    page_count,
                    title=note["title"],
                )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise

    @staticmethod
    def _resolve_links(
        db: sqlite3.Connection, payload: AuditNotePayload
    ) -> tuple[list[str], list[tuple[str, int]]]:
        risk_ids = list(dict.fromkeys(payload.risk_ids))
        for risk_id in risk_ids:
            if db.execute("SELECT 1 FROM risk_items WHERE id=?", (risk_id,)).fetchone() is None:
                raise NoteError(
                    "NOTE_RISK_NOT_FOUND",
                    "备忘录关联的风险不存在或已失效",
                    "刷新风险列表后重新选择",
                )

        pages = list(dict.fromkeys((item.document_id, item.page_number) for item in payload.pages))
        for document_id, page_number in pages:
            page = db.execute(
                """SELECT 1 FROM pages
                WHERE document_id=? AND page_number=? LIMIT 1""",
                (document_id, page_number),
            ).fetchone()
            if page is None:
                raise NoteError(
                    "NOTE_PAGE_NOT_FOUND",
                    "备忘录关联的文档页不存在或尚未解析",
                    "刷新文档后重新选择有效页码",
                )
        return risk_ids, pages

    @staticmethod
    def _replace_links(
        db: sqlite3.Connection,
        note_id: str,
        risk_ids: list[str],
        pages: list[tuple[str, int]],
    ) -> None:
        db.execute("DELETE FROM note_risks WHERE note_id=?", (note_id,))
        db.execute("DELETE FROM note_pages WHERE note_id=?", (note_id,))
        db.executemany(
            "INSERT INTO note_risks(note_id, risk_id) VALUES (?, ?)",
            [(note_id, risk_id) for risk_id in risk_ids],
        )
        db.executemany(
            """INSERT INTO note_pages(note_id, document_id, page_number)
            VALUES (?, ?, ?)""",
            [(note_id, document_id, page_number) for document_id, page_number in pages],
        )

    @staticmethod
    def _insert_event(
        db: sqlite3.Connection,
        event_type: str,
        note_id: str,
        created_at: str,
        model_readable: bool,
        risk_count: int,
        page_count: int,
        *,
        title: str | None = None,
    ) -> None:
        details: dict[str, Any] = {
            "note_id": note_id,
            "model_readable": model_readable,
            "risk_count": risk_count,
            "page_count": page_count,
        }
        if title is not None:
            details["title"] = title
        db.execute(
            "INSERT INTO audit_events VALUES (?, NULL, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                event_type,
                created_at,
                json.dumps(details, ensure_ascii=False),
            ),
        )

    @staticmethod
    def _hydrate(db: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        risks = [
            dict(item)
            for item in db.execute(
                """SELECT r.id AS risk_id, r.risk_number, r.summary
                FROM note_risks nr
                JOIN risk_items r ON r.id=nr.risk_id
                WHERE nr.note_id=? ORDER BY r.risk_number""",
                (row["id"],),
            ).fetchall()
        ]
        pages = [
            dict(item)
            for item in db.execute(
                """SELECT d.id AS document_id, d.filename AS document_name, np.page_number
                FROM note_pages np
                JOIN documents d ON d.id=np.document_id
                WHERE np.note_id=? ORDER BY d.filename, np.page_number""",
                (row["id"],),
            ).fetchall()
        ]
        return {
            "id": row["id"],
            "title": row["title"],
            "body": row["body"],
            "tags": json.loads(row["tags_json"]),
            "model_readable": bool(row["model_readable"]),
            "risks": risks,
            "pages": pages,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
