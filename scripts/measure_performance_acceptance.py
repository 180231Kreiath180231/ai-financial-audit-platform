from __future__ import annotations

import argparse
import http.cookiejar
import json
import math
import os
import platform
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median
from typing import Any

import psutil
from reportlab.pdfgen import canvas

from backend.app.db import Database, utc_now
from backend.app.risks import RiskRepository
from backend.app.schemas import ProjectCreate, RiskCreate, RiskEvidenceCreate
from backend.app.worker import MEMORY_WAIT_STEP, LocalTaskWorker

MIN_ACTIVE_SECONDS = 30
P06_P95_SECONDS = 2.0
P06_MAX_SECONDS = 5.0


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_ready(url: str, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.25)
    raise TimeoutError(f"服务未在 {timeout:.0f} 秒内就绪：{url}")


def process_tree(process: subprocess.Popen[bytes]) -> list[psutil.Process]:
    try:
        root = psutil.Process(process.pid)
        return [root, *root.children(recursive=True)]
    except psutil.Error:
        return []


def stop_tree(process: subprocess.Popen[bytes], *, force: bool = False) -> None:
    processes = process_tree(process)
    for child in reversed(processes):
        try:
            child.kill() if force else child.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(processes, timeout=5)
    for child in alive:
        try:
            child.kill()
        except psutil.Error:
            pass


def start_backend(repo_root: Path, data_dir: Path, port: int) -> subprocess.Popen[bytes]:
    environment = os.environ.copy()
    environment.update(
        {
            "AUDIT_DATA_DIR": str(data_dir),
            "AUDIT_PORT": str(port),
            "AUDIT_FRONTEND_ORIGIN": "http://127.0.0.1:5173",
            "AUDIT_SEED_SYNTHETIC": "0",
            "AUDIT_LOG_LEVEL": "WARNING",
        }
    )
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=repo_root,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
    )
    wait_ready(f"http://127.0.0.1:{port}/health")
    return process


def host_info() -> dict[str, Any]:
    memory = psutil.virtual_memory()
    disk = shutil.disk_usage(Path.cwd())
    return {
        "captured_at": datetime.now(UTC).isoformat(),
        "platform": platform.platform(),
        "processor": platform.processor(),
        "physical_cpu_count": psutil.cpu_count(logical=False),
        "logical_cpu_count": psutil.cpu_count(logical=True),
        "memory_total_gb": round(memory.total / 1024**3, 2),
        "memory_available_gb": round(memory.available / 1024**3, 2),
        "disk_free_gb": round(disk.free / 1024**3, 2),
        "python": platform.python_version(),
    }


def write_result(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def percentile(values: list[float], percentage: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * percentage) - 1))
    return ordered[index]


def create_native_pdf(path: Path, pages: int) -> None:
    document = canvas.Canvas(str(path), pageCompression=1)
    for page_number in range(1, pages + 1):
        document.setTitle("Synthetic native PDF performance fixture")
        document.drawString(
            72,
            720,
            f"SYNTHETIC NATIVE AUDIT PAGE {page_number} revenue control evidence",
        )
        document.showPage()
    document.save()


def create_project(database: Database, root: Path) -> dict[str, Any]:
    return database.create_project(
        ProjectCreate(
            name="性能验收合成项目",
            entity_name="性能验收合成主体",
            year_start=2024,
            year_end=2025,
            storage_path=str(root),
            model_profile="严格离线 / Fake Provider",
        ),
        is_synthetic=True,
    )


def enqueue_pdf(database: Database, root: Path, filename: str, payload: bytes) -> str:
    task_id = str(uuid.uuid4())
    incoming = root / "incoming" / f"{task_id}.part"
    incoming.write_bytes(payload)
    now = utc_now()
    with database.connect(root / "app.db") as connection:
        connection.execute(
            """INSERT INTO tasks
            (id, task_type, filename, incoming_path, status, progress,
             current_step, created_at, updated_at)
            VALUES (?, 'pdf_import', ?, ?, 'queued', 0, '等待单工作器', ?, ?)""",
            (task_id, filename, str(incoming), now, now),
        )
    database.record_project_event(root, "task.queued", task_id=task_id)
    return task_id


