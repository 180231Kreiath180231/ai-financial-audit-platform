from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import psutil


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


def stop_tree(process: subprocess.Popen[bytes]) -> None:
    processes = process_tree(process)
    for child in reversed(processes):
        try:
            child.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(processes, timeout=5)
    for child in alive:
        try:
            child.kill()
        except psutil.Error:
            pass


def measure(duration: int) -> dict[str, object]:
    repo_root = Path(__file__).resolve().parents[1]
    backend_port = free_port()
    frontend_port = free_port()
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if npm is None:
        raise RuntimeError("找不到 npm")

    with tempfile.TemporaryDirectory(prefix="hengjian-baseline-") as data_dir:
        environment = os.environ.copy()
        environment.update(
            {
                "AUDIT_DATA_DIR": data_dir,
                "AUDIT_PORT": str(backend_port),
                "AUDIT_FRONTEND_ORIGIN": f"http://127.0.0.1:{frontend_port}",
                "AUDIT_SEED_SYNTHETIC": "1",
                "AUDIT_LOG_LEVEL": "WARNING",
            }
        )
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        backend = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "backend.app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(backend_port),
            ],
            cwd=repo_root,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        frontend = subprocess.Popen(
            [npm, "--prefix", "frontend", "run", "dev", "--", "--port", str(frontend_port)],
            cwd=repo_root,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        try:
            wait_ready(f"http://127.0.0.1:{backend_port}/health")
            wait_ready(f"http://127.0.0.1:{frontend_port}")
            roots = [backend, frontend]
            tracked: dict[int, psutil.Process] = {}

            def current_processes() -> list[psutil.Process]:
                visible = [process for root in roots for process in process_tree(root)]
                for process in visible:
                    if process.pid not in tracked:
                        tracked[process.pid] = process
                        try:
                            process.cpu_percent(None)
                        except psutil.Error:
                            pass
                return [tracked[process.pid] for process in visible]

            for process in current_processes():
                try:
                    process.cpu_percent(None)
                except psutil.Error:
                    pass

            cpu_samples: list[float] = []
            memory_samples: list[int] = []
            system_memory_samples: list[float] = []
            logical_cpus = psutil.cpu_count(logical=True) or 1
            for _ in range(duration):
                time.sleep(1)
                cpu = 0.0
                memory = 0
                for process in current_processes():
                    try:
                        cpu += process.cpu_percent(None)
                        memory += process.memory_info().rss
                    except psutil.Error:
                        pass
                cpu_samples.append(cpu / logical_cpus)
                memory_samples.append(memory)
                system_memory_samples.append(psutil.virtual_memory().percent)

            return {
                "measured_at": datetime.now(UTC).isoformat(),
                "duration_seconds": duration,
                "logical_cpu_count": logical_cpus,
                "application_cpu_average_percent": round(sum(cpu_samples) / len(cpu_samples), 2),
                "application_cpu_peak_percent": round(max(cpu_samples), 2),
                "application_memory_peak_mb": round(max(memory_samples) / 1024**2, 1),
                "system_memory_peak_percent": round(max(system_memory_samples), 1),
            }
        finally:
            stop_tree(frontend)
            stop_tree(backend)


def main() -> None:
    parser = argparse.ArgumentParser(description="测量空闲工作台的本地资源基线")
    parser.add_argument("--duration", type=int, default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.duration < 3:
        parser.error("--duration 至少为 3 秒")
    result = measure(args.duration)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
