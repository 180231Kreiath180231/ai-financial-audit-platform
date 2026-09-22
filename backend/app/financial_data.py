from __future__ import annotations

import codecs
import csv
import hashlib
import json
import shutil
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import duckdb

from .db import Database, utc_now
from .risks import RiskRepository

MAX_CSV_BYTES = 100 * 1024 * 1024
MAX_CSV_ROWS = 500_000
MONEY_QUANTUM = Decimal("0.01")
RULE_SET_VERSION = "TB-RULESET-v1"
RULE_VERSION = "v1"
REQUIRED_COLUMNS = (
    "年度",
    "期间",
    "科目编码",
    "科目名称",
    "期初借方",
    "期初贷方",
    "本期借方",
    "本期贷方",
    "期末借方",
    "期末贷方",
    "币种",
    "是否末级",
)
AMOUNT_COLUMNS = (
    "期初借方",
    "期初贷方",
    "本期借方",
    "本期贷方",
    "期末借方",
    "期末贷方",
)


class FinancialDataError(RuntimeError):
    def __init__(self, code: str, message: str, action: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.action = action


@dataclass(frozen=True)
class TrialBalanceRow:
    line_number: int
    year: int
    period: str
    account_code: str
    account_name: str
    opening_debit: Decimal
    opening_credit: Decimal
    period_debit: Decimal
    period_credit: Decimal
    closing_debit: Decimal
    closing_credit: Decimal
    currency: str
    raw_json: str
    blank_fields_json: str
    extras_json: str

    @property
    def period_key(self) -> str:
        return f"{self.year}-{self.period}"

    def duckdb_values(self, dataset_id: str) -> tuple[Any, ...]:
        return (
            dataset_id,
            self.line_number,
            self.year,
            self.period,
            self.period_key,
            self.account_code,
            self.account_name,
            self.opening_debit,
            self.opening_credit,
            self.period_debit,
            self.period_credit,
            self.closing_debit,
            self.closing_credit,
            self.currency,
            True,
            self.raw_json,
            self.blank_fields_json,
            self.extras_json,
        )


def _issue(code: str, message: str, action: str, **context: Any) -> dict[str, Any]:
    return {"code": code, "message": message, "action": action, **context}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _money(value: Decimal) -> str:
    return format(value.quantize(MONEY_QUANTUM), ".2f")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def detect_encoding(path: Path) -> str:
    with path.open("rb") as source:
        if source.read(3) == codecs.BOM_UTF8:
            return "utf-8-sig"
    for encoding in ("utf-8", "gb18030"):
        decoder = codecs.getincrementaldecoder(encoding)(errors="strict")
        try:
            with path.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    decoder.decode(chunk)
                decoder.decode(b"", final=True)
            return encoding
        except UnicodeDecodeError:
            continue
    raise FinancialDataError(
        "CSV_ENCODING_UNSUPPORTED",
        "CSV 不是 UTF-8、UTF-8 BOM 或 GB18030 编码",
        "请用受支持的编码重新保存文件",
    )


def _parse_amount(raw: str, *, line_number: int, field: str) -> Decimal:
    value = raw.strip()
    if not value:
        return Decimal("0.00")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise FinancialDataError(
            "CSV_AMOUNT_INVALID",
            f"第 {line_number} 行“{field}”不是有效金额",
            "修正为非负且最多两位小数的数字",
        ) from exc
    if not amount.is_finite() or amount < 0 or amount.as_tuple().exponent < -2:
        raise FinancialDataError(
            "CSV_AMOUNT_INVALID",
            f"第 {line_number} 行“{field}”必须为非负且最多两位小数",
            "使用借贷列表示方向，并将金额保留至分",
        )
    return amount.quantize(MONEY_QUANTUM)


def _normalize_row(
    raw: dict[str | None, str | list[str] | None],
    *,
    line_number: int,
    extra_columns: list[str],
) -> TrialBalanceRow:
    if None in raw or any(raw.get(column) is None for column in REQUIRED_COLUMNS):
        raise FinancialDataError(
            "CSV_ROW_WIDTH_INVALID",
            f"第 {line_number} 行的字段数量与表头不一致",
            "检查逗号和双引号转义后重新上传",
        )
    values = {key: str(value or "") for key, value in raw.items() if key is not None}
    try:
        year_text = values["年度"].strip()
        if not year_text.isdigit():
            raise ValueError
        year = int(year_text)
        if not 2000 <= year <= 2100:
            raise ValueError
    except ValueError as exc:
        raise FinancialDataError(
            "CSV_YEAR_INVALID",
            f"第 {line_number} 行年度无效",
            "年度必须是 2000 至 2100 的四位整数",
        ) from exc
    period = values["期间"].strip().upper()
    if period not in {"FY", *(f"{month:02d}" for month in range(1, 13))}:
        raise FinancialDataError(
            "CSV_PERIOD_INVALID",
            f"第 {line_number} 行期间“{period or '空'}”无效",
            "期间只能填写 01–12 或 FY",
        )
    account_code = values["科目编码"].strip()
    account_name = values["科目名称"].strip()
    currency = values["币种"].strip()
    if not account_code or not account_name or not currency:
        raise FinancialDataError(
            "CSV_REQUIRED_VALUE_MISSING",
            f"第 {line_number} 行缺少科目编码、科目名称或币种",
            "补齐必填文本字段后重新上传",
        )
    if values["是否末级"].strip() != "1":
        raise FinancialDataError(
            "CSV_NON_LEAF_ACCOUNT",
            f"第 {line_number} 行不是末级科目",
            "首版仅导入是否末级为 1 的科目记录",
        )
    amounts = {
        field: _parse_amount(values[field], line_number=line_number, field=field)
        for field in AMOUNT_COLUMNS
    }
    blank_fields = [field for field in AMOUNT_COLUMNS if not values[field].strip()]
    extras = {column: values.get(column, "") for column in extra_columns}
    return TrialBalanceRow(
        line_number=line_number,
        year=year,
        period=period,
        account_code=account_code,
        account_name=account_name,
        opening_debit=amounts["期初借方"],
        opening_credit=amounts["期初贷方"],
        period_debit=amounts["本期借方"],
        period_credit=amounts["本期贷方"],
        closing_debit=amounts["期末借方"],
        closing_credit=amounts["期末贷方"],
        currency=currency,
        raw_json=_json(values),
        blank_fields_json=_json(blank_fields),
        extras_json=_json(extras),
    )


def _open_reader(path: Path, encoding: str) -> tuple[Any, csv.DictReader]:
    csv.field_size_limit(10 * 1024 * 1024)
    stream = path.open("r", encoding=encoding, newline="")
    reader = csv.DictReader(stream, delimiter=",", strict=True)
    return stream, reader


def inspect_csv(path: Path) -> dict[str, Any]:
    encoding = detect_encoding(path)
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    samples: list[dict[str, str]] = []
    currencies: set[str] = set()
    period_kinds: set[str] = set()
    periods: set[tuple[int, str]] = set()
    keys: set[tuple[int, str, str]] = set()
    names: dict[str, str] = {}
    renamed_codes: set[str] = set()
    row_count = 0
    extra_columns: list[str] = []
    try:
        stream, reader = _open_reader(path, encoding)
        with stream:
            headers = reader.fieldnames or []
            if len(headers) != len(set(headers)):
                errors.append(
                    _issue(
                        "CSV_HEADER_DUPLICATE",
                        "CSV 表头包含重复列名",
                        "删除重复列后重新上传",
                    )
                )
                return _inspection_result(path, encoding, errors=errors)
            missing = [column for column in REQUIRED_COLUMNS if column not in headers]
            if missing:
                errors.append(
                    _issue(
                        "CSV_REQUIRED_COLUMNS_MISSING",
                        f"缺少必填列：{'、'.join(missing)}",
                        "下载模板并补齐必填列",
                    )
                )
                return _inspection_result(path, encoding, errors=errors)
            extra_columns = [column for column in headers if column not in REQUIRED_COLUMNS]
            for line_number, raw in enumerate(reader, start=2):
                row_count += 1
                if row_count > MAX_CSV_ROWS:
                    errors.append(
                        _issue(
                            "CSV_ROW_LIMIT_EXCEEDED",
                            f"CSV 超过 {MAX_CSV_ROWS:,} 行上限",
                            "拆分文件后分别导入",
                        )
                    )
                    break
                try:
                    row = _normalize_row(
                        raw, line_number=line_number, extra_columns=extra_columns
                    )
                except FinancialDataError as exc:
                    if len(errors) < 100:
                        errors.append(
                            _issue(
                                exc.code,
                                exc.message,
                                exc.action,
                                line_number=line_number,
                            )
                        )
                    continue
                key = (row.year, row.period, row.account_code)
                if key in keys and len(errors) < 100:
                    errors.append(
                        _issue(
                            "CSV_PRIMARY_KEY_DUPLICATE",
                            f"第 {line_number} 行的年度、期间和科目编码重复",
                            "每个期间只保留一条末级科目记录",
                            line_number=line_number,
                            field="科目编码",
                        )
                    )
                keys.add(key)
                previous_name = names.setdefault(row.account_code, row.account_name)
                if previous_name != row.account_name:
                    renamed_codes.add(row.account_code)
                currencies.add(row.currency)
                period_kinds.add("annual" if row.period == "FY" else "monthly")
                periods.add((row.year, row.period))
                if len(samples) < 20:
                    samples.append(
                        {
                            "行号": str(row.line_number),
                            "年度": str(row.year),
                            "期间": row.period,
                            "科目编码": row.account_code,
                            "科目名称": row.account_name,
                            "期末借方": _money(row.closing_debit),
                            "期末贷方": _money(row.closing_credit),
                            "币种": row.currency,
                        }
                    )
    except csv.Error as exc:
        errors.append(
            _issue(
                "CSV_PARSE_ERROR",
                f"CSV 解析失败：{exc}",
                "检查逗号分隔和双引号转义后重新上传",
            )
        )
    if row_count == 0:
        errors.append(_issue("CSV_EMPTY", "CSV 不包含数据行", "至少添加一条末级科目记录"))
    if len(currencies) > 1:
        errors.append(
            _issue(
                "CSV_CURRENCY_MIXED",
                f"同一文件包含多个币种：{'、'.join(sorted(currencies))}",
                "按币种拆分文件后重新上传",
            )
        )
    if len(period_kinds) > 1:
        errors.append(
            _issue(
                "CSV_PERIOD_GRAIN_MIXED",
                "同一文件混用了月度期间和 FY",
                "月度与年度数据必须分开导入",
            )
        )
    for code in sorted(renamed_codes)[:50]:
        warnings.append(
            _issue(
                "CSV_ACCOUNT_NAME_CHANGED",
                f"科目编码 {code} 在不同期间使用了不同名称",
                "导入后复核科目名称映射",
                field="科目名称",
            )
        )
    if extra_columns:
        warnings.append(
            _issue(
                "CSV_EXTRA_COLUMNS_PRESERVED",
                f"检测到 {len(extra_columns)} 个额外列，将原样保存但不参与计算",
                "确认预览后继续",
            )
        )
    period_type = next(iter(period_kinds), "monthly")
    ordered_periods = sorted(periods, key=_period_sort_key)
    if _has_period_gap(ordered_periods, period_type):
        warnings.append(
            _issue(
                "CSV_PERIOD_GAP",
                "数据期间不连续；系统不会跨缺失期间执行衔接检查",
                "确认缺失期间符合预期，或补齐后重新上传",
            )
        )
    return _inspection_result(
        path,
        encoding,
        errors=errors,
        warnings=warnings,
        samples=samples,
        row_count=row_count,
        currency=next(iter(currencies), ""),
        period_type=period_type,
        periods=ordered_periods,
        extra_columns=extra_columns,
    )


def _inspection_result(
    path: Path,
    encoding: str,
    *,
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]] | None = None,
    samples: list[dict[str, str]] | None = None,
    row_count: int = 0,
    currency: str = "",
    period_type: str = "monthly",
    periods: list[tuple[int, str]] | None = None,
    extra_columns: list[str] | None = None,
) -> dict[str, Any]:
    period_values = periods or []
    return {
        "valid": not errors,
        "encoding": encoding,
        "size_bytes": path.stat().st_size,
        "row_count": row_count,
        "currency": currency,
        "amount_unit": "元",
        "period_type": period_type,
        "period_start": _period_key(*period_values[0]) if period_values else "",
        "period_end": _period_key(*period_values[-1]) if period_values else "",
        "extra_columns": extra_columns or [],
        "warnings": warnings or [],
        "errors": errors,
        "sample_rows": samples or [],
    }