def prepare_fixture(
    base: Path,
    *,
    documents: int,
    pages: int,
    seed_foreground_data: bool = False,
) -> tuple[Database, dict[str, Any], Path, list[str], str | None, str | None]:
    data_dir = base / "data"
    root = base / "project"
    database = Database(data_dir)
    project = create_project(database, root)
    template = base / "native-template.pdf"
    create_native_pdf(template, pages)
    template_bytes = template.read_bytes()

    foreground_document_id: str | None = None
    risk_id: str | None = None
    if seed_foreground_data:
        small_pdf = base / "foreground.pdf"
        create_native_pdf(small_pdf, 3)
        seed_task = enqueue_pdf(
            database,
            root,
            "foreground.pdf",
            small_pdf.read_bytes() + b"\n% foreground fixture\n",
        )
        worker = LocalTaskWorker(database, resource_sampler=lambda: (0.0, 0.0))
        claimed = worker._claim_next()
        if claimed is None or claimed[2] != seed_task:
            raise RuntimeError("前台夹具任务未能领取")
        worker._process(*claimed)
        with database.connect(root / "app.db") as connection:
            foreground = connection.execute(
                "SELECT id FROM documents ORDER BY created_at LIMIT 1"
            ).fetchone()
            page = connection.execute(
                """SELECT original_text FROM pages
                WHERE document_id=? AND page_number=1 AND block_number=1""",
                (foreground["id"],),
            ).fetchone()
        foreground_document_id = foreground["id"]
        risk = RiskRepository(database).create(
            project["id"],
            RiskCreate(
                risk_type="性能验收合成线索",
                summary="Synthetic risk used only for foreground latency measurement",
                evidence=[
                    RiskEvidenceCreate(
                        document_id=foreground_document_id,
                        page_number=1,
                        block_number=1,
                        quote=page["original_text"],
                        direction="support",
                    )
                ],
            ),
        )
        risk_id = risk["id"]

    task_ids = [
        enqueue_pdf(
            database,
            root,
            f"native-load-{index + 1:03d}.pdf",
            template_bytes + f"\n% unique-load-{index + 1:03d}\n".encode(),
        )
        for index in range(documents)
    ]
    return database, project, root, task_ids, foreground_document_id, risk_id


def task_rows(database: Database, root: Path, task_ids: list[str]) -> list[sqlite3.Row]:
    placeholders = ",".join("?" for _ in task_ids)
    with database.connect(root / "app.db") as connection:
        return connection.execute(
            f"SELECT * FROM tasks WHERE id IN ({placeholders}) ORDER BY created_at",
            task_ids,
        ).fetchall()


def task_counts(rows: list[sqlite3.Row]) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        result[row["status"]] = result.get(row["status"], 0) + 1
    return result


def event_count(database: Database, root: Path, event_type: str) -> int:
    with database.connect(root / "app.db") as connection:
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM audit_events WHERE event_type=?", (event_type,)
            ).fetchone()[0]
        )


def prime_cpu(process: subprocess.Popen[bytes]) -> dict[int, psutil.Process]:
    tracked: dict[int, psutil.Process] = {}
    for item in process_tree(process):
        tracked[item.pid] = item
        try:
            item.cpu_percent(None)
        except psutil.Error:
            pass
    psutil.cpu_percent(interval=None)
    return tracked


def sample_process(process: subprocess.Popen[bytes], tracked: dict[int, psutil.Process]) -> dict[str, float]:
    visible = process_tree(process)
    for item in visible:
        if item.pid not in tracked:
            tracked[item.pid] = item
            try:
                item.cpu_percent(None)
            except psutil.Error:
                pass
    cpu = 0.0
    memory = 0
    for item in visible:
        try:
            cpu += tracked[item.pid].cpu_percent(None)
            memory += tracked[item.pid].memory_info().rss
        except psutil.Error:
            pass
    logical_cpus = psutil.cpu_count(logical=True) or 1
    return {
        "application_cpu_percent": round(cpu / logical_cpus, 2),
        "application_memory_mb": round(memory / 1024**2, 1),
        "system_cpu_percent": round(psutil.cpu_percent(interval=None), 1),
        "system_memory_percent": round(psutil.virtual_memory().percent, 1),
    }


