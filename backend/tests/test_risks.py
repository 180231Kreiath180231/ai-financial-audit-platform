from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.db import Database, utc_now
from backend.app.gateway import ModelGateway
from backend.app.risks import RiskError, RiskRepository
from backend.app.schemas import RiskCreate, RiskEvidenceCreate, RiskTransition
from backend.tests.helpers import create_project


def seed_evidence(database: Database, root: Path) -> str:
    document_id = str(uuid.uuid4())
    now = utc_now()
    with database.connect(root / "app.db") as db:
        db.execute(
            """INSERT INTO documents
            (id, filename, sha256, size_bytes, page_count, parse_method,
             parse_version, stored_path, created_at)
            VALUES (?, 'synthetic-evidence.pdf', ?, 128, 2, 'native_pdf',
                    'pypdf-v1', ?, ?)""",
            (document_id, "a" * 64, str(root / "files" / "synthetic-evidence.pdf"), now),
        )
        for page_number, text in (
            (1, "synthetic supporting evidence text"),
            (2, "synthetic counter evidence text"),
        ):
            db.execute(
                """INSERT INTO pages
                (id, document_id, page_number, block_number, original_text,
                 parse_method, parse_version)
                VALUES (?, ?, ?, 1, ?, 'native_pdf', 'pypdf-v1')""",
                (str(uuid.uuid4()), document_id, page_number, text),
            )
    return document_id


def create_manual_risk(database: Database, project_id: str, document_id: str) -> dict:
    return RiskRepository(database).create(
        project_id,
        RiskCreate(
            risk_type="人工线索",
            summary="Synthetic evidence needs human review",
            evidence=[
                RiskEvidenceCreate(
                    document_id=document_id,
                    page_number=1,
                    block_number=1,
                    quote="synthetic supporting evidence text",
                    direction="support",
                ),
                RiskEvidenceCreate(
                    document_id=document_id,
                    page_number=2,
                    block_number=1,
                    quote="synthetic counter evidence text",
                    direction="counter",
                ),
            ],
        ),
    )


def test_manual_risk_resolves_evidence_and_creates_immutable_v1(tmp_path: Path) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "project")
    root = Path(project["storage_path"])
    document_id = seed_evidence(database, root)

    risk = create_manual_risk(database, project["id"], document_id)

    assert risk["risk_number"] == "R-0001"
    assert risk["risk_level"] == "待评估"
    assert risk["status"] == "待复核"
    assert risk["trigger_rule_id"] == "MANUAL-DRAFT"
    assert risk["model_explanation"] is None
    assert [item["direction"] for item in risk["evidence"]] == ["support", "counter"]
    assert risk["evidence"][0]["quote"] == "synthetic supporting evidence text"
    assert risk["versions"][0]["version"] == 1
    assert risk["versions"][0]["snapshot"]["status"] == "待复核"
    with database.connect(root / "app.db") as db:
        event = db.execute(
            "SELECT details_json FROM audit_events WHERE event_type='risk.created'"
        ).fetchone()
    assert json.loads(event["details_json"])["evidence_count"] == 2


def test_risk_transition_requires_prd_path_and_preserves_history(tmp_path: Path) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "project")
    document_id = seed_evidence(database, Path(project["storage_path"]))
    repository = RiskRepository(database)
    risk = create_manual_risk(database, project["id"], document_id)

    verified = repository.transition(
        project["id"],
        risk["id"],
        RiskTransition(status="已核实", note="已逐页核对合成证据"),
    )

    assert verified["status"] == "已核实"
    assert verified["human_opinion"] == "已逐页核对合成证据"
    assert verified["version"] == 2
    assert [item["version"] for item in verified["versions"]] == [2, 1]
    assert verified["versions"][1]["snapshot"]["status"] == "待复核"
    with pytest.raises(RiskError) as captured:
        repository.transition(
            project["id"],
            risk["id"],
            RiskTransition(status="已排除", note="非法逆向流转"),
        )
    assert captured.value.code == "RISK_TRANSITION_INVALID"


