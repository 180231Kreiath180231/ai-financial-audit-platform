from __future__ import annotations

import struct
from pathlib import Path

import pytest

from scripts.measure_strict_offline_gateway import (
    BYTE_ORDER_MAGIC,
    SECTION_HEADER_BLOCK,
    OfflineAcceptanceError,
    count_pcapng_packets,
    exercise_gateway,
)


def _pcapng_block(block_type: int, body: bytes) -> bytes:
    padding = b"\0" * ((4 - len(body) % 4) % 4)
    length = 12 + len(body) + len(padding)
    return struct.pack("<II", block_type, length) + body + padding + struct.pack("<I", length)


def test_strict_offline_exercise_blocks_before_route_selection() -> None:
    result = exercise_gateway(3, "https://192.0.2.1:9/v1")

    assert result["passed"] is True
    assert result["blocked_attempts"] == 3
    assert result["model_call_rows"] == 3
    assert result["all_calls_blocked_before_route_selection"] is True
    assert result["prompt_plaintext_absent"] is True
    assert result["credential_plaintext_absent"] is True


def test_pcapng_counter_counts_packet_blocks(tmp_path: Path) -> None:
    section = _pcapng_block(
        SECTION_HEADER_BLOCK,
        struct.pack("<IHHq", BYTE_ORDER_MAGIC, 1, 0, -1),
    )
    interface = _pcapng_block(1, struct.pack("<HHI", 1, 0, 65535))
    enhanced_packet = _pcapng_block(6, struct.pack("<IIIII", 0, 0, 0, 0, 0))
    capture = tmp_path / "capture.pcapng"
    capture.write_bytes(section + interface + enhanced_packet)

    result = count_pcapng_packets(capture)

    assert result["blocks"] == 3
    assert result["packet_blocks"] == 1


def test_pcapng_counter_rejects_truncated_block(tmp_path: Path) -> None:
    capture = tmp_path / "broken.pcapng"
    capture.write_bytes(struct.pack("<III", SECTION_HEADER_BLOCK, 28, BYTE_ORDER_MAGIC))

    with pytest.raises(OfflineAcceptanceError, match="Invalid PCAPNG block length"):
        count_pcapng_packets(capture)
