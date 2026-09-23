from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from .db import Database, utc_now
from .risks import RiskRepository

OUTPUT_SCHEMA_VERSION = "output-snapshot-v1"
RISK_REGISTER_TEMPLATE_VERSION = "format-neutral-risk-register-v1"
CONFIRMED_RISK_STATUSES = ("已核实", "已关闭")


class OutputError(RuntimeError):
    def __init__(self, code: str, message: str, action: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.action = action


class OutputSnapshotService:
    """Create immutable, format-neutral snapshots from confirmed server-side risks."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self.risks = RiskRepository(database)

    def list(self, project_id: str) -> list[dict[str, Any]]:
        root = self.database.project_root(project_id)
        with self.database.connect(root / "app.db") as db:
            rows = db.execute(
                """SELECT id, output_kind, schema_version, template_version,
                risk_count, content_sha256, created_at
                FROM output_snapshots ORDER BY created_at DESC, id DESC"""
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, project_id: str, snapshot_id: str) -> dict[str, Any]:
        root = self.database.project_root(project_id)
        with self.database.connect(root / "app.db") as db:
            row = db.execute(
                "SELECT * FROM output_snapshots WHERE id=?",
                (snapshot_id,),
            ).fetchone()
        if row is None:
            raise KeyError(snapshot_id)
        result = dict(row)
        result["snapshot"] = json.loads(result.pop("snapshot_json"))
        return result

    def create_risk_register(self, project_id: str) -> dict[str, Any]:
        project = self.database.get_project(project_id)
        root = self.database.project_root(project_id)
        snapshot_id = str(uuid.uuid4())
        created_at = utc_now()

        with self.database.connect(root / "app.db") as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                placeholders = ",".join("?" for _ in CONFIRMED_RISK_STATUSES)
                rows = db.execute(
                    f"""SELECT * FROM risk_items WHERE status IN ({placeholders})
                    ORDER BY risk_number""",
                    CONFIRMED_RISK_STATUSES,
                ).fetchall()
                if not rows:
                    raise OutputError(
                        "NO_CONFIRMED_RISKS",
                        "当前项目没有可固化的已核实风险",
                        "先在风险台账完成证据复核并将风险转为“已核实”",
                    )

                risks = [
                    self.risks._hydrate(db, row, include_versions=False)  # noqa: SLF001
                    for row in rows
                ]
                snapshot_risks = [self._snapshot_risk(risk) for risk in risks]
                payload = {
                    "schema_version": OUTPUT_SCHEMA_VERSION,
                    "output_kind": "risk_register",
                    "project": {
                        "id": project["id"],
                        "name": project["name"],
                        "entity_name": project["entity_name"],
                        "year_start": project["year_start"],
                        "year_end": project["year_end"],
                    },
                    "risks": snapshot_risks,
                }
                serialized = json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                content_sha256 = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
                db.execute(
                    """INSERT INTO output_snapshots
                    (id, output_kind, schema_version, template_version, risk_count,
                     content_sha256, snapshot_json, created_at)
                    VALUES (?, 'risk_register', ?, ?, ?, ?, ?, ?)""",
                    (
                        snapshot_id,
                        OUTPUT_SCHEMA_VERSION,
                        RISK_REGISTER_TEMPLATE_VERSION,
                        len(snapshot_risks),
                        content_sha256,
                        serialized,
                        created_at,
                    ),
                )
                db.executemany(
                    """INSERT INTO output_snapshot_risks
                    (snapshot_id, risk_id, risk_number, risk_version, risk_status)
                    VALUES (?, ?, ?, ?, ?)""",
                    [
                        (
                            snapshot_id,
                            risk["risk_id"],
                            risk["risk_number"],
                            risk["risk_version"],
                            risk["status"],
                        )
                        for risk in snapshot_risks
                    ],
                )
                db.execute(
                    "INSERT INTO audit_events VALUES (?, NULL, ?, ?, ?)",
                    (
                        str(uuid.uuid4()),
                        "output.snapshot_created",
                        created_at,
                        json.dumps(
                            {
                                "snapshot_id": snapshot_id,
                                "output_kind": "risk_register",
                                "risk_count": len(snapshot_risks),
                                "content_sha256": content_sha256,
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return self.get(project_id, snapshot_id)

    @staticmethod
    def _snapshot_risk(risk: dict[str, Any]) -> dict[str, Any]:
        evidence = []
        for index, item in enumerate(risk["evidence"], start=1):
            if item["kind"] == "document":
                source_reference = (
                    f"{item['document_name']} · 第 {item['page_number']} 页"
                    f" · 块 {item['block_number']}"
                )
            else:
                source_reference = (
                    f"{item['document_name']} · CSV 行 {item['line_start']}–{item['line_end']}"
                )
            evidence.append(
                {
                    "citation": f"{risk['risk_number']}-E{index:02d}",
                    "source_evidence_id": item["id"],
                    "kind": item["kind"],
                    "direction": item["direction"],
                    "source_reference": source_reference,
                    "quote": item["quote"],
                    "document_id": item.get("document_id"),
                    "page_number": item.get("page_number"),
                    "block_number": item.get("block_number"),
                    "dataset_id": item.get("dataset_id"),
                    "line_start": item.get("line_start"),
                    "line_end": item.get("line_end"),
                    "period_key": item.get("period_key"),
                    "account_code": item.get("account_code"),
                    "parse_method": item.get("parse_method"),
                    "parse_version": item.get("parse_version"),
                }
            )
        if not any(item["direction"] == "support" for item in evidence):
            raise OutputError(
                "RISK_SUPPORT_EVIDENCE_REQUIRED",
                f"{risk['risk_number']} 缺少支持证据，不能生成快照",
                "回到风险台账补充并核对支持证据",
            )
        return {
            "risk_id": risk["id"],
            "risk_number": risk["risk_number"],
            "risk_version": risk["version"],
            "risk_type": risk["risk_type"],
            "risk_level": risk["risk_level"],
            "status": risk["status"],
            "summary": risk["summary"],
            "trigger_rule_id": risk["trigger_rule_id"],
            "trigger_rule_version": risk["trigger_rule_version"],
            "input_values": risk["input_values"],
            "baseline_values": risk["baseline_values"],
            "calculation_result": risk["calculation_result"],
            "model_explanation": risk["model_explanation"],
            "uncertainty": risk["uncertainty"],
            "human_opinion": risk["human_opinion"],
            "model_source": {
                "provider": risk["model_provider"],
                "actual_model": risk["actual_model"],
                "model_call_id": risk["model_call_id"],
            },
            "evidence": evidence,
        }
