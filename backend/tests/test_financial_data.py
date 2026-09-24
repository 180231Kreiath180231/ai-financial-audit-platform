from __future__ import annotations

import csv
from pathlib import Path

from backend.app.db import Database
from backend.app.financial_data import (
    REQUIRED_COLUMNS,
    FinancialDataService,
    inspect_csv,
    sha256_file,
)
from backend.app.risks import RiskRepository
from backend.app.worker import LocalTaskWorker
from backend.tests.helpers import create_project


def write_trial_balance(path: Path, rows: list[list[str]], extras: list[str] | None = None) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow([*REQUIRED_COLUMNS, *(extras or [])])
        writer.writerows(rows)


def synthetic_annual_rows() -> list[list[str]]:
    return [
        ["2024", "FY", "001001", "库存现金", "", "", "1000", "0", "1000", "0", "CNY", "1", "来源A"],
        ["2024", "FY", "004001", "实收资本", "0", "0", "0", "1000", "0", "1000", "CNY", "1", "来源B"],
        ["2025", "FY", "001001", "库存现金", "900", "0", "200", "0", "1100", "0", "CNY", "1", "来源A"],
        ["2025", "FY", "004001", "实收资本", "0", "1000", "0", "150", "0", "1150", "CNY", "1", "来源B"],
    ]


def process_one(worker: LocalTaskWorker) -> None:
    claimed = worker._claim_next()
    assert claimed is not None
    worker._process(*claimed)


def test_preview_import_rules_and_financial_risks_are_traceable(tmp_path: Path) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "project")
    root = Path(project["storage_path"])
    source = root / "incoming" / "synthetic.csv"
    write_trial_balance(source, synthetic_annual_rows(), ["来源系统"])
    service = FinancialDataService(database)

    preview = service.preview(project["id"], "synthetic.csv", source, sha256_file(source))

    assert preview["valid"] is True
    assert preview["encoding"] == "utf-8-sig"
    assert preview["row_count"] == 4
    assert preview["period_start"] == "2024-FY"
    assert preview["period_end"] == "2025-FY"
    assert preview["extra_columns"] == ["来源系统"]
    assert preview["sample_rows"][0]["科目编码"] == "001001"
    assert {warning["code"] for warning in preview["warnings"]} == {
        "CSV_EXTRA_COLUMNS_PRESERVED"
    }

    confirmed = service.confirm(project["id"], preview["preview_id"])
    assert confirmed["task"]["task_type"] == "trial_balance_import"
    process_one(LocalTaskWorker(database))

    datasets = service.list_datasets(project["id"])
    assert len(datasets) == 1
    dataset = service.get_dataset(project["id"], datasets[0]["id"])
    assert dataset["row_count"] == 4
    assert dataset["passed_count"] == 7
    assert dataset["failed_count"] == 4
    assert dataset["unavailable_count"] == 1
    assert len(dataset["rule_results"]) == 12

    failed = [result for result in dataset["rule_results"] if result["status"] == "fail"]
    assert {result["rule_id"] for result in failed} == {
        "TB-BAL-OPEN-001",
        "TB-BAL-MOVEMENT-001",
        "TB-BAL-CLOSE-001",
        "TB-PERIOD-CONTINUITY-001",
    }
    rule_scope_kinds: dict[str, set[str]] = {}
    for result in dataset["rule_results"]:
        rule_scope_kinds.setdefault(result["rule_id"], set()).add(result["scope"]["kind"])
    assert rule_scope_kinds["TB-ACCOUNT-ROLLFORWARD-001"] == {"formula"}
    assert rule_scope_kinds["TB-PERIOD-CONTINUITY-001"] == {"continuity"}
    opening = next(result for result in failed if result["rule_id"] == "TB-BAL-OPEN-001")
    assert opening["calculation_result"]["difference"] == "-100.00"
    detail = service.result_rows(
        project["id"], dataset["id"], opening["id"], offset=0, limit=100
    )
    assert detail["total"] == 2
    assert detail["rows"][0]["line_number"] == 4

    risks = RiskRepository(database).list(project["id"])
    assert len(risks) == 4
    assert all(risk["risk_level"] == "待评估" for risk in risks)
    assert all(risk["evidence"][0]["kind"] == "financial" for risk in risks)
    assert all(risk["versions"] == [] for risk in risks)
    detailed_risk = RiskRepository(database).get(project["id"], risks[0]["id"])
    assert detailed_risk["versions"][0]["snapshot"]["risk_level"] == "待评估"


