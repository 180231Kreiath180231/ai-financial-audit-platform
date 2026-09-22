from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from .db import Database, utc_now
from .schemas import RiskCreate, RiskTransition


class RiskError(RuntimeError):
    def __init__(self, code: str, message: str, action: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.action = action


ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "待复核": {"已核实", "已排除", "待补证"},
    "待补证": {"待复核"},
    "已核实": {"已关闭"},
    "已排除": set(),
    "已关闭": set(),
}


class RiskRepository:
    """Project-scoped risk cards with immutable snapshots and resolved evidence."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def list(self, project_id: str) -> list[dict[str, Any]]:
        root = self.database.project_root(project_id)
        with self.database.connect(root / "app.db") as db:
            rows = db.execute(
                "SELECT * FROM risk_items ORDER BY updated_at DESC, risk_number DESC"
            ).fetchall()
            return [self._hydrate(db, row, include_versions=False) for row in rows]

    def get(self, project_id: str, risk_id: str) -> dict[str, Any]:
        root = self.database.project_root(project_id)
        with self.database.connect(root / "app.db") as db:
            row = db.execute("SELECT * FROM risk_items WHERE id=?", (risk_id,)).fetchone()
            if row is None:
                raise KeyError(risk_id)
            return self._hydrate(db, row, include_versions=True)

    def create(self, project_id: str, payload: RiskCreate) -> dict[str, Any]:
        root = self.database.project_root(project_id)
        risk_id = str(uuid.uuid4())
        now = utc_now()
        with self.database.connect(root / "app.db") as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                evidence_rows = self._resolve_evidence(db, payload)
                sequence = int(
                    db.execute(
                        """SELECT COALESCE(MAX(CAST(SUBSTR(risk_number, 3) AS INTEGER)), 0)
                        FROM risk_items WHERE risk_number GLOB 'R-[0-9]*'"""
                    ).fetchone()[0]
                ) + 1
                risk_number = f"R-{sequence:04d}"
                db.execute(
                    """INSERT INTO risk_items
                    (id, risk_number, risk_type, risk_level, status, summary,
                     trigger_rule_id, trigger_rule_version, input_values_json,
                     baseline_values_json, calculation_result_json, uncertainty,
                     created_at, updated_at)
                    VALUES (?, ?, ?, '待评估', '待复核', ?, 'MANUAL-DRAFT', 'v1',
                            '{}', '{}', '{}', ?, ?, ?)""",
                    (
                        risk_id,
                        risk_number,
                        payload.risk_type,
                        payload.summary,
                        "人工证据草稿；尚未执行经确认的确定性规则或真实模型解释。",
                        now,
                        now,
                    ),
                )
                for item, evidence in evidence_rows:
                    db.execute(
                        """INSERT INTO risk_evidence
                        (id, risk_id, document_id, page_number, block_number, quote,
                         direction, parse_method, parse_version, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            str(uuid.uuid4()),
                            risk_id,
                            item.document_id,
                            item.page_number,
                            item.block_number,
                            evidence["quote"],
                            item.direction,
                            evidence["parse_method"],
                            evidence["parse_version"],
                            now,
                        ),
                    )
                row = db.execute("SELECT * FROM risk_items WHERE id=?", (risk_id,)).fetchone()
                hydrated = self._hydrate(db, row, include_versions=False)
                self._insert_version(
                    db,
                    risk_id=risk_id,
                    version=1,
                    snapshot=self._snapshot(hydrated),
                    change_reason="创建人工证据草稿",
                    created_at=now,
                )
                db.execute(
                    "INSERT INTO audit_events VALUES (?, NULL, ?, ?, ?)",
                    (
                        str(uuid.uuid4()),
                        "risk.created",
                        now,
                        json.dumps(
                            {
                                "risk_id": risk_id,
                                "risk_number": risk_number,
                                "evidence_count": len(evidence_rows),
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return self.get(project_id, risk_id)

    def transition(
        self, project_id: str, risk_id: str, payload: RiskTransition
    ) -> dict[str, Any]:
        root = self.database.project_root(project_id)
        now = utc_now()
        with self.database.connect(root / "app.db") as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                current = db.execute(
                    "SELECT * FROM risk_items WHERE id=?", (risk_id,)
                ).fetchone()
                if current is None:
                    raise KeyError(risk_id)
                allowed = ALLOWED_TRANSITIONS[current["status"]]
                if payload.status not in allowed:
                    raise RiskError(
                        "RISK_TRANSITION_INVALID",
                        f"不允许从“{current['status']}”变更为“{payload.status}”",
                        "选择当前状态允许的下一步",
                    )
                next_version = int(current["version"]) + 1
                db.execute(
                    """UPDATE risk_items SET status=?, human_opinion=?, version=?, updated_at=?
                    WHERE id=?""",
                    (payload.status, payload.note, next_version, now, risk_id),
                )
                changed = db.execute(
                    "SELECT * FROM risk_items WHERE id=?", (risk_id,)
                ).fetchone()
                hydrated = self._hydrate(db, changed, include_versions=False)
                self._insert_version(
                    db,
                    risk_id=risk_id,
                    version=next_version,
                    snapshot=self._snapshot(hydrated),
                    change_reason=payload.note,
                    created_at=now,
                )
                db.execute(
                    "INSERT INTO audit_events VALUES (?, NULL, ?, ?, ?)",
                    (
                        str(uuid.uuid4()),
                        "risk.status_changed",
                        now,
                        json.dumps(
                            {
                                "risk_id": risk_id,
                                "from_status": current["status"],
                                "to_status": payload.status,
                                "version": next_version,
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return self.get(project_id, risk_id)

    def apply_fake_explanation(
        self,
        project_id: str,
        risk_id: str,
        *,
        explanation: str,
        uncertainty: str,
        provider: str,
        actual_model: str,
        model_call_id: str,
    ) -> dict[str, Any]:
        root = self.database.project_root(project_id)
        now = utc_now()
        with self.database.connect(root / "app.db") as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                current = db.execute(
                    "SELECT * FROM risk_items WHERE id=?", (risk_id,)
                ).fetchone()
                if current is None:
                    raise KeyError(risk_id)
                next_version = int(current["version"]) + 1
                db.execute(
                    """UPDATE risk_items SET model_explanation=?, uncertainty=?,
                    model_provider=?, actual_model=?, model_call_id=?, version=?, updated_at=?
                    WHERE id=?""",
                    (
                        explanation,
                        uncertainty,
                        provider,
                        actual_model,
                        model_call_id,
                        next_version,
                        now,
                        risk_id,
                    ),
                )
                changed = db.execute(
                    "SELECT * FROM risk_items WHERE id=?", (risk_id,)
                ).fetchone()
                hydrated = self._hydrate(db, changed, include_versions=False)
                self._insert_version(
                    db,
                    risk_id=risk_id,
                    version=next_version,
                    snapshot=self._snapshot(hydrated),
                    change_reason="生成 Fake Provider 合成解释草稿",
                    created_at=now,
                )
                db.execute(
                    "INSERT INTO audit_events VALUES (?, NULL, ?, ?, ?)",
                    (
                        str(uuid.uuid4()),
                        "risk.fake_explanation_created",
                        now,
                        json.dumps(
                            {
                                "risk_id": risk_id,
                                "model_call_id": model_call_id,
                                "version": next_version,
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return self.get(project_id, risk_id)

    @staticmethod
    def _resolve_evidence(
        db: sqlite3.Connection, payload: RiskCreate
    ) -> list[tuple[Any, dict[str, str]]]:
        seen: dict[tuple[str, int, int], str] = {}
        resolved: list[tuple[Any, dict[str, str]]] = []
        for item in payload.evidence:
            key = (item.document_id, item.page_number, item.block_number)
            previous_direction = seen.get(key)
            if previous_direction and previous_direction != item.direction:
                raise RiskError(
                    "EVIDENCE_DIRECTION_CONFLICT",
                    "同一证据片段不能同时标记为支持证据和反证",
                    "为该片段保留一个证据方向",
                )
            if previous_direction:
                continue
            seen[key] = item.direction
            row = db.execute(
                """SELECT original_text, parse_method, parse_version
                FROM pages WHERE document_id=? AND page_number=? AND block_number=?""",
                (item.document_id, item.page_number, item.block_number),
            ).fetchone()
            if row is None:
                raise RiskError(
                    "EVIDENCE_NOT_FOUND",
                    "所选证据页或文本块不存在",
                    "重新搜索并选择项目内的有效证据",
                )
            original_text = row["original_text"]
            quote = item.quote.strip()
            if quote not in original_text:
                raise RiskError(
                    "EVIDENCE_QUOTE_MISMATCH",
                    "所选证据片段与服务端保存的原文不一致",
                    "重新搜索并选择原文命中片段",
                )
            resolved.append(
                (
                    item,
                    {
                        "quote": quote,
                        "parse_method": row["parse_method"],
                        "parse_version": row["parse_version"],
                    },
                )
            )
        return resolved

    @staticmethod
    def _risk_from_row(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        for source, target in (
            ("input_values_json", "input_values"),
            ("baseline_values_json", "baseline_values"),
            ("calculation_result_json", "calculation_result"),
        ):
            result[target] = json.loads(result.pop(source))
        return result

    def _hydrate(
        self, db: sqlite3.Connection, row: sqlite3.Row, *, include_versions: bool
    ) -> dict[str, Any]:
        result = self._risk_from_row(row)
        evidence = db.execute(
            """SELECT e.id, e.document_id, d.filename document_name, e.page_number,
            e.block_number, e.quote, e.direction, e.parse_method, e.parse_version
            FROM risk_evidence e JOIN documents d ON d.id=e.document_id
            WHERE e.risk_id=? ORDER BY e.direction DESC, e.page_number, e.block_number""",
            (row["id"],),
        ).fetchall()
        result["evidence"] = [dict(item) for item in evidence]
        result["versions"] = []
        if include_versions:
            versions = db.execute(
                """SELECT version, change_reason, created_at, snapshot_json
                FROM risk_versions WHERE risk_id=? ORDER BY version DESC""",
                (row["id"],),
            ).fetchall()
            result["versions"] = [
                {
                    "version": item["version"],
                    "change_reason": item["change_reason"],
                    "created_at": item["created_at"],
                    "snapshot": json.loads(item["snapshot_json"]),
                }
                for item in versions
            ]
        return result

    @staticmethod
    def _snapshot(risk: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in risk.items()
            if key not in {"versions", "created_at", "updated_at"}
        }

    @staticmethod
    def _insert_version(
        db: sqlite3.Connection,
        *,
        risk_id: str,
        version: int,
        snapshot: dict[str, Any],
        change_reason: str,
        created_at: str,
    ) -> None:
        db.execute(
            """INSERT INTO risk_versions
            (id, risk_id, version, snapshot_json, change_reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4()),
                risk_id,
                version,
                json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                change_reason,
                created_at,
            ),
        )
