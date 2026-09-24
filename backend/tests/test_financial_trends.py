from decimal import Decimal
from pathlib import Path
from statistics import mean, median, pstdev

from backend.app.db import Database
from backend.app.financial_data import FinancialDataService
from backend.app.risks import RiskRepository
from backend.tests.helpers import create_project


def seed_dataset(
    database: Database,
    root: Path,
    project_id: str,
    values: dict[int, Decimal],
    *,
    start: int,
    end: int,
) -> FinancialDataService:
    service = FinancialDataService(database)
    with database.connect(root / "app.db") as db:
        db.execute(
            """INSERT INTO financial_datasets
            (id, filename, sha256, size_bytes, source_path, encoding, period_type,
             period_start, period_end, row_count, currency, amount_unit, status, created_at)
            VALUES ('dataset-1', 'trend.csv', ?, 100, 'trend.csv', 'utf-8-sig', 'annual',
                    ?, ?, ?, 'CNY', '元', 'active', 'now')""",
            ("b" * 64, f"{start}-FY", f"{end}-FY", len(values) + end - start + 1),
        )
    rows = []
    line_number = 2
    for year in range(start, end + 1):
        if year in values:
            rows.append((
                "dataset-1", line_number, year, "FY", f"{year}-FY", "1001", "库存现金",
                Decimal(0), Decimal(0), Decimal(0), Decimal(0), values[year], Decimal(0),
                "CNY", True, "{}", "[]", "{}",
            ))
            line_number += 1
        rows.append((
            "dataset-1", line_number, year, "FY", f"{year}-FY", "A-TOTAL", "资产总计",
            Decimal(0), Decimal(0), Decimal(0), Decimal(0), Decimal(1000), Decimal(0),
            "CNY", True, "{}", "[]", "{}",
        ))
        line_number += 1
    with service.analysis(root) as analysis:
        analysis.executemany(
            "INSERT INTO trial_balance_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    return service


def test_trend_analysis_exposes_gaps_robust_statistics_and_explicit_ratio(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "project")
    root = Path(project["storage_path"])
    values = {
        2015: Decimal(100), 2016: Decimal(110), 2017: Decimal(120),
        2019: Decimal(140), 2020: Decimal(150), 2021: Decimal(160),
        2022: Decimal(170), 2023: Decimal(180), 2024: Decimal(400),
        2025: Decimal(200),
    }
    service = seed_dataset(database, root, project["id"], values, start=2015, end=2025)

    accounts = service.list_trend_accounts(project["id"], "dataset-1")
    analysis = service.trend_analysis(
        project["id"], "dataset-1", "1001", "A-TOTAL"
    )

    assert [item["account_code"] for item in accounts] == ["1001", "A-TOTAL"]
    assert analysis["sample_count"] == 10
    assert analysis["analysis_version"] == "FIN-TREND-v1"
    assert analysis["sample_quality"] == "limited"
    assert analysis["missing_periods"] == ["2018-FY"]
    assert analysis["denominator"] == {
        "account_code": "A-TOTAL",
        "account_name": "资产总计",
        "basis": "期末净额绝对值（借方-贷方）",
    }
    points = {point["period_key"]: point for point in analysis["points"]}
    assert points["2019-FY"]["direction"] is None
    assert points["2019-FY"]["yoy_change"] is None
    assert points["2024-FY"]["structure_ratio"] == "40.0000"
    assert "MAD 稳健偏离" in points["2024-FY"]["signals"]
    assert "Z-score 辅助偏离，不单独定级" in points["2024-FY"]["signals"]
    assert points["2025-FY"]["turning_point"] is True
    assert points["2025-FY"]["yoy_change"] == "-200.00"
    assert RiskRepository(database).list(project["id"]) == []


def test_trend_analysis_marks_small_sample_as_uncertain(tmp_path: Path) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "small-project")
    root = Path(project["storage_path"])
    service = seed_dataset(
        database,
        root,
        project["id"],
        {2024: Decimal(100), 2025: Decimal(120)},
        start=2024,
        end=2025,
    )

    analysis = service.trend_analysis(project["id"], "dataset-1", "1001")

    assert analysis["sample_quality"] == "insufficient"
    assert "少于 3 期" in analysis["uncertainty"]
    assert analysis["points"][-1]["z_score"] is None
    assert analysis["points"][-1]["robust_z_score"] is None
    assert analysis["denominator"] is None


def test_ten_financial_metrics_match_an_independent_standard_library_oracle(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "oracle-project")
    root = Path(project["storage_path"])
    raw_values = [
        Decimal("10"),
        Decimal("20"),
        Decimal("30"),
        Decimal("40"),
        Decimal("100"),
        Decimal("50"),
    ]
    service = seed_dataset(
        database,
        root,
        project["id"],
        {2020 + index: value for index, value in enumerate(raw_values)},
        start=2020,
        end=2025,
    )

    analysis = service.trend_analysis(
        project["id"], "dataset-1", "1001", "A-TOTAL"
    )
    oracle_mean = mean(raw_values)
    oracle_median = median(raw_values)
    oracle_mad = median([abs(value - oracle_median) for value in raw_values])
    oracle_stddev = pstdev(raw_values)
    last = analysis["points"][-1]

    assert analysis["mean"] == f"{oracle_mean.quantize(Decimal('0.01')):f}"
    assert analysis["median"] == f"{oracle_median.quantize(Decimal('0.01')):f}"
    assert analysis["mad"] == f"{oracle_mad.quantize(Decimal('0.01')):f}"
    assert analysis["standard_deviation"] == (
        f"{oracle_stddev.quantize(Decimal('0.01')):f}"
    )
    assert last["closing_net"] == "50.00"
    assert last["yoy_change"] == "-50.00"
    assert last["yoy_percent"] == "-50.00"
    assert last["direction"] == "down"
    assert last["trend_run"] == 1
    assert last["turning_point"] is True
    assert last["z_score"] == (
        f"{((raw_values[-1] - oracle_mean) / oracle_stddev).quantize(Decimal('0.0001')):f}"
    )
    assert last["robust_z_score"] == (
        f"{(Decimal('0.6745') * (raw_values[-1] - oracle_median) / oracle_mad).quantize(Decimal('0.0001')):f}"
    )
    assert last["structure_ratio"] == "5.0000"
