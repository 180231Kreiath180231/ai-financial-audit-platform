"""Exercise strict-offline gateway blocking and inspect PktMon PCAPNG captures."""

from __future__ import annotations

import argparse
import json
import struct
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from backend.app.db import Database
from backend.app.gateway import GatewayError, ModelGateway
from backend.app.schemas import ModelProfileCreate, ModelProviderCreate, ProjectCreate

PACKET_BLOCK_TYPES = {0x00000002, 0x00000003, 0x00000006}
SECTION_HEADER_BLOCK = 0x0A0D0D0A
BYTE_ORDER_MAGIC = 0x1A2B3C4D
SYNTHETIC_CANARY_KEY = "synthetic-pktmon-canary-not-a-real-key"


class OfflineAcceptanceError(RuntimeError):
    """Raised when an offline acceptance artifact is invalid."""


def exercise_gateway(
    attempts: int,
    target_base_url: str,
    *,
    arm_network_canary: bool = False,
) -> dict[str, Any]:
    if attempts < 1:
        raise ValueError("attempts must be positive")
    started_at = datetime.now(UTC).isoformat()
    with tempfile.TemporaryDirectory(prefix="hengjian-offline-gateway-") as temporary:
        root = Path(temporary)
        database = Database(root / "data")
        project = database.create_project(
            ProjectCreate(
                name="合成严格离线抓包验收",
                entity_name="合成严格离线主体",
                year_start=2024,
                year_end=2025,
                storage_path=str(root / "project"),
                model_profile="外部连接负向验证",
            ),
            is_synthetic=True,
        )
        provider = database.create_model_provider(
            ModelProviderCreate(
                display_name="保留地址外部模型负向验证",
                base_url=target_base_url,
                api_key=(
                    SecretStr(SYNTHETIC_CANARY_KEY)
                    if arm_network_canary
                    else None
                ),
                timeout_seconds=1,
                max_retries=0,
            )
        )
        database.create_model_profile(
            ModelProfileCreate(
                provider_id=provider["id"],
                display_name="严格离线文本能力",
                model_name="offline-negative-control-v1",
                capabilities={"text", "json_schema"},
            )
        )
        database.set_project_external_access(project["id"], True)
        database.set_strict_offline(True)

        gateway = ModelGateway(database)
        error_codes: list[str] = []
        prompt_markers: list[str] = []
        for index in range(attempts):
            marker = f"synthetic-offline-attempt-{index + 1}"
            prompt_markers.append(marker)
            try:
                gateway.complete_external(project["id"], "text", marker)
            except GatewayError as error:
                error_codes.append(error.code)
            else:
                error_codes.append("NOT_BLOCKED")

        with database.connect(database.registry_path) as connection:
            rows = connection.execute(
                """SELECT status, error_code, provider_id, model_profile_id, request_summary
                FROM model_calls ORDER BY started_at"""
            ).fetchall()
        registry_bytes = database.registry_path.read_bytes()
        calls_are_blocked = len(rows) == attempts and all(
            row["status"] == "blocked"
            and row["error_code"] == "OFFLINE_MODE_BLOCKED"
            and row["provider_id"] is None
            and row["model_profile_id"] is None
            and len(row["request_summary"]) == 64
            for row in rows
        )
        prompts_absent = all(marker.encode("utf-8") not in registry_bytes for marker in prompt_markers)
        credential_absent = SYNTHETIC_CANARY_KEY.encode("utf-8") not in registry_bytes
        passed = (
            error_codes == ["OFFLINE_MODE_BLOCKED"] * attempts
            and calls_are_blocked
            and prompts_absent
            and credential_absent
            and database.strict_offline()
        )
        return {
            "scenario": "strict-offline-external-text-negative-control-v1",
            "started_at": started_at,
            "completed_at": datetime.now(UTC).isoformat(),
            "target_base_url": target_base_url,
            "network_canary_armed": arm_network_canary,
            "attempts": attempts,
            "blocked_attempts": error_codes.count("OFFLINE_MODE_BLOCKED"),
            "error_codes": error_codes,
            "model_call_rows": len(rows),
            "all_calls_blocked_before_route_selection": calls_are_blocked,
            "prompt_plaintext_absent": prompts_absent,
            "credential_plaintext_absent": credential_absent,
            "strict_offline": database.strict_offline(),
            "passed": passed,
        }


def count_pcapng_packets(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    if len(data) < 12:
        raise OfflineAcceptanceError(f"PCAPNG is too short: {path}")

    offset = 0
    endian: str | None = None
    packet_blocks = 0
    total_blocks = 0
    while offset < len(data):
        if len(data) - offset < 12:
            raise OfflineAcceptanceError(f"Truncated PCAPNG block at offset {offset}")
        raw_type = data[offset : offset + 4]
        if raw_type == struct.pack("<I", SECTION_HEADER_BLOCK):
            raw_magic = data[offset + 8 : offset + 12]
            if raw_magic == struct.pack("<I", BYTE_ORDER_MAGIC):
                endian = "<"
            elif raw_magic == struct.pack(">I", BYTE_ORDER_MAGIC):
                endian = ">"
            else:
                raise OfflineAcceptanceError("Invalid PCAPNG byte-order magic")
        if endian is None:
            raise OfflineAcceptanceError("PCAPNG does not start with a section header")

        block_type = struct.unpack_from(f"{endian}I", data, offset)[0]
        block_length = struct.unpack_from(f"{endian}I", data, offset + 4)[0]
        if block_length < 12 or block_length % 4 != 0 or offset + block_length > len(data):
            raise OfflineAcceptanceError(f"Invalid PCAPNG block length at offset {offset}")
        trailing_length = struct.unpack_from(
            f"{endian}I", data, offset + block_length - 4
        )[0]
        if trailing_length != block_length:
            raise OfflineAcceptanceError(f"PCAPNG block length mismatch at offset {offset}")
        total_blocks += 1
        if block_type in PACKET_BLOCK_TYPES:
            packet_blocks += 1
        offset += block_length

    return {
        "path": str(path.resolve()),
        "bytes": len(data),
        "blocks": total_blocks,
        "packet_blocks": packet_blocks,
    }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    exercise = commands.add_parser("exercise")
    exercise.add_argument("--attempts", type=int, default=10)
    exercise.add_argument("--target-base-url", default="https://192.0.2.1:9/v1")
    exercise.add_argument("--arm-network-canary", action="store_true")
    exercise.add_argument("--output", type=Path, required=True)
    count = commands.add_parser("count-pcap")
    count.add_argument("--input", type=Path, required=True)
    count.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    arguments = _build_parser().parse_args()
    try:
        if arguments.command == "exercise":
            result = exercise_gateway(
                arguments.attempts,
                arguments.target_base_url,
                arm_network_canary=arguments.arm_network_canary,
            )
        else:
            result = count_pcapng_packets(arguments.input)
    except (OSError, OfflineAcceptanceError, ValueError) as error:
        print(f"error: {error}")
        return 1
    _write_json(arguments.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("passed", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