def test_fake_explanation_is_local_audited_and_versioned(tmp_path: Path) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "project")
    document_id = seed_evidence(database, Path(project["storage_path"]))
    repository = RiskRepository(database)
    risk = create_manual_risk(database, project["id"], document_id)

    draft = ModelGateway(database).draft_fake_risk_explanation(
        project["id"],
        summary=risk["summary"],
        support_refs=[f"{document_id}:1:1"],
        counter_refs=[f"{document_id}:2:1"],
    )
    updated = repository.apply_fake_explanation(
        project["id"],
        risk["id"],
        explanation=draft["explanation"],
        uncertainty=draft["uncertainty"],
        provider=draft["provider"],
        actual_model=draft["actual_model"],
        model_call_id=draft["call_id"],
    )

    assert draft["external_request"] is False
    assert updated["actual_model"] == "fake-structured-v1"
    assert updated["version"] == 2
    assert "不构成审计结论" in updated["uncertainty"]
    with database.connect(database.registry_path) as db:
        call = db.execute(
            "SELECT * FROM model_calls WHERE id=?", (draft["call_id"],)
        ).fetchone()
    assert call["status"] == "completed"
    assert call["capability"] == "json_schema"


def test_fake_explanation_cannot_change_human_confirmed_risk(tmp_path: Path) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "project")
    document_id = seed_evidence(database, Path(project["storage_path"]))
    repository = RiskRepository(database)
    risk = create_manual_risk(database, project["id"], document_id)
    verified = repository.transition(
        project["id"],
        risk["id"],
        RiskTransition(status="已核实", note="人工已经确认当前内容"),
    )

    with pytest.raises(RiskError) as captured:
        repository.apply_fake_explanation(
            project["id"],
            risk["id"],
            explanation="未经复核的新解释",
            uncertainty="未经复核",
            provider="Fake Provider",
            actual_model="fake-structured-v1",
            model_call_id="call-after-review",
        )

    assert captured.value.code == "RISK_EXPLANATION_REVIEW_REQUIRED"
    unchanged = repository.get(project["id"], risk["id"])
    assert unchanged["status"] == "已核实"
    assert unchanged["version"] == verified["version"]
    assert unchanged["model_explanation"] is None


def test_risk_creation_rejects_unknown_evidence_block(tmp_path: Path) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "project")
    document_id = seed_evidence(database, Path(project["storage_path"]))

    with pytest.raises(RiskError) as captured:
        RiskRepository(database).create(
            project["id"],
            RiskCreate(
                summary="Unknown evidence must fail closed",
                evidence=[
                    RiskEvidenceCreate(
                        document_id=document_id,
                        page_number=99,
                        block_number=1,
                        quote="unknown evidence",
                        direction="support",
                    )
                ],
            ),
        )
    assert captured.value.code == "EVIDENCE_NOT_FOUND"


def test_risk_text_fields_reject_whitespace_only_values() -> None:
    with pytest.raises(ValidationError):
        RiskCreate(
            summary="     ",
            evidence=[
                RiskEvidenceCreate(
                    document_id="document-1",
                    page_number=1,
                    block_number=1,
                    quote="synthetic evidence",
                    direction="support",
                )
            ],
        )
    with pytest.raises(ValidationError):
        RiskTransition(status="已核实", note="  ")


def test_risk_creation_verifies_quote_and_rejects_conflicting_direction(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "project")
    document_id = seed_evidence(database, Path(project["storage_path"]))
    repository = RiskRepository(database)

    with pytest.raises(RiskError) as mismatch:
        repository.create(
            project["id"],
            RiskCreate(
                summary="Browser quote must be verified",
                evidence=[
                    RiskEvidenceCreate(
                        document_id=document_id,
                        page_number=1,
                        block_number=1,
                        quote="tampered browser quote",
                        direction="support",
                    )
                ],
            ),
        )
    assert mismatch.value.code == "EVIDENCE_QUOTE_MISMATCH"

    with pytest.raises(RiskError) as conflict:
        repository.create(
            project["id"],
            RiskCreate(
                summary="One source must have one direction",
                evidence=[
                    RiskEvidenceCreate(
                        document_id=document_id,
                        page_number=1,
                        block_number=1,
                        quote="synthetic supporting evidence text",
                        direction=direction,
                    )
                    for direction in ("support", "counter")
                ],
            ),
        )
    assert conflict.value.code == "EVIDENCE_DIRECTION_CONFLICT"