def session_opener(base_url: str) -> urllib.request.OpenerDirector:
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    request = urllib.request.Request(f"{base_url}/api/v1/session", method="POST")
    with opener.open(request, timeout=5) as response:
        if response.status != 204:
            raise RuntimeError(f"本机会话创建失败：{response.status}")
    return opener


def timed_request(opener: urllib.request.OpenerDirector, url: str) -> tuple[float, int]:
    started = time.perf_counter()
    with opener.open(url, timeout=10) as response:
        response.read()
        status = response.status
    return time.perf_counter() - started, status


def latency_summary(values: list[float], errors: int) -> dict[str, Any]:
    return {
        "sample_count": len(values),
        "error_count": errors,
        "median_ms": round(median(values) * 1000, 1) if values else None,
        "p95_ms": round(percentile(values, 0.95) * 1000, 1) if values else None,
        "max_ms": round(max(values) * 1000, 1) if values else None,
    }


def measure_native_load(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="hengjian-native-load-") as temp:
        base = Path(temp)
        database, project, root, task_ids, document_id, _ = prepare_fixture(
            base,
            documents=args.documents,
            pages=args.pages,
            seed_foreground_data=True,
        )
        port = free_port()
        backend = start_backend(repo_root, base / "data", port)
        tracked = prime_cpu(backend)
        opener = session_opener(f"http://127.0.0.1:{port}")
        endpoint_values: dict[str, list[float]] = {"pdf": [], "risks": [], "search": []}
        endpoint_errors = {key: 0 for key in endpoint_values}
        samples: list[dict[str, Any]] = []
        started = time.monotonic()
        try:
            while time.monotonic() - started < args.timeout:
                loop_started = time.monotonic()
                rows = task_rows(database, root, task_ids)
                counts = task_counts(rows)
                active = counts.get("running", 0) + counts.get("queued", 0) > 0
                if active:
                    endpoints = {
                        "pdf": f"http://127.0.0.1:{port}/api/v1/projects/{project['id']}/documents/{document_id}/file",
                        "risks": f"http://127.0.0.1:{port}/api/v1/projects/{project['id']}/risks",
                        "search": f"http://127.0.0.1:{port}/api/v1/projects/{project['id']}/search?q=SYNTHETIC",
                    }
                    for name, url in endpoints.items():
                        try:
                            elapsed, status = timed_request(opener, url)
                            if status != 200:
                                endpoint_errors[name] += 1
                            else:
                                endpoint_values[name].append(elapsed)
                        except OSError:
                            endpoint_errors[name] += 1
                process_sample = sample_process(backend, tracked)
                samples.append(
                    {
                        "elapsed_seconds": round(time.monotonic() - started, 2),
                        **process_sample,
                        "task_counts": counts,
                    }
                )
                if counts.get("completed", 0) == len(task_ids):
                    break
                remaining = 1.0 - (time.monotonic() - loop_started)
                if remaining > 0:
                    time.sleep(remaining)
        finally:
            stop_tree(backend)

        active_samples = [
            sample
            for sample in samples
            if sample["task_counts"].get("running", 0)
            or sample["task_counts"].get("queued", 0)
        ]
        cpu_values = [sample["application_cpu_percent"] for sample in active_samples]
        memory_values = [sample["application_memory_mb"] for sample in active_samples]
        final_counts = task_counts(task_rows(database, root, task_ids))
        latency = {
            name: latency_summary(values, endpoint_errors[name])
            for name, values in endpoint_values.items()
        }
        p02_passed = (
            len(active_samples) >= args.min_active_seconds
            and final_counts.get("completed", 0) == len(task_ids)
            and bool(cpu_values)
            and mean(cpu_values) <= 35.0
            and max(cpu_values) <= 45.0
        )
        p06_passed = all(
            item["sample_count"] >= min(15, args.min_active_seconds)
            and item["error_count"] == 0
            and item["p95_ms"] <= P06_P95_SECONDS * 1000
            and item["max_ms"] <= P06_MAX_SECONDS * 1000
            for item in latency.values()
        )
        return {
            "measured_at": datetime.now(UTC).isoformat(),
            "host": host_info(),
            "fixture": {
                "synthetic": True,
                "external_requests": 0,
                "documents": args.documents,
                "pages_per_document": args.pages,
            },
            "method": {
                "sampling_interval_seconds": 1,
                "cpu_normalization": "sum of backend process-tree CPU divided by logical CPU count",
                "p02_min_active_seconds": args.min_active_seconds,
                "p06_operational_thresholds": {
                    "p95_seconds": P06_P95_SECONDS,
                    "max_seconds": P06_MAX_SECONDS,
                    "errors": 0,
                },
            },
            "p02": {
                "passed": p02_passed,
                "active_sample_count": len(active_samples),
                "duration_seconds": round(samples[-1]["elapsed_seconds"], 2) if samples else 0,
                "application_cpu_average_percent": round(mean(cpu_values), 2)
                if cpu_values
                else None,
                "application_cpu_peak_percent": round(max(cpu_values), 2)
                if cpu_values
                else None,
                "application_memory_peak_mb": round(max(memory_values), 1)
                if memory_values
                else None,
                "final_task_counts": final_counts,
            },
            "p06": {"passed": p06_passed, "latency": latency},
            "samples": samples,
        }


