from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import struct
import uuid
from datetime import UTC, datetime
from typing import Any

from .retrieval import CHUNK_VERSION, reciprocal_rank_fusion, retrieval_status

SYNTHETIC_MODEL_PROFILE_ID = "synthetic-hash-embedding-v1"
SYNTHETIC_ACTUAL_MODEL = "synthetic-hash-embedding-v1"
SYNTHETIC_DIMENSION = 64
SYNTHETIC_MAX_CHUNKS = 10_000
VECTOR_CANDIDATE_LIMIT = 50


class SyntheticVectorError(RuntimeError):
    def __init__(self, code: str, message: str, action: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.action = action


def require_synthetic_project(is_synthetic: bool) -> None:
    if not is_synthetic:
        raise SyntheticVectorError(
            "SYNTHETIC_INDEX_ONLY",
            "合成向量与混合检索只允许用于合成项目",
            "真实项目保持全文检索，等待 Embedding 服务商与数据政策确认。",
        )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _feature_tokens(text: str) -> list[str]:
    normalized = text.casefold()
    latin_tokens = re.findall(r"[a-z0-9]+", normalized)
    cjk = "".join(re.findall(r"[\u3400-\u9fff]", normalized))
    cjk_tokens = list(cjk)
    cjk_tokens.extend(cjk[index : index + 2] for index in range(max(0, len(cjk) - 1)))
    return latin_tokens + cjk_tokens


def synthetic_embedding(text: str, *, dimension: int = SYNTHETIC_DIMENSION) -> list[float]:
    """Create deterministic feature-hash vectors for synthetic tests, not model output."""
    if dimension < 8:
        raise ValueError("合成向量维度不能小于 8")
    vector = [0.0] * dimension
    for token in _feature_tokens(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "little") % dimension
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[bucket] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm:
        vector = [value / norm for value in vector]
    return vector


def encode_vector(vector: list[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def decode_vector(blob: bytes, dimension: int) -> tuple[float, ...]:
    expected_size = dimension * 4
    if len(blob) != expected_size:
        raise SyntheticVectorError(
            "VECTOR_BLOB_INVALID",
            "向量数据长度与索引维度不一致",
            "重建合成向量索引后重试。",
        )
    return struct.unpack(f"<{dimension}f", blob)


def build_synthetic_vector_index(db: sqlite3.Connection) -> dict[str, Any]:
    status = retrieval_status(db)
    if status["chunk_state"] != "ready" or status["chunk_count"] == 0:
        raise SyntheticVectorError(
            "RETRIEVAL_CHUNKS_NOT_READY",
            "没有可用于合成向量索引的就绪分块",
            "先导入包含可提取原文的合成 PDF。",
        )
    if status["chunk_count"] > SYNTHETIC_MAX_CHUNKS:
        raise SyntheticVectorError(
            "SYNTHETIC_INDEX_TOO_LARGE",
            "合成向量索引仅用于小规模测试项目",
            f"将合成项目控制在 {SYNTHETIC_MAX_CHUNKS} 个分块以内。",
        )

    index_id = str(uuid.uuid4())
    created_at = _utc_now()
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute(
            """INSERT INTO vector_index_versions
            (id, model_profile_id, actual_model, dimension, chunk_version, backend,
             status, indexed_chunk_count, created_at)
            VALUES (?, ?, ?, ?, ?, 'memory_cosine', 'building', 0, ?)""",
            (
                index_id,
                SYNTHETIC_MODEL_PROFILE_ID,
                SYNTHETIC_ACTUAL_MODEL,
                SYNTHETIC_DIMENSION,
                CHUNK_VERSION,
                created_at,
            ),
        )
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise

    try:
        db.execute("BEGIN IMMEDIATE")
        chunks = db.execute(
            "SELECT id, text FROM retrieval_chunks WHERE chunk_version=? ORDER BY id",
            (CHUNK_VERSION,),
        ).fetchall()
        for chunk in chunks:
            db.execute(
                """INSERT INTO chunk_embeddings
                (chunk_id, index_version_id, dimension, vector_blob)
                VALUES (?, ?, ?, ?)""",
                (
                    chunk["id"],
                    index_id,
                    SYNTHETIC_DIMENSION,
                    encode_vector(synthetic_embedding(chunk["text"])),
                ),
            )
        completed_at = _utc_now()
        db.execute(
            """UPDATE vector_index_versions
            SET status='ready', indexed_chunk_count=?, completed_at=? WHERE id=?""",
            (len(chunks), completed_at, index_id),
        )
        db.execute(
            "INSERT INTO audit_events VALUES (?, NULL, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                "retrieval.synthetic_index_built",
                completed_at,
                json.dumps(
                    {
                        "index_version_id": index_id,
                        "actual_model": SYNTHETIC_ACTUAL_MODEL,
                        "dimension": SYNTHETIC_DIMENSION,
                        "backend": "memory_cosine",
                        "chunk_count": len(chunks),
                        "external_request": False,
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        db.execute(
            """UPDATE vector_index_versions
            SET status='failed', error_code='SYNTHETIC_INDEX_BUILD_FAILED', completed_at=?
            WHERE id=?""",
            (_utc_now(), index_id),
        )
        raise
    return retrieval_status(db)


def _filter_sql(
    *,
    document_id: str | None,
    page_number: int | None,
    fiscal_year: int | None,
    entity_name: str | None,
    account_name: str | None,
    document_type: str | None,
    parse_method: str | None,
) -> tuple[str, list[Any]]:
    filters: list[str] = []
    parameters: list[Any] = []
    for expression, value in (
        ("c.document_id=?", document_id),
        ("c.page_number=?", page_number),
        ("d.fiscal_year=?", fiscal_year),
        ("d.entity_name=? COLLATE NOCASE", entity_name),
        ("d.document_type=? COLLATE NOCASE", document_type),
        ("d.parse_method=?", parse_method),
    ):
        if value is not None and value != "":
            filters.append(expression)
            parameters.append(value)
    if account_name:
        filters.append(
            "EXISTS (SELECT 1 FROM json_each(d.account_names_json) "
            "WHERE value=? COLLATE NOCASE)"
        )
        parameters.append(account_name)
    return (f" AND {' AND '.join(filters)}" if filters else "", parameters)


def _keyword_chunk_ids(
    db: sqlite3.Connection,
    term: str,
    filter_sql: str,
    parameters: list[Any],
) -> list[str]:
    if len(term) >= 3:
        phrase = f'"{term.replace(chr(34), chr(34) * 2)}"'
        rows = db.execute(
            f"""SELECT c.id, bm25(pages_fts) search_rank
            FROM pages_fts
            JOIN pages p ON p.rowid=pages_fts.rowid
            JOIN retrieval_chunks c ON c.page_id=p.id
            JOIN documents d ON d.id=c.document_id
            WHERE pages_fts MATCH ? AND instr(lower(c.text), lower(?)) > 0{filter_sql}
            ORDER BY search_rank, c.page_number, c.block_number, c.chunk_number
            LIMIT ?""",
            (phrase, term, *parameters, VECTOR_CANDIDATE_LIMIT),
        ).fetchall()
    else:
        rows = db.execute(
            f"""SELECT c.id
            FROM retrieval_chunks c JOIN documents d ON d.id=c.document_id
            WHERE instr(lower(c.text), lower(?)) > 0{filter_sql}
            ORDER BY c.page_number, c.block_number, c.chunk_number
            LIMIT ?""",
            (term, *parameters, VECTOR_CANDIDATE_LIMIT),
        ).fetchall()
    return [row["id"] for row in rows]


def _vector_chunk_ids(
    db: sqlite3.Connection,
    term: str,
    index: sqlite3.Row,
    filter_sql: str,
    parameters: list[Any],
) -> list[str]:
    query_vector = synthetic_embedding(term, dimension=index["dimension"])
    scored: list[tuple[float, str]] = []
    rows = db.execute(
        f"""SELECT c.id, e.vector_blob
        FROM chunk_embeddings e
        JOIN retrieval_chunks c ON c.id=e.chunk_id
        JOIN documents d ON d.id=c.document_id
        WHERE e.index_version_id=?{filter_sql}
        ORDER BY c.id""",
        (index["id"], *parameters),
    )
    for row in rows:
        vector = decode_vector(row["vector_blob"], index["dimension"])
        score = sum(left * right for left, right in zip(query_vector, vector, strict=True))
        if score <= 0:
            continue
        scored.append((score, row["id"]))
        if len(scored) > VECTOR_CANDIDATE_LIMIT * 2:
            scored = sorted(scored, key=lambda item: (-item[0], item[1]))[
                :VECTOR_CANDIDATE_LIMIT
            ]
    return [
        identifier
        for _, identifier in sorted(scored, key=lambda item: (-item[0], item[1]))[
            :VECTOR_CANDIDATE_LIMIT
        ]
    ]


def search_synthetic_hybrid(
    db: sqlite3.Connection,
    query: str,
    *,
    document_id: str | None = None,
    page_number: int | None = None,
    fiscal_year: int | None = None,
    entity_name: str | None = None,
    account_name: str | None = None,
    document_type: str | None = None,
    parse_method: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    term = query.strip()
    if not term:
        raise SyntheticVectorError(
            "HYBRID_QUERY_REQUIRED",
            "混合检索需要关键词",
            "输入问题或关键词后重试，或切换回全文检索。",
        )
    index = db.execute(
        """SELECT * FROM vector_index_versions
        WHERE actual_model=? AND chunk_version=?
        ORDER BY created_at DESC, id DESC LIMIT 1""",
        (SYNTHETIC_ACTUAL_MODEL, CHUNK_VERSION),
    ).fetchone()
    if index is None:
        raise SyntheticVectorError(
            "SYNTHETIC_INDEX_NOT_READY",
            "合成向量索引尚未就绪",
            "先构建合成测试索引，或切换回全文检索。",
        )
    if index["status"] == "stale":
        raise SyntheticVectorError(
            "SYNTHETIC_INDEX_STALE",
            "合成向量索引已过期",
            "重建合成测试索引后重试。",
        )
    if index["status"] != "ready":
        raise SyntheticVectorError(
            "SYNTHETIC_INDEX_NOT_READY",
            "合成向量索引尚未就绪",
            "等待索引完成或重新构建。",
        )
    current_chunk_count = db.execute(
        "SELECT COUNT(*) FROM retrieval_chunks WHERE chunk_version=?", (CHUNK_VERSION,)
    ).fetchone()[0]
    if index["indexed_chunk_count"] != current_chunk_count:
        raise SyntheticVectorError(
            "SYNTHETIC_INDEX_STALE",
            "合成向量索引已过期",
            "重建合成测试索引后重试。",
        )

    filter_sql, parameters = _filter_sql(
        document_id=document_id,
        page_number=page_number,
        fiscal_year=fiscal_year,
        entity_name=entity_name,
        account_name=account_name,
        document_type=document_type,
        parse_method=parse_method,
    )
    keyword_ids = _keyword_chunk_ids(db, term, filter_sql, parameters)
    vector_ids = _vector_chunk_ids(db, term, index, filter_sql, parameters)
    fused = reciprocal_rank_fusion(keyword_ids, vector_ids, limit=max(1, min(limit, 30)))
    if not fused:
        return []

    placeholders = ",".join("?" for _ in fused)
    rows = db.execute(
        f"""SELECT c.*, d.filename document_name, d.fiscal_year, d.entity_name,
        d.document_type, d.account_names_json
        FROM retrieval_chunks c JOIN documents d ON d.id=c.document_id
        WHERE c.id IN ({placeholders})""",
        tuple(item["id"] for item in fused),
    ).fetchall()
    by_id = {row["id"]: row for row in rows}
    results: list[dict[str, Any]] = []
    for item in fused:
        row = by_id[item["id"]]
        results.append(
            {
                "chunk_id": row["id"],
                "document_id": row["document_id"],
                "document_name": row["document_name"],
                "page_number": row["page_number"],
                "block_number": row["block_number"],
                "parse_method": row["parse_method"],
                "parse_version": row["parse_version"],
                "snippet": row["text"][:320].strip(),
                "match_kind": "content" if item["keyword_rank"] is not None else "semantic",
                "fiscal_year": row["fiscal_year"],
                "entity_name": row["entity_name"],
                "document_type": row["document_type"],
                "account_names": json.loads(row["account_names_json"] or "[]"),
            }
        )
    return results
