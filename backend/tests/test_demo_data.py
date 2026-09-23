from __future__ import annotations

import csv
from pathlib import Path

import pytest

from backend.app.db import Database
from backend.app.demo_data import (
    DEMO_FINANCIAL_FILENAME,
    DEMO_PDF_FILENAMES,
    DemoDataError,
    DemoDataService,
)
from backend.app.financial_data import REQUIRED_COLUMNS, FinancialDataService
from backend.app.worker import LocalTaskWorker
from backend.tests.helpers import create_project, write_pdf


def write_financial_fixture(path: Path) -> None:
    rows = [
        list(REQUIRED_COLUMNS),
        ["2024", "FY", "1001", "库存现金", "0", "0", "1000", "0", "1000", "0", "CNY", "1"],
        ["2024", "FY", "4001", "实收资本", "0", "0", "0", "1000", "0", "1000", "CNY", "1"],
        ["2025", "FY", "1001", "库存现金", "900", "0", "200", "0", "1100", "0", "CNY", "1"],
        ["2025", "FY", "4001", "实收资本", "0", "1000", "0", "100", "0", "1100", "CNY", "1"],
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        csv.writer(stream).writerows(rows)


def build_service(tmp_path: Path, *, is_synthetic: bool = True):
    database = Database(tmp_path / "registry")
    project = create_project(
        database,
        tmp_path / "project",
        is_synthetic=is_synthetic,
    )
    fixtures = tmp_path / "mock资料"
    fixtures.mkdir()
    for index, filename in enumerate(DEMO_PDF_FILENAMES):
        write_pdf(fixtures / filename, f"demo-{index}")
    write_financial_fixture(fixtures / DEMO_FINANCIAL_FILENAME)
    service = DemoDataService(database, FinancialDataService(database), fixtures)
    return database, project, service


def process_all(worker: LocalTaskWorker) -> None:
    while claimed := worker._claim_next():
        worker._process(*claimed)


def test_demo_load_is_offline_idempotent_and_uses_normal_worker(tmp_path: Path) -> None:
    database, project, service = build_service(tmp_path)

    first = service.load(project["id"])
    second = service.load(project["id"])

    assert first["queued_task_count"] == 4
    assert first["external_request"] is False
    assert second["queued_task_count"] == 0
    assert second["reused_task_count"] == 4

    process_all(LocalTaskWorker(database))
    root = Path(project["storage_path"])
    with database.connect(root / "app.db") as db:
        assert db.execute("SELECT COUNT(*) count FROM documents").fetchone()["count"] == 3
        assert db.execute("SELECT COUNT(*) count FROM financial_datasets").fetchone()["count"] == 1
        assert db.execute(
            "SELECT COUNT(*) count FROM tasks WHERE status='completed'"
        ).fetchone()["count"] == 4

    third = service.load(project["id"])
    assert third["queued_task_count"] == 0
    assert third["reused_document_count"] == 3
    assert third["reused_financial_dataset"] is True


def test_demo_load_rejects_non_synthetic_project(tmp_path: Path) -> None:
    _, project, service = build_service(tmp_path, is_synthetic=False)

    with pytest.raises(DemoDataError) as error:
        service.load(project["id"])

    assert error.value.code == "DEMO_PROJECT_REQUIRED"