def _period_sort_key(period: tuple[int, str]) -> int:
    year, value = period
    return year if value == "FY" else year * 12 + int(value) - 1


def _period_key(year: int, period: str) -> str:
    return f"{year}-{period}"


def _has_period_gap(periods: list[tuple[int, str]], period_type: str) -> bool:
    if len(periods) < 2:
        return False
    values = [_period_sort_key(period) for period in periods]
    expected = 1 if period_type == "annual" else 1
    return any(current - previous != expected for previous, current in zip(values, values[1:]))


def iter_rows(path: Path, encoding: str, extra_columns: list[str]) -> Iterator[TrialBalanceRow]:
    stream, reader = _open_reader(path, encoding)
    with stream:
        for line_number, raw in enumerate(reader, start=2):
            yield _normalize_row(raw, line_number=line_number, extra_columns=extra_columns)


class FinancialDataService:
    def __init__(self, database: Database) -> None:
        self.database = database

    @contextmanager
    def analysis(self, root: Path) -> Iterator[duckdb.DuckDBPyConnection]:
        connection = duckdb.connect(str(root / "analysis.duckdb"))
        try:
            connection.execute("SET memory_limit='2GB'")
            connection.execute("SET threads=2")
            self._ensure_analysis_schema(connection)
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _ensure_analysis_schema(db: duckdb.DuckDBPyConnection) -> None:
        db.execute(
            """CREATE TABLE IF NOT EXISTS trial_balance_rows (
                dataset_id VARCHAR NOT NULL,
                line_number INTEGER NOT NULL,
                year INTEGER NOT NULL,
                period VARCHAR NOT NULL,
                period_key VARCHAR NOT NULL,
                account_code VARCHAR NOT NULL,
                account_name VARCHAR NOT NULL,
                opening_debit DECIMAL(38,2) NOT NULL,
                opening_credit DECIMAL(38,2) NOT NULL,
                period_debit DECIMAL(38,2) NOT NULL,
                period_credit DECIMAL(38,2) NOT NULL,
                closing_debit DECIMAL(38,2) NOT NULL,
                closing_credit DECIMAL(38,2) NOT NULL,
                currency VARCHAR NOT NULL,
                is_leaf BOOLEAN NOT NULL,
                raw_json VARCHAR NOT NULL,
                blank_fields_json VARCHAR NOT NULL,
                extras_json VARCHAR NOT NULL,
                PRIMARY KEY(dataset_id, line_number)
            )"""
        )
        db.execute(
            """CREATE TABLE IF NOT EXISTS financial_rule_results (
                id VARCHAR PRIMARY KEY,
                run_id VARCHAR NOT NULL,
                dataset_id VARCHAR NOT NULL,
                rule_id VARCHAR NOT NULL,
                rule_version VARCHAR NOT NULL,
                period_key VARCHAR NOT NULL,
                status VARCHAR NOT NULL,
                summary VARCHAR NOT NULL,
                input_values_json VARCHAR NOT NULL,
                baseline_values_json VARCHAR NOT NULL,
                calculation_result_json VARCHAR NOT NULL,
                scope_json VARCHAR NOT NULL,
                affected_count INTEGER NOT NULL,
                line_start INTEGER,
                line_end INTEGER,
                created_at VARCHAR NOT NULL
            )"""
        )
        db.execute(
            """CREATE TABLE IF NOT EXISTS financial_rule_result_rows (
                result_id VARCHAR NOT NULL,
                dataset_id VARCHAR NOT NULL,
                line_number INTEGER NOT NULL,
                reason VARCHAR NOT NULL,
                PRIMARY KEY(result_id, dataset_id, line_number)
            )"""
        )

    def preview(self, project_id: str, filename: str, path: Path, sha256: str) -> dict[str, Any]:
        root = self.database.project_root(project_id)
        inspection = inspect_csv(path)
        duplicate_id = None
        with self.database.connect(root / "app.db") as db:
            duplicate = db.execute(
                "SELECT id FROM financial_datasets WHERE sha256=?", (sha256,)
            ).fetchone()
            duplicate_id = duplicate["id"] if duplicate else None
        if not inspection["valid"]:
            path.unlink(missing_ok=True)
            return {"preview_id": None, "duplicate_dataset_id": None, **inspection}
        preview_id = str(uuid.uuid4())
        now = utc_now()
        if duplicate_id:
            path.unlink(missing_ok=True)
        with self.database.connect(root / "app.db") as db:
            db.execute(
                """INSERT INTO financial_import_previews
                (id, filename, sha256, size_bytes, stored_path, encoding, period_type,
                 period_start, period_end, row_count, currency, extra_columns_json,
                 warnings_json, sample_rows_json, duplicate_dataset_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    preview_id,
                    filename,
                    sha256,
                    inspection["size_bytes"],
                    str(path) if not duplicate_id else "",
                    inspection["encoding"],
                    inspection["period_type"],
                    inspection["period_start"],
                    inspection["period_end"],
                    inspection["row_count"],
                    inspection["currency"],
                    _json(inspection["extra_columns"]),
                    _json(inspection["warnings"]),
                    _json(inspection["sample_rows"]),
                    duplicate_id,
                    now,
                ),
            )
        self.database.record_project_event(
            root,
            "financial.preview_created",
            details={
                "preview_id": preview_id,
                "sha256": sha256,
                "row_count": inspection["row_count"],
                "duplicate": bool(duplicate_id),
            },
        )
        return {
            "preview_id": preview_id,
            "duplicate_dataset_id": duplicate_id,
            **inspection,
        }

    def confirm(self, project_id: str, preview_id: str) -> dict[str, Any]:
        root = self.database.project_root(project_id)
        with self.database.connect(root / "app.db") as db:
            preview = db.execute(
                "SELECT * FROM financial_import_previews WHERE id=?", (preview_id,)
            ).fetchone()
        if preview is None:
            raise FinancialDataError(
                "CSV_PREVIEW_NOT_FOUND", "导入预览不存在或已失效", "重新选择 CSV 并生成预览"
            )
        if preview["duplicate_dataset_id"]:
            return {"reused_dataset_id": preview["duplicate_dataset_id"], "task": None}
        if preview["confirmed_at"]:
            with self.database.connect(root / "app.db") as db:
                task = db.execute(
                    """SELECT * FROM tasks WHERE task_type='trial_balance_import'
                    AND incoming_path=? ORDER BY created_at DESC LIMIT 1""",
                    (preview["stored_path"],),
                ).fetchone()
            if task:
                return {"reused_dataset_id": None, "task": dict(task)}
            raise FinancialDataError(
                "CSV_PREVIEW_ALREADY_CONFIRMED",
                "该预览已确认",
                "刷新数据集和任务状态",
            )
        source = Path(preview["stored_path"])
        if not source.is_file() or sha256_file(source) != preview["sha256"]:
            raise FinancialDataError(
                "CSV_PREVIEW_SOURCE_CHANGED",
                "预览对应的本地文件已丢失或发生变化",
                "重新选择原始 CSV",
            )
        dataset_id = str(uuid.uuid4())
        task_id = str(uuid.uuid4())
        destination = root / "financial" / f"{dataset_id}.csv"
        shutil.move(str(source), destination)
        now = utc_now()
        try:
            with self.database.connect(root / "app.db") as db:
                db.execute("BEGIN IMMEDIATE")
                try:
                    db.execute(
                        "UPDATE financial_import_previews SET confirmed_at=?, stored_path=? WHERE id=?",
                        (now, str(destination), preview_id),
                    )
                    db.execute(
                        """INSERT INTO tasks
                        (id, task_type, filename, incoming_path, status, progress,
                         current_step, dataset_id, created_at, updated_at)
                        VALUES (?, 'trial_balance_import', ?, ?, 'queued', 0,
                                '等待结构化数据工作器', ?, ?, ?)""",
                        (task_id, preview["filename"], str(destination), dataset_id, now, now),
                    )
                    task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
                    db.execute("COMMIT")
                except Exception:
                    db.execute("ROLLBACK")
                    raise
        except Exception:
            if destination.exists() and not source.exists():
                shutil.move(str(destination), source)
            raise
        self.database.record_project_event(
            root,
            "task.queued",
            task_id=task_id,
            details={"task_type": "trial_balance_import", "dataset_id": dataset_id},
        )
        return {"reused_dataset_id": None, "task": dict(task)}

    def process_import(
        self,
        root: Path,
        task_id: str,
        safe_point: Callable[[Path, str, Path], bool],
        update_task: Callable[..., None],
    ) -> None:
        with self.database.connect(root / "app.db") as db:
            task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if task is None:
            return
        source = Path(task["incoming_path"])
        if not source.is_file():
            raise FinancialDataError(
                "FILE_MISSING", "待处理 CSV 不存在", "重新选择原始 CSV 上传"
            )
        inspection = inspect_csv(source)
        if not inspection["valid"]:
            first = inspection["errors"][0]
            raise FinancialDataError(first["code"], first["message"], first["action"])
        update_task(root, task_id, progress=25, current_step="写入本地分析库")
        if not safe_point(root, task_id, source):
            return
        sha256 = sha256_file(source)
        with self.database.connect(root / "app.db") as db:
            duplicate = db.execute(
                "SELECT id FROM financial_datasets WHERE sha256=?", (sha256,)
            ).fetchone()
        if duplicate:
            self._complete_duplicate_task(root, task_id, duplicate["id"])
            source.unlink(missing_ok=True)
            return
        dataset_id = task["dataset_id"] or str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        extra_columns = inspection["extra_columns"]
        with self.analysis(root) as analysis:
            analysis.execute("BEGIN TRANSACTION")
            try:
                batch: list[tuple[Any, ...]] = []
                for row in iter_rows(source, inspection["encoding"], extra_columns):
                    batch.append(row.duckdb_values(dataset_id))
                    if len(batch) >= 2_000:
                        analysis.executemany(
                            "INSERT INTO trial_balance_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            batch,
                        )
                        batch.clear()
                        if not safe_point(root, task_id, source):
                            analysis.execute("ROLLBACK")
                            return
                if batch:
                    analysis.executemany(
                        "INSERT INTO trial_balance_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        batch,
                    )
                update_task(root, task_id, progress=65, current_step="执行确定性财务规则")
                if not safe_point(root, task_id, source):
                    analysis.execute("ROLLBACK")
                    return
                results = self._run_rules(analysis, dataset_id, run_id, inspection)
                analysis.execute("COMMIT")
            except Exception:
                analysis.execute("ROLLBACK")
                raise
        if not safe_point(root, task_id, source):
            with self.analysis(root) as analysis:
                self._delete_analysis_dataset(analysis, dataset_id)
            return
        try:
            committed = self._commit_metadata_and_risks(
                root,
                task_id,
                dataset_id,
                run_id,
                source,
                sha256,
                inspection,
                results,
            )
            if not committed:
                with self.analysis(root) as analysis:
                    self._delete_analysis_dataset(analysis, dataset_id)
        except Exception:
            with self.analysis(root) as analysis:
                self._delete_analysis_dataset(analysis, dataset_id)
            raise

    def _complete_duplicate_task(self, root: Path, task_id: str, dataset_id: str) -> None:
        with self.database.connect(root / "app.db") as db:
            db.execute(
                """UPDATE tasks SET status='completed', progress=100,
                current_step='已复用现有数据集', result_kind='duplicate', dataset_id=?,
                error_code=NULL, error_message=NULL, next_action=NULL, updated_at=?
                WHERE id=? AND status='running'""",
                (dataset_id, utc_now(), task_id),
            )
        self.database.record_project_event(
            root,
            "task.completed",
            task_id=task_id,
            details={"result_kind": "duplicate", "dataset_id": dataset_id},
        )

    @staticmethod
    def _delete_analysis_dataset(db: duckdb.DuckDBPyConnection, dataset_id: str) -> None:
        result_ids = [
            row[0]
            for row in db.execute(
                "SELECT id FROM financial_rule_results WHERE dataset_id=?", [dataset_id]
            ).fetchall()
        ]
        for result_id in result_ids:
            db.execute("DELETE FROM financial_rule_result_rows WHERE result_id=?", [result_id])
        db.execute("DELETE FROM financial_rule_results WHERE dataset_id=?", [dataset_id])
        db.execute("DELETE FROM trial_balance_rows WHERE dataset_id=?", [dataset_id])

    def _run_rules(
        self,
        db: duckdb.DuckDBPyConnection,
        dataset_id: str,
        run_id: str,
        inspection: dict[str, Any],
    ) -> list[dict[str, Any]]:
        created_at = utc_now()
        results: list[dict[str, Any]] = []
        results.append(
            self._insert_rule_result(
                db,
                run_id,
                dataset_id,
                "TB-STRUCT-001",
                "dataset",
                "pass",
                "必填字段、格式、金额精度与末级科目检查通过",
                {"row_count": inspection["row_count"], "encoding": inspection["encoding"]},
                {"required_columns": list(REQUIRED_COLUMNS), "amount_unit": "元"},
                {"error_count": 0},
                {"kind": "dataset"},
                [],
                created_at,
            )
        )
        results.append(
            self._insert_rule_result(
                db,
                run_id,
                dataset_id,
                "TB-UNIQUE-001",
                "dataset",
                "pass",
                "年度、期间与科目编码唯一性检查通过",
                {"row_count": inspection["row_count"]},
                {"unique_key": ["年度", "期间", "科目编码"]},
                {"duplicate_count": 0},
                {"kind": "dataset"},
                [],
                created_at,
            )
        )
        totals = db.execute(
            """SELECT period_key, MIN(line_number), MAX(line_number), COUNT(*),
            SUM(opening_debit), SUM(opening_credit), SUM(period_debit), SUM(period_credit),
            SUM(closing_debit), SUM(closing_credit)
            FROM trial_balance_rows WHERE dataset_id=? GROUP BY period_key ORDER BY period_key""",
            [dataset_id],
        ).fetchall()
        total_rules = (
            ("TB-BAL-OPEN-001", "期初借贷总额", 4, 5),
            ("TB-BAL-MOVEMENT-001", "本期发生额借贷", 6, 7),
            ("TB-BAL-CLOSE-001", "期末借贷总额", 8, 9),
        )
        for total in totals:
            period_key, line_start, line_end, row_count = total[:4]
            for rule_id, label, debit_index, credit_index in total_rules:
                debit = total[debit_index]
                credit = total[credit_index]
                difference = debit - credit
                status = "pass" if abs(difference) <= MONEY_QUANTUM else "fail"
                results.append(
                    self._insert_rule_result(
                        db,
                        run_id,
                        dataset_id,
                        rule_id,
                        period_key,
                        status,
                        f"{period_key} {label}{'平衡' if status == 'pass' else '不平衡'}",
                        {"debit_total": _money(debit), "credit_total": _money(credit)},
                        {"tolerance": "0.01", "currency": inspection["currency"]},
                        {"difference": _money(difference)},
                        {"kind": "period", "period_key": period_key},
                        [],
                        created_at,
                        affected_count=row_count if status == "fail" else 0,
                        line_bounds=(line_start, line_end) if status == "fail" else None,
                    )
                )
        formula_rows = db.execute(
            """SELECT line_number, period_key, account_code, account_name,
            opening_debit, opening_credit, period_debit, period_credit,
            closing_debit, closing_credit,
            (closing_debit-closing_credit) actual_net,
            (opening_debit-opening_credit+period_debit-period_credit) expected_net
            FROM trial_balance_rows WHERE dataset_id=? AND (
                ABS((closing_debit-closing_credit) -
                    (opening_debit-opening_credit+period_debit-period_credit)) > 0.01
                OR (opening_debit > 0 AND opening_credit > 0)
                OR (closing_debit > 0 AND closing_credit > 0)
            ) ORDER BY period_key, line_number""",
            [dataset_id],
        ).fetchall()
        formula_by_period: dict[str, list[tuple[Any, ...]]] = {}
        for row in formula_rows:
            formula_by_period.setdefault(row[1], []).append(row)
        for total in totals:
            period_key = total[0]
            affected = formula_by_period.get(period_key, [])
            status = "fail" if affected else "pass"
            row_refs = []
            for row in affected:
                reasons: list[str] = []
                if abs(row[10] - row[11]) > MONEY_QUANTUM:
                    reasons.append("余额公式不成立")
                if row[4] > 0 and row[5] > 0:
                    reasons.append("期初借贷同时有余额")
                if row[8] > 0 and row[9] > 0:
                    reasons.append("期末借贷同时有余额")
                row_refs.append((row[0], row[0], "、".join(reasons)))
            results.append(
                self._insert_rule_result(
                    db,
                    run_id,
                    dataset_id,
                    "TB-ROLLFORWARD-001",
                    period_key,
                    status,
                    f"{period_key} 单科目余额公式{'通过' if status == 'pass' else f'存在 {len(affected)} 条异常'}",
                    {"checked_rows": total[3]},
                    {
                        "formula": "期末借方-期末贷方=期初借方-期初贷方+本期借方-本期贷方",
                        "tolerance": "0.01",
                    },
                    {"affected_count": len(affected)},
                    {"kind": "formula", "period_key": period_key},
                    row_refs,
                    created_at,
                )
            )
        periods = [(int(value.split("-", 1)[0]), value.split("-", 1)[1]) for value in (row[0] for row in totals)]
        if periods:
            first_key = _period_key(*periods[0])
            results.append(
                self._insert_rule_result(
                    db,
                    run_id,
                    dataset_id,
                    "TB-ROLLFORWARD-001",
                    first_key,
                    "unavailable",
                    f"{first_key} 没有前置期间，无法执行跨期衔接检查",
                    {"current_period": first_key},
                    {"required_previous_period": True},
                    {"reason": "missing_baseline"},
                    {"kind": "continuity", "period_key": first_key},
                    [],
                    created_at,
                )
            )
        for previous, current in zip(periods, periods[1:]):
            previous_key = _period_key(*previous)
            current_key = _period_key(*current)
            if _period_sort_key(current) - _period_sort_key(previous) != 1:
                results.append(
                    self._insert_rule_result(
                        db,
                        run_id,
                        dataset_id,
                        "TB-ROLLFORWARD-001",
                        current_key,
                        "unavailable",
                        f"{previous_key} 至 {current_key} 期间不连续，未跨期计算",
                        {"previous_period": previous_key, "current_period": current_key},
                        {"required_adjacent": True},
                        {"reason": "period_gap"},
                        {"kind": "continuity", "period_key": current_key},
                        [],
                        created_at,
                    )
                )
                continue
            affected = db.execute(
                """SELECT COALESCE(c.line_number, p.line_number) line_number,
                COALESCE(c.account_code, p.account_code) account_code,
                COALESCE(c.account_name, p.account_name) account_name,
                COALESCE(p.closing_debit-p.closing_credit, 0) previous_net,
                COALESCE(c.opening_debit-c.opening_credit, 0) current_net,
                CASE WHEN p.line_number IS NULL THEN '新增科目期初非零'
                     WHEN c.line_number IS NULL THEN '科目消失但前期期末非零'
                     ELSE '期初与前期期末不衔接' END reason
                FROM (SELECT * FROM trial_balance_rows WHERE dataset_id=? AND period_key=?) p
                FULL OUTER JOIN (SELECT * FROM trial_balance_rows WHERE dataset_id=? AND period_key=?) c
                ON p.account_code=c.account_code
                WHERE ABS(COALESCE(p.closing_debit-p.closing_credit, 0) -
                          COALESCE(c.opening_debit-c.opening_credit, 0)) > 0.01
                ORDER BY line_number""",
                [dataset_id, previous_key, dataset_id, current_key],
            ).fetchall()
            status = "fail" if affected else "pass"
            results.append(
                self._insert_rule_result(
                    db,
                    run_id,
                    dataset_id,
                    "TB-ROLLFORWARD-001",
                    current_key,
                    status,
                    f"{previous_key} 至 {current_key} 跨期衔接{'通过' if status == 'pass' else f'存在 {len(affected)} 条异常'}",
                    {"previous_period": previous_key, "current_period": current_key},
                    {"tolerance": "0.01", "comparison": "前期期末净额与本期期初净额"},
                    {"affected_count": len(affected)},
                    {
                        "kind": "continuity",
                        "previous_period": previous_key,
                        "period_key": current_key,
                    },
                    [(row[0], row[0], row[5]) for row in affected],
                    created_at,
                )
            )
        return results

    def _insert_rule_result(
        self,
        db: duckdb.DuckDBPyConnection,
        run_id: str,
        dataset_id: str,
        rule_id: str,
        period_key: str,
        status: str,
        summary: str,
        input_values: dict[str, Any],
        baseline_values: dict[str, Any],
        calculation_result: dict[str, Any],
        scope: dict[str, Any],
        row_refs: list[tuple[int, int, str]],
        created_at: str,
        *,
        affected_count: int | None = None,
        line_bounds: tuple[int, int] | None = None,
    ) -> dict[str, Any]:
        result_id = str(uuid.uuid4())
        line_start = (
            line_bounds[0]
            if line_bounds
            else min((item[0] for item in row_refs), default=None)
        )
        line_end = (
            line_bounds[1]
            if line_bounds
            else max((item[1] for item in row_refs), default=None)
        )
        count = len(row_refs) if affected_count is None else affected_count
        db.execute(
            "INSERT INTO financial_rule_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                result_id,
                run_id,
                dataset_id,
                rule_id,
                RULE_VERSION,
                period_key,
                status,
                summary,
                _json(input_values),
                _json(baseline_values),
                _json(calculation_result),
                _json(scope),
                count,
                line_start,
                line_end,
                created_at,
            ],
        )
        for start, end, reason in row_refs:
            for line_number in range(start, end + 1):
                db.execute(
                    "INSERT OR IGNORE INTO financial_rule_result_rows VALUES (?, ?, ?, ?)",
                    [result_id, dataset_id, line_number, reason],
                )
        return {
            "id": result_id,
            "rule_id": rule_id,
            "rule_version": RULE_VERSION,
            "period_key": period_key,
            "status": status,
            "summary": summary,
            "input_values": input_values,
            "baseline_values": baseline_values,
            "calculation_result": calculation_result,
            "scope": scope,
            "affected_count": count,
            "line_start": line_start,
            "line_end": line_end,
        }

    def _commit_metadata_and_risks(
        self,
        root: Path,
        task_id: str,
        dataset_id: str,
        run_id: str,
        source: Path,
        sha256: str,
        inspection: dict[str, Any],
        results: list[dict[str, Any]],
    ) -> bool:
        now = utc_now()
        passed = sum(result["status"] == "pass" for result in results)
        failed = sum(result["status"] == "fail" for result in results)
        unavailable = sum(result["status"] == "unavailable" for result in results)
        with self.database.connect(root / "app.db") as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                task = db.execute("SELECT status, filename FROM tasks WHERE id=?", (task_id,)).fetchone()
                if task is None or task["status"] != "running":
                    db.execute("ROLLBACK")
                    return False
                db.execute(
                    """INSERT INTO financial_datasets
                    (id, filename, sha256, size_bytes, source_path, encoding, period_type,
                     period_start, period_end, row_count, currency, amount_unit, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '元', ?)""",
                    (
                        dataset_id,
                        task["filename"],
                        sha256,
                        inspection["size_bytes"],
                        str(source),
                        inspection["encoding"],
                        inspection["period_type"],
                        inspection["period_start"],
                        inspection["period_end"],
                        inspection["row_count"],
                        inspection["currency"],
                        now,
                    ),
                )
                db.execute(
                    """INSERT INTO financial_rule_runs
                    (id, dataset_id, rule_set_version, status, passed_count, failed_count,
                     unavailable_count, created_at, completed_at)
                    VALUES (?, ?, ?, 'completed', ?, ?, ?, ?, ?)""",
                    (run_id, dataset_id, RULE_SET_VERSION, passed, failed, unavailable, now, now),
                )
                sequence = int(
                    db.execute(
                        """SELECT COALESCE(MAX(CAST(SUBSTR(risk_number, 3) AS INTEGER)), 0)
                        FROM risk_items WHERE risk_number GLOB 'R-[0-9]*'"""
                    ).fetchone()[0]
                )
                for result in results:
                    if result["status"] != "fail":
                        continue
                    sequence += 1
                    self._insert_rule_risk(
                        db,
                        dataset_id,
                        task["filename"],
                        sha256,
                        result,
                        sequence,
                        now,
                    )
                db.execute(
                    """UPDATE tasks SET status='completed', progress=100,
                    current_step='财务数据与规则结果已提交', result_kind='imported',
                    dataset_id=?, error_code=NULL, error_message=NULL, next_action=NULL,
                    updated_at=? WHERE id=? AND status='running'""",
                    (dataset_id, now, task_id),
                )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        self.database.record_project_event(
            root,
            "task.completed",
            task_id=task_id,
            details={
                "result_kind": "imported",
                "dataset_id": dataset_id,
                "rule_run_id": run_id,
                "failed_rule_results": failed,
            },
        )
        return True

    @staticmethod
    def _insert_rule_risk(
        db: Any,
        dataset_id: str,
        filename: str,
        sha256: str,
        result: dict[str, Any],
        sequence: int,
        now: str,
    ) -> None:
        risk_id = str(uuid.uuid4())
        risk_number = f"R-{sequence:04d}"
        uncertainty = "确定性规则已复算；异常仍需人工判断数据质量、会计口径与审计影响。"
        db.execute(
            """INSERT INTO risk_items
            (id, risk_number, risk_type, risk_level, status, summary,
             trigger_rule_id, trigger_rule_version, input_values_json,
             baseline_values_json, calculation_result_json, uncertainty,
             version, created_at, updated_at, source_rule_result_id)
            VALUES (?, ?, '财务规则异常', '待评估', '待复核', ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)""",
            (
                risk_id,
                risk_number,
                result["summary"],
                result["rule_id"],
                result["rule_version"],
                _json(result["input_values"]),
                _json(result["baseline_values"]),
                _json(result["calculation_result"]),
                uncertainty,
                now,
                now,
                result["id"],
            ),
        )
        line_start = result["line_start"] or 2
        line_end = result["line_end"] or line_start
        evidence_id = str(uuid.uuid4())
        quote = (
            f"{filename} · CSV 行 {line_start}"
            + (f"–{line_end}" if line_end != line_start else "")
            + f" · {result['summary']} · SHA-256 {sha256}"
        )
        db.execute(
            """INSERT INTO financial_risk_evidence
            (id, risk_id, dataset_id, line_start, line_end, period_key,
             account_code, quote, direction, created_at)
            VALUES (?, ?, ?, ?, ?, ?, NULL, ?, 'support', ?)""",
            (
                evidence_id,
                risk_id,
                dataset_id,
                line_start,
                line_end,
                result["period_key"],
                quote,
                now,
            ),
        )
        snapshot = {
            "id": risk_id,
            "risk_number": risk_number,
            "risk_type": "财务规则异常",
            "risk_level": "待评估",
            "status": "待复核",
            "summary": result["summary"],
            "trigger_rule_id": result["rule_id"],
            "trigger_rule_version": result["rule_version"],
            "input_values": result["input_values"],
            "baseline_values": result["baseline_values"],
            "calculation_result": result["calculation_result"],
            "model_explanation": None,
            "uncertainty": uncertainty,
            "human_opinion": "",
            "model_provider": None,
            "actual_model": None,
            "model_call_id": None,
            "version": 1,
            "evidence": [
                {
                    "id": evidence_id,
                    "kind": "financial",
                    "dataset_id": dataset_id,
                    "document_name": filename,
                    "line_start": line_start,
                    "line_end": line_end,
                    "period_key": result["period_key"],
                    "quote": quote,
                    "direction": "support",
                }
            ],
        }
        RiskRepository._insert_version(
            db,
            risk_id=risk_id,
            version=1,
            snapshot=snapshot,
            change_reason="确定性财务规则生成待评估草稿",
            created_at=now,
        )
        db.execute(
            "INSERT INTO audit_events VALUES (?, NULL, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                "risk.rule_draft_created",
                now,
                _json(
                    {
                        "risk_id": risk_id,
                        "risk_number": risk_number,
                        "dataset_id": dataset_id,
                        "rule_result_id": result["id"],
                    }
                ),
            ),
        )

    def list_datasets(self, project_id: str) -> list[dict[str, Any]]:
        root = self.database.project_root(project_id)
        with self.database.connect(root / "app.db") as db:
            rows = db.execute(
                """SELECT d.*, r.id rule_run_id, r.rule_set_version, r.status rule_run_status,
                r.passed_count, r.failed_count, r.unavailable_count, r.completed_at
                , COALESCE((SELECT p.warnings_json FROM financial_import_previews p
                    WHERE p.sha256=d.sha256 ORDER BY p.created_at DESC LIMIT 1), '[]')
                    import_warnings_json
                FROM financial_datasets d
                LEFT JOIN financial_rule_runs r ON r.dataset_id=d.id
                ORDER BY d.created_at DESC"""
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["import_warnings"] = json.loads(item.pop("import_warnings_json"))
            result.append(item)
        return result

    def get_dataset(self, project_id: str, dataset_id: str) -> dict[str, Any]:
        datasets = self.list_datasets(project_id)
        dataset = next((item for item in datasets if item["id"] == dataset_id), None)
        if dataset is None:
            raise KeyError(dataset_id)
        root = self.database.project_root(project_id)
        with self.analysis(root) as analysis:
            rows = analysis.execute(
                """SELECT id, rule_id, rule_version, period_key, status, summary,
                input_values_json, baseline_values_json, calculation_result_json,
                scope_json, affected_count, line_start, line_end, created_at
                FROM financial_rule_results WHERE dataset_id=?
                ORDER BY CASE status WHEN 'fail' THEN 0 WHEN 'unavailable' THEN 1 ELSE 2 END,
                         period_key, rule_id""",
                [dataset_id],
            ).fetchall()
        dataset["rule_results"] = [
            {
                "id": row[0],
                "rule_id": row[1],
                "rule_version": row[2],
                "period_key": row[3],
                "status": row[4],
                "summary": row[5],
                "input_values": json.loads(row[6]),
                "baseline_values": json.loads(row[7]),
                "calculation_result": json.loads(row[8]),
                "scope": json.loads(row[9]),
                "affected_count": row[10],
                "line_start": row[11],
                "line_end": row[12],
                "created_at": row[13],
            }
            for row in rows
        ]
        return dataset

    def result_rows(
        self,
        project_id: str,
        dataset_id: str,
        result_id: str,
        *,
        offset: int,
        limit: int,
    ) -> dict[str, Any]:
        root = self.database.project_root(project_id)
        with self.analysis(root) as analysis:
            result = analysis.execute(
                """SELECT scope_json, affected_count FROM financial_rule_results
                WHERE id=? AND dataset_id=?""",
                [result_id, dataset_id],
            ).fetchone()
            if result is None:
                raise KeyError(result_id)
            scope = json.loads(result[0])
            if scope.get("kind") == "period":
                where = "r.dataset_id=? AND r.period_key=?"
                params: list[Any] = [dataset_id, scope["period_key"]]
                reason_select = "'汇总计算范围'"
            else:
                where = "r.dataset_id=? AND rr.result_id=?"
                params = [dataset_id, result_id]
                reason_select = "rr.reason"
            query = f"""SELECT r.line_number, r.year, r.period, r.account_code,
                r.account_name, r.opening_debit, r.opening_credit, r.period_debit,
                r.period_credit, r.closing_debit, r.closing_credit, r.currency,
                {reason_select} reason
                FROM trial_balance_rows r
                {'JOIN financial_rule_result_rows rr ON rr.dataset_id=r.dataset_id AND rr.line_number=r.line_number' if scope.get('kind') != 'period' else ''}
                WHERE {where} ORDER BY r.line_number LIMIT ? OFFSET ?"""
            rows = analysis.execute(query, [*params, limit, offset]).fetchall()
            if scope.get("kind") == "period":
                total = analysis.execute(
                    "SELECT COUNT(*) FROM trial_balance_rows WHERE dataset_id=? AND period_key=?",
                    params,
                ).fetchone()[0]
            else:
                total = analysis.execute(
                    "SELECT COUNT(*) FROM financial_rule_result_rows WHERE dataset_id=? AND result_id=?",
                    [dataset_id, result_id],
                ).fetchone()[0]
        return {
            "total": total,
            "offset": offset,
            "limit": limit,
            "rows": [
                {
                    "line_number": row[0],
                    "year": row[1],
                    "period": row[2],
                    "account_code": row[3],
                    "account_name": row[4],
                    "opening_debit": _money(row[5]),
                    "opening_credit": _money(row[6]),
                    "period_debit": _money(row[7]),
                    "period_credit": _money(row[8]),
                    "closing_debit": _money(row[9]),
                    "closing_credit": _money(row[10]),
                    "currency": row[11],
                    "reason": row[12],
                }
                for row in rows
            ],
        }

    def archive_dataset(self, project_id: str, dataset_id: str) -> dict[str, Any]:
        root = self.database.project_root(project_id)
        now = utc_now()
        with self.database.connect(root / "app.db") as db:
            changed = db.execute(
                """UPDATE financial_datasets SET status='archived', archived_at=?
                WHERE id=? AND status='active'""",
                (now, dataset_id),
            ).rowcount
        if not changed:
            raise KeyError(dataset_id)
        self.database.record_project_event(
            root, "financial.dataset_archived", details={"dataset_id": dataset_id}
        )
        return self.get_dataset(project_id, dataset_id)

    def existing_rule_run(self, project_id: str, dataset_id: str) -> dict[str, Any]:
        root = self.database.project_root(project_id)
        with self.database.connect(root / "app.db") as db:
            row = db.execute(
                """SELECT * FROM financial_rule_runs
                WHERE dataset_id=? AND rule_set_version=?""",
                (dataset_id, RULE_SET_VERSION),
            ).fetchone()
        if row is None:
            raise KeyError(dataset_id)
        return dict(row)