def test_same_csv_reuses_existing_dataset_and_rule_run(tmp_path: Path) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "project")
    root = Path(project["storage_path"])
    service = FinancialDataService(database)

    first = root / "incoming" / "first.csv"
    write_trial_balance(first, synthetic_annual_rows(), ["来源系统"])
    preview = service.preview(project["id"], "first.csv", first, sha256_file(first))
    service.confirm(project["id"], preview["preview_id"])
    process_one(LocalTaskWorker(database))
    dataset = service.list_datasets(project["id"])[0]

    duplicate = root / "incoming" / "duplicate.csv"
    write_trial_balance(duplicate, synthetic_annual_rows(), ["来源系统"])
    duplicate_preview = service.preview(
        project["id"], "duplicate.csv", duplicate, sha256_file(duplicate)
    )

    assert duplicate_preview["duplicate_dataset_id"] == dataset["id"]
    assert not duplicate.exists()
    confirmed = service.confirm(project["id"], duplicate_preview["preview_id"])
    assert confirmed == {"reused_dataset_id": dataset["id"], "task": None}
    run = service.existing_rule_run(project["id"], dataset["id"])
    assert run["status"] == "completed"
    assert len(RiskRepository(database).list(project["id"])) == 4


def test_invalid_structure_is_rejected_without_partial_dataset(tmp_path: Path) -> None:
    source = tmp_path / "invalid.csv"
    rows = synthetic_annual_rows()
    rows[0][6] = "-1"
    rows[1][10] = "USD"
    write_trial_balance(source, rows, ["来源系统"])

    inspection = inspect_csv(source)

    assert inspection["valid"] is False
    assert {error["code"] for error in inspection["errors"]} == {
        "CSV_AMOUNT_INVALID",
        "CSV_CURRENCY_MIXED",
    }


def test_missing_month_produces_unavailable_not_false_pass(tmp_path: Path) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "project")
    root = Path(project["storage_path"])
    source = root / "incoming" / "gap.csv"
    rows = [
        ["2025", period, code, name, "0", "0", debit, credit, debit, credit, "CNY", "1"]
        for period in ("01", "03")
        for code, name, debit, credit in (
            ("1001", "库存现金", "100", "0"),
            ("4001", "实收资本", "0", "100"),
        )
    ]
    write_trial_balance(source, rows)
    service = FinancialDataService(database)
    preview = service.preview(project["id"], "gap.csv", source, sha256_file(source))
    assert {warning["code"] for warning in preview["warnings"]} == {"CSV_PERIOD_GAP"}
    service.confirm(project["id"], preview["preview_id"])
    process_one(LocalTaskWorker(database))
    dataset = service.get_dataset(project["id"], service.list_datasets(project["id"])[0]["id"])

    unavailable = [
        result
        for result in dataset["rule_results"]
        if result["status"] == "unavailable"
    ]
    assert len(unavailable) == 2
    assert unavailable[-1]["calculation_result"]["reason"] == "period_gap"
    assert RiskRepository(database).list(project["id"]) == []


def test_archive_preserves_rows_results_and_risks(tmp_path: Path) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "project")
    root = Path(project["storage_path"])
    source = root / "incoming" / "archive.csv"
    write_trial_balance(source, synthetic_annual_rows(), ["来源系统"])
    service = FinancialDataService(database)
    preview = service.preview(project["id"], "archive.csv", source, sha256_file(source))
    service.confirm(project["id"], preview["preview_id"])
    process_one(LocalTaskWorker(database))
    dataset_id = service.list_datasets(project["id"])[0]["id"]

    archived = service.archive_dataset(project["id"], dataset_id)

    assert archived["status"] == "archived"
    assert archived["archived_at"] is not None
    assert len(archived["rule_results"]) == 12
    assert len(RiskRepository(database).list(project["id"])) == 4


def test_cancel_after_rule_calculation_does_not_commit_partial_dataset(tmp_path: Path) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "project")
    root = Path(project["storage_path"])
    source = root / "incoming" / "cancel.csv"
    write_trial_balance(source, synthetic_annual_rows(), ["来源系统"])
    service = FinancialDataService(database)
    preview = service.preview(project["id"], "cancel.csv", source, sha256_file(source))
    confirmed = service.confirm(project["id"], preview["preview_id"])
    task_id = confirmed["task"]["id"]
    worker = LocalTaskWorker(database)
    claimed = worker._claim_next()
    assert claimed is not None
    original_run_rules = worker.financial_data._run_rules

    def cancel_after_rules(*args, **kwargs):
        results = original_run_rules(*args, **kwargs)
        with database.connect(root / "app.db") as db:
            db.execute("UPDATE tasks SET status='cancelled' WHERE id=?", (task_id,))
        return results

    worker.financial_data._run_rules = cancel_after_rules  # type: ignore[method-assign]
    worker._process(*claimed)

    with database.connect(root / "app.db") as db:
        task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        dataset_count = db.execute("SELECT COUNT(*) FROM financial_datasets").fetchone()[0]
    assert task["status"] == "cancelled"
    assert dataset_count == 0
    assert not Path(task["incoming_path"]).exists()
    with service.analysis(root) as analysis:
        assert analysis.execute("SELECT COUNT(*) FROM trial_balance_rows").fetchone()[0] == 0
        assert analysis.execute("SELECT COUNT(*) FROM financial_rule_results").fetchone()[0] == 0