def run_cpu_burn(duration: int) -> None:
    deadline = time.monotonic() + duration
    value = 1
    while time.monotonic() < deadline:
        value = (value * 1664525 + 1013904223) & 0xFFFFFFFF
    if value == -1:
        print(value)


def start_cpu_burners(duration: int) -> list[subprocess.Popen[bytes]]:
    logical = psutil.cpu_count(logical=True) or 1
    count = max(1, math.ceil(logical * 0.75))
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    # Process creation can take tens of seconds on Windows under endpoint scanning.
    # Give every burner time to start, then begin together so the 1-second samples
    # cover the complete sustained-pressure window.
    start_at = time.time() + 30
    burn_code = (
        "import sys,time; start=float(sys.argv[1]); duration=int(sys.argv[2]); "
        "time.sleep(max(0,start-time.time())); deadline=time.monotonic()+duration; value=1; "
        "exec('while time.monotonic() < deadline:\\n "
        " value=(value*1664525+1013904223)&0xFFFFFFFF')"
    )
    return [
        subprocess.Popen(
            [sys.executable, "-c", burn_code, str(start_at), str(duration)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        for _ in range(count)
    ]


def stop_processes(processes: list[subprocess.Popen[bytes]]) -> None:
    for process in processes:
        if process.poll() is None:
            process.terminate()
    for process in processes:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def measure_cpu_guard(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="hengjian-cpu-guard-") as temp:
        base = Path(temp)
        database, _, root, task_ids, _, _ = prepare_fixture(
            base, documents=args.documents, pages=args.pages
        )
        port = free_port()
        backend = start_backend(repo_root, base / "data", port)
        tracked = prime_cpu(backend)
        samples: list[dict[str, Any]] = []
        burners: list[subprocess.Popen[bytes]] = []
        started = time.monotonic()
        high_started: float | None = None
        pause_seen_at: float | None = None
        low_started: float | None = None
        resume_seen_at: float | None = None
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if task_counts(task_rows(database, root, task_ids)).get("running", 0):
                    break
                time.sleep(0.2)
            burners = start_cpu_burners(args.burn_duration)
            while time.monotonic() - started < args.timeout:
                loop_started = time.monotonic()
                rows = task_rows(database, root, task_ids)
                counts = task_counts(rows)
                process_sample = sample_process(backend, tracked)
                elapsed = time.monotonic() - started
                pause_events = event_count(database, root, "task.resource_pause_requested")
                resume_events = event_count(database, root, "task.resource_resumed")
                system_cpu = process_sample["system_cpu_percent"]
                if system_cpu > 50 and high_started is None:
                    high_started = elapsed
                elif system_cpu <= 50 and pause_seen_at is None:
                    high_started = None
                if pause_events and pause_seen_at is None:
                    pause_seen_at = elapsed
                    stop_processes(burners)
                    burners = []
                if pause_seen_at is not None:
                    if system_cpu < 30 and low_started is None:
                        low_started = elapsed
                    elif system_cpu >= 30 and resume_seen_at is None:
                        low_started = None
                if resume_events and resume_seen_at is None:
                    resume_seen_at = elapsed
                samples.append(
                    {
                        "elapsed_seconds": round(elapsed, 2),
                        **process_sample,
                        "task_counts": counts,
                        "pause_event_count": pause_events,
                        "resume_event_count": resume_events,
                    }
                )
                if resume_seen_at is not None and counts.get("completed", 0) == len(task_ids):
                    break
                remaining = 1.0 - (time.monotonic() - loop_started)
                if remaining > 0:
                    time.sleep(remaining)
        finally:
            stop_processes(burners)
            stop_tree(backend)

        pause_delay = pause_seen_at - high_started if pause_seen_at and high_started else None
        resume_delay = resume_seen_at - low_started if resume_seen_at and low_started else None
        final_counts = task_counts(task_rows(database, root, task_ids))
        passed = (
            pause_delay is not None
            and 9 <= pause_delay <= 15
            and resume_delay is not None
            and 9 <= resume_delay <= 15
            and final_counts.get("completed", 0) == len(task_ids)
        )
        return {
            "measured_at": datetime.now(UTC).isoformat(),
            "host": host_info(),
            "fixture": {
                "synthetic": True,
                "external_requests": 0,
                "documents": args.documents,
                "pages_per_document": args.pages,
                "cpu_burner_processes": max(1, math.ceil((psutil.cpu_count() or 1) * 0.75)),
            },
            "p03": {
                "passed": passed,
                "pause_delay_seconds": round(pause_delay, 2) if pause_delay is not None else None,
                "resume_delay_seconds": round(resume_delay, 2) if resume_delay is not None else None,
                "pause_event_count": event_count(database, root, "task.resource_pause_requested"),
                "resume_event_count": event_count(database, root, "task.resource_resumed"),
                "final_task_counts": final_counts,
            },
            "samples": samples,
        }


def run_memory_hold(target_percent: float, max_gb: float, duration: int) -> None:
    memory = psutil.virtual_memory()
    reserve = 6 * 1024**3
    safe_limit = max(0, memory.available - reserve)
    requested_limit = int(max_gb * 1024**3)
    allocation_limit = min(safe_limit, requested_limit)
    blocks: list[bytearray] = []
    allocated = 0
    block_size = 64 * 1024**2
    while psutil.virtual_memory().percent < target_percent and allocated + block_size <= allocation_limit:
        block = bytearray(block_size)
        for offset in range(0, len(block), 4096):
            block[offset] = 1
        blocks.append(block)
        allocated += len(block)
        time.sleep(0.1)
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        time.sleep(1)


def measure_memory_guard(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="hengjian-memory-guard-") as temp:
        base = Path(temp)
        database, _, root, task_ids, _, _ = prepare_fixture(
            base, documents=1, pages=args.pages
        )
        task_id = task_ids[0]
        with database.connect(root / "app.db") as connection:
            connection.execute("DELETE FROM audit_events WHERE task_id=?", (task_id,))
            connection.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        source = base / "native-template.pdf"
        payload = source.read_bytes() + b"\n% memory-gate\n"

        port = free_port()
        backend = start_backend(repo_root, base / "data", port)
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        holder = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "_memory-hold",
                "--target-percent",
                str(args.target_percent),
                "--max-gb",
                str(args.max_gb),
                "--duration",
                str(args.hold_duration),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        samples: list[dict[str, Any]] = []
        started = time.monotonic()
        queued_at: float | None = None
        blocked_seen_at: float | None = None
        recovered_seen_at: float | None = None
        released = False
        try:
            high_samples = 0
            while time.monotonic() - started < args.timeout:
                loop_started = time.monotonic()
                elapsed = time.monotonic() - started
                memory_percent = round(psutil.virtual_memory().percent, 1)
                high_samples = high_samples + 1 if memory_percent > 70 else 0
                if high_samples >= 2 and queued_at is None:
                    task_id = enqueue_pdf(database, root, "memory-gate.pdf", payload)
                    queued_at = elapsed
                rows = task_rows(database, root, [task_id]) if queued_at is not None else []
                row = rows[0] if rows else None
                if row and row["status"] == "queued" and row["current_step"] == MEMORY_WAIT_STEP:
                    blocked_seen_at = blocked_seen_at or elapsed
                    if not released:
                        holder.terminate()
                        holder.wait(timeout=5)
                        released = True
                if released and event_count(database, root, "resource.memory_recovered"):
                    recovered_seen_at = recovered_seen_at or elapsed
                samples.append(
                    {
                        "elapsed_seconds": round(elapsed, 2),
                        "system_memory_percent": memory_percent,
                        "task_status": row["status"] if row else None,
                        "current_step": row["current_step"] if row else None,
                        "memory_block_event_count": event_count(
                            database, root, "resource.memory_blocked"
                        ),
                        "memory_resume_event_count": event_count(
                            database, root, "resource.memory_recovered"
                        ),
                    }
                )
                if row and row["status"] == "completed" and recovered_seen_at is not None:
                    break
                remaining = 1.0 - (time.monotonic() - loop_started)
                if remaining > 0:
                    time.sleep(remaining)
        finally:
            if holder.poll() is None:
                holder.terminate()
                try:
                    holder.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    holder.kill()
            stop_tree(backend)

        rows = task_rows(database, root, [task_id]) if queued_at is not None else []
        final_status = rows[0]["status"] if rows else None
        blocked_events = event_count(database, root, "resource.memory_blocked")
        recovered_events = event_count(database, root, "resource.memory_recovered")
        passed = (
            queued_at is not None
            and blocked_seen_at is not None
            and recovered_seen_at is not None
            and blocked_events >= 1
            and recovered_events >= 1
            and final_status == "completed"
        )
        return {
            "measured_at": datetime.now(UTC).isoformat(),
            "host": host_info(),
            "fixture": {
                "synthetic": True,
                "external_requests": 0,
                "pages": args.pages,
                "target_memory_percent": args.target_percent,
                "allocation_cap_gb": args.max_gb,
                "minimum_free_memory_reserve_gb": 6,
            },
            "p04": {
                "passed": passed,
                "queued_at_seconds": round(queued_at, 2) if queued_at is not None else None,
                "blocked_seen_at_seconds": round(blocked_seen_at, 2)
                if blocked_seen_at is not None
                else None,
                "recovered_seen_at_seconds": round(recovered_seen_at, 2)
                if recovered_seen_at is not None
                else None,
                "memory_block_event_count": blocked_events,
                "memory_resume_event_count": recovered_events,
                "final_task_status": final_status,
            },
            "samples": samples,
        }


def measure_restart_recovery(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="hengjian-restart-") as temp:
        base = Path(temp)
        database, _, root, task_ids, _, _ = prepare_fixture(
            base, documents=args.documents, pages=args.pages
        )
        first_port = free_port()
        first = start_backend(repo_root, base / "data", first_port)
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            rows = task_rows(database, root, task_ids)
            counts = task_counts(rows)
            if counts.get("completed", 0) >= 2 and counts.get("running", 0) >= 1:
                break
            time.sleep(0.2)
        stop_tree(first, force=True)

        after_kill = task_rows(database, root, task_ids)
        completed_before = {
            row["id"]: row["document_id"]
            for row in after_kill
            if row["status"] == "completed"
        }
        interrupted_ids = [
            row["id"] for row in after_kill if row["status"] in {"running", "pausing"}
        ]
        with database.connect(root / "app.db") as connection:
            document_count_before = int(connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0])

        second_port = free_port()
        second = start_backend(repo_root, base / "data", second_port)
        try:
            deadline = time.monotonic() + args.timeout
            while time.monotonic() < deadline:
                rows = task_rows(database, root, task_ids)
                if task_counts(rows).get("completed", 0) == len(task_ids):
                    break
                time.sleep(0.5)
        finally:
            stop_tree(second)

        final_rows = task_rows(database, root, task_ids)
        final_counts = task_counts(final_rows)
        final_documents = {row["id"]: row["document_id"] for row in final_rows}
        immutable_completed = all(
            final_documents.get(task_id) == document_id
            for task_id, document_id in completed_before.items()
        )
        with database.connect(root / "app.db") as connection:
            document_count_after = int(connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
            duplicate_completion_events = int(
                connection.execute(
                    """SELECT COUNT(*) FROM (
                    SELECT task_id FROM audit_events WHERE event_type='task.completed'
                    GROUP BY task_id HAVING COUNT(*) > 1)"""
                ).fetchone()[0]
            )
        passed = (
            len(completed_before) >= 2
            and bool(interrupted_ids)
            and final_counts.get("completed", 0) == len(task_ids)
            and immutable_completed
            and duplicate_completion_events == 0
            and document_count_after == args.documents
        )
        return {
            "measured_at": datetime.now(UTC).isoformat(),
            "host": host_info(),
            "fixture": {
                "synthetic": True,
                "external_requests": 0,
                "documents": args.documents,
                "pages_per_document": args.pages,
                "termination": "forced process-tree kill",
            },
            "p05": {
                "passed": passed,
                "completed_before_exit": len(completed_before),
                "interrupted_task_ids": interrupted_ids,
                "final_task_counts": final_counts,
                "completed_task_document_ids_unchanged": immutable_completed,
                "duplicate_completion_event_groups": duplicate_completion_events,
                "document_count_before_restart": document_count_before,
                "document_count_after_recovery": document_count_after,
                "scope_note": "验证批量任务级恢复；外部 OCR 页级检查点仍由离线自动化覆盖。",
            },
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="P02 至 P06 Windows 实机性能验收")
    subparsers = parser.add_subparsers(dest="command", required=True)

    native = subparsers.add_parser("native-load", help="测量 P02 与 P06")
    native.add_argument("--documents", type=int, default=14)
    native.add_argument("--pages", type=int, default=1000)
    native.add_argument("--min-active-seconds", type=int, default=MIN_ACTIVE_SECONDS)
    native.add_argument("--timeout", type=int, default=240)
    native.add_argument("--output", type=Path, required=True)

    cpu = subparsers.add_parser("cpu-guard", help="测量 P03")
    cpu.add_argument("--documents", type=int, default=8)
    cpu.add_argument("--pages", type=int, default=1000)
    cpu.add_argument("--burn-duration", type=int, default=45)
    cpu.add_argument("--timeout", type=int, default=180)
    cpu.add_argument("--output", type=Path, required=True)

    memory = subparsers.add_parser("memory-guard", help="测量 P04")
    memory.add_argument("--pages", type=int, default=1000)
    memory.add_argument("--target-percent", type=float, default=72.0)
    memory.add_argument("--max-gb", type=float, default=4.0)
    memory.add_argument("--hold-duration", type=int, default=60)
    memory.add_argument("--timeout", type=int, default=120)
    memory.add_argument("--output", type=Path, required=True)

    restart = subparsers.add_parser("restart-recovery", help="测量 P05")
    restart.add_argument("--documents", type=int, default=8)
    restart.add_argument("--pages", type=int, default=1000)
    restart.add_argument("--timeout", type=int, default=180)
    restart.add_argument("--output", type=Path, required=True)

    burn = subparsers.add_parser("_cpu-burn")
    burn.add_argument("--duration", type=int, required=True)

    hold = subparsers.add_parser("_memory-hold")
    hold.add_argument("--target-percent", type=float, required=True)
    hold.add_argument("--max-gb", type=float, required=True)
    hold.add_argument("--duration", type=int, required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "_cpu-burn":
        run_cpu_burn(args.duration)
        return
    if args.command == "_memory-hold":
        run_memory_hold(args.target_percent, args.max_gb, args.duration)
        return
    if args.command == "native-load":
        result = measure_native_load(args)
    elif args.command == "cpu-guard":
        result = measure_cpu_guard(args)
    elif args.command == "memory-guard":
        result = measure_memory_guard(args)
    else:
        result = measure_restart_recovery(args)
    write_result(args.output, result)


if __name__ == "__main__":
    main()
