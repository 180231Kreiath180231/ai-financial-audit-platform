from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    data_dir: Path
    frontend_origin: str
    seed_synthetic: bool


def load_settings() -> Settings:
    repo_root = Path(__file__).resolve().parents[2]
    data_dir = Path(os.getenv("AUDIT_DATA_DIR", repo_root / "data" / "runtime")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
        host="127.0.0.1",
        port=int(os.getenv("AUDIT_PORT", "8000")),
        data_dir=data_dir,
        frontend_origin=os.getenv("AUDIT_FRONTEND_ORIGIN", "http://127.0.0.1:5173"),
        seed_synthetic=os.getenv("AUDIT_SEED_SYNTHETIC", "1") == "1",
    )
