from __future__ import annotations

import hashlib
import sqlite3
import uuid
from collections.abc import Sequence
from typing import Any

CHUNK_VERSION = "char-window-v1"
CHUNK_TARGET_CHARS = 1000
CHUNK_OVERLAP_CHARS = 150
RRF_K = 60

_BREAK_CHARACTERS = "\n。！？；.!?;"


def split_text_chunks(
    text: str,
    *,
    target_chars: int = CHUNK_TARGET_CHARS,
    overlap_chars: int = CHUNK_OVERLAP_CHARS,
) -> list[tuple[int, int, str]]:
    """Split exact source substrings using deterministic character offsets."""
    if target_chars < 32:
        raise ValueError("分块长度不能小于 32 个字符")
    if overlap_chars < 0 or overlap_chars >= target_chars:
        raise ValueError("分块重叠必须大于等于 0 且小于分块长度")
    if not text.strip():
        return []

    chunks: list[tuple[int, int, str]] = []
    start = 0
    text_length = len(text)
    while start < text_length:
        end = min(text_length, start + target_chars)
        if end < text_length:
            minimum_break = start + max(1, int(target_chars * 0.6))
            break_at = max(text.rfind(character, minimum_break, end) for character in _BREAK_CHARACTERS)
            if break_at >= minimum_break:
                end = break_at + 1
        chunk = text[start:end]
        if chunk.strip():
            chunks.append((start, end, chunk))
        if end >= text_length:
            break
        start = max(start + 1, end - overlap_chars)
    return chunks


def replace_page_chunks(
    db: sqlite3.Connection,
    *,
    page_id: str,
    document_id: str,
    page_number: int,
    block_number: int,
    original_text: str,
    parse_method: str,
    parse_version: str,
) -> int:
    db.execute("DELETE FROM retrieval_chunks WHERE page_id=?", (page_id,))
    chunks = split_text_chunks(original_text)
    for chunk_number, (char_start, char_end, text) in enumerate(chunks, start=1):
        chunk_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"hengjian:{CHUNK_VERSION}:{page_id}:{chunk_number}:{char_start}:{char_end}",
            )
        )
        db.execute(
            """INSERT INTO retrieval_chunks
            (id, document_id, page_id, page_number, block_number, chunk_number,
             char_start, char_end, text, text_sha256, parse_method, parse_version,
             chunk_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                chunk_id,
                document_id,
                page_id,
                page_number,
                block_number,
                chunk_number,
                char_start,
                char_end,
                text,
                hashlib.sha256(text.encode("utf-8")).hexdigest(),
                parse_method,
                parse_version,
                CHUNK_VERSION,
            ),
        )
    db.execute(
        "UPDATE vector_index_versions SET status='stale' WHERE status='ready'"
    )
    return len(chunks)


def rebuild_retrieval_chunks(db: sqlite3.Connection) -> int:
    db.execute("DELETE FROM retrieval_chunks")
    total = 0
    rows = db.execute(
        """SELECT id, document_id, page_number, block_number, original_text,
        parse_method, parse_version FROM pages ORDER BY document_id, page_number, block_number"""
    ).fetchall()
    for row in rows:
        (
            page_id,
            document_id,
            page_number,
            block_number,
            original_text,
            parse_method,
            parse_version,
        ) = row
        total += replace_page_chunks(
            db,
            page_id=page_id,
            document_id=document_id,
            page_number=page_number,
            block_number=block_number,
            original_text=original_text,
            parse_method=parse_method,
            parse_version=parse_version,
        )
    return total


def reciprocal_rank_fusion(
    keyword_ids: Sequence[str],
    vector_ids: Sequence[str],
    *,
    limit: int = 30,
    k: int = RRF_K,
) -> list[dict[str, Any]]:
    """Fuse two ranked ID lists without mixing incomparable raw scores."""
    if limit < 1 or limit > 50:
        raise ValueError("融合结果数量必须在 1 到 50 之间")
    if k < 1:
        raise ValueError("RRF k 必须大于 0")
    scores: dict[str, float] = {}
    ranks: dict[str, dict[str, int | None]] = {}
    for source, identifiers in (("keyword", keyword_ids), ("vector", vector_ids)):
        for rank, identifier in enumerate(dict.fromkeys(identifiers), start=1):
            scores[identifier] = scores.get(identifier, 0.0) + 1 / (k + rank)
            ranks.setdefault(identifier, {"keyword_rank": None, "vector_rank": None})[
                f"{source}_rank"
            ] = rank
    ordered = sorted(scores, key=lambda identifier: (-scores[identifier], identifier))
    return [
        {
            "id": identifier,
            "score": scores[identifier],
            **ranks[identifier],
        }
        for identifier in ordered[:limit]
    ]


def retrieval_status(db: sqlite3.Connection) -> dict[str, Any]:
    source_page_count = db.execute(
        "SELECT COUNT(*) count FROM pages WHERE trim(original_text)<>''"
    ).fetchone()["count"]
    chunk_row = db.execute(
        """SELECT COUNT(*) chunk_count, COUNT(DISTINCT page_id) chunked_page_count
        FROM retrieval_chunks WHERE chunk_version=?""",
        (CHUNK_VERSION,),
    ).fetchone()
    chunk_count = chunk_row["chunk_count"]
    chunked_page_count = chunk_row["chunked_page_count"]
    if source_page_count == 0:
        chunk_state = "empty"
    elif chunked_page_count == source_page_count:
        chunk_state = "ready"
    else:
        chunk_state = "stale"

    index = db.execute(
        "SELECT * FROM vector_index_versions ORDER BY created_at DESC, id DESC LIMIT 1"
    ).fetchone()
    vector_state = "not_configured" if index is None else index["status"]
    if index is not None and vector_state == "ready" and index["indexed_chunk_count"] != chunk_count:
        vector_state = "stale"

    if chunk_state == "empty":
        message = "项目暂无可分块原文；全文与语义检索均不会外发。"
    elif chunk_state == "stale":
        message = "本地分块与页面原文不一致；需重建后再生成向量索引。"
    elif vector_state == "not_configured":
        message = "全文检索与本地分块可用；语义检索尚未配置，不会发送数据。"
    elif index is not None and index["actual_model"] == "synthetic-hash-embedding-v1":
        message = "全文检索与合成测试向量索引可用；未调用外部服务。"
    else:
        message = "全文检索与本地分块可用；语义索引状态已记录。"

    if vector_state == "not_configured":
        action = "确认 Embedding 服务商与数据外发政策后再构建向量索引。"
    elif vector_state == "stale":
        action = "使用原模型与维度重建向量索引，或新建独立索引版本。"
    elif vector_state == "failed":
        action = "检查索引失败原因后重试，不要混用不同维度的向量。"
    elif index is not None and index["actual_model"] == "synthetic-hash-embedding-v1":
        action = "仅用于合成项目验证检索链路，不代表真实 Embedding 质量。"
    else:
        action = "无需操作。"

    return {
        "chunk_version": CHUNK_VERSION,
        "chunk_state": chunk_state,
        "chunk_count": chunk_count,
        "chunked_page_count": chunked_page_count,
        "source_page_count": source_page_count,
        "keyword_state": "ready" if source_page_count else "empty",
        "vector_state": vector_state,
        "vector_backend": None if index is None else index["backend"],
        "model_profile_id": None if index is None else index["model_profile_id"],
        "actual_model": None if index is None else index["actual_model"],
        "dimension": None if index is None else index["dimension"],
        "indexed_chunk_count": 0 if index is None else index["indexed_chunk_count"],
        "external_request": False,
        "message": message,
        "action": action,
    }
