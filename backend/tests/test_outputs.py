from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.db import Database
from backend.app.outputs import OutputError, OutputSnapshotService
from backend.app.risks import RiskRepository
from backend.app.schemas import RiskCreate, RiskEvidenceCreate, RiskTransition
from backend.tests.helpers import create_project
from backend.tests.test_risks import create_manual_risk, seed_evidence


def test_snapshot_requires_confirmed_risk_and_preserves_old_versions(tmp_path: Path) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "project")
    root = Path(project["storage_path"])
    document_id = seed_evidence(database, root)
    repository = RiskRepository(database)
    risk = create_manual_risk(database, project["id"], document_id)
    outputs = OutputSnapshotService(database)

    with pytest.raises(OutputError) as pending:
        outputs.create_risk_register(project["id"])
    assert pending.value.code == "NO_CONFIRMED_RISKS"

    verified = repository.transition(
        project["id"],
        risk["id"],
        RiskTransition(status="已核实", note="已逐页核对合成证据"),
    )
    first = outputs.create_risk_register(project["id"])
    first_risk = first["snapshot"]["risks"][0]

    assert first["risk_count"] == 1
    assert len(first["content_sha256"]) == 64
    assert first_risk["risk_version"] == verified["version"]
    assert first_risk["status"] == "已核实"
    assert [item["citation"] for item in first_risk["evidence"]] == [
        "R-0001-E01",
        "R-0001-E02",
    ]
    assert first_risk["evidence"][0]["source_reference"].endswith("第 1 页 · 块 1")

    repository.transition(
        project["id"],
        risk["id"],
        RiskTransition(status="已关闭", note="复核工作已完成"),
    )
    second = outputs.create_risk_register(project["id"])

    assert second["id"] != first["id"]
    assert second["snapshot"]["risks"][0]["status"] == "已关闭"
    assert outputs.get(project["id"], first["id"])["snapshot"]["risks"][0][
        "status"
    ] == "已核实"
    assert [item["id"] for item in outputs.list(project["id"])] == [
        second["id"],
        first["id"],
    ]

    with database.connect(root / "app.db") as db:
        events = db.execute(
            "SELECT details_json FROM audit_events WHERE event_type='output.snapshot_created'"
        ).fetchall()
    assert len(events) == 2
    assert json.loads(events[0]["details_json"])["risk_count"] == 1


def test_snapshot_rejects_confirmed_risk_without_support_evidence(tmp_path: Path) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "project")
    document_id = seed_evidence(database, Path(project["storage_path"]))
    repository = RiskRepository(database)
    risk = repository.create(
        project["id"],
        RiskCreate(
            summary="Counter evidence alone is insufficient for output",
            evidence=[
                RiskEvidenceCreate(
                    document_id=document_id,
                    page_number=2,
                    block_number=1,
                    quote="synthetic counter evidence text",
                    direction="counter",
                )
            ],
        ),
    )
    repository.transition(
        project["id"],
        risk["id"],
        RiskTransition(status="已核实", note="人工确认仍需补充支持证据"),
    )

    with pytest.raises(OutputError) as captured:
        OutputSnapshotService(database).create_risk_register(project["id"])

    assert captured.value.code == "RISK_SUPPORT_EVIDENCE_REQUIRED"
    assert OutputSnapshotService(database).list(project["id"]) == []
