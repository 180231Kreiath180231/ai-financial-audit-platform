import math
import sqlite3

import pytest

from backend.app.migrations import PROJECT_MIGRATIONS, apply_migrations
from backend.app.retrieval import replace_page_chunks
from backend.app.synthetic_vectors import (
    SYNTHETIC_ACTUAL_MODEL,
    SYNTHETIC_DIMENSION,
    SyntheticVectorError,
    build_synthetic_vector_index,
    require_synthetic_project,
    search_synthetic_hybrid,
    synthetic_embedding,
)


def project_db() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:", isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    apply_migrations(db, "project", PROJECT_MIGRATIONS)
    for document_id, filename, page_id, text in (
        ("doc-income", "收入报告.pdf", "page-income", "营业收入异常需要复核合同与回款证据。"),
        ("doc-asset", "资产报告.pdf", "page-asset", "固定资产折旧年限需要复核。"),
    ):
        db.execute(
            """INSERT INTO documents
            (id, filename, sha256, size_bytes, page_count, parse_method, parse_version,
             stored_path, created_at)
            VALUES (?, ?, ?, 12, 1, 'native_pdf', 'v1', ?, 'now')""",
            (document_id, filename, document_id.encode().hex().ljust(64, "0")[:64], filename),
        )
        db.execute(
            """INSERT INTO pages
            (id, document_id, page_number, block_number, original_text, parse_method, parse_version)
            VALUES (?, ?, 1, 1, ?, 'native_pdf', 'v1')""",
            (page_id, document_id, text),
        )
        replace_page_chunks(
            db,
            page_id=page_id,
            document_id=document_id,
            page_number=1,
            block_number=1,
            original_text=text,
            parse_method="native_pdf",
            parse_version="v1",
        )
    return db


def test_synthetic_embedding_is_deterministic_normalized_and_local() -> None:
    first = synthetic_embedding("营业收入审计")
    second = synthetic_embedding("营业收入审计")

    assert first == second
    assert len(first) == SYNTHETIC_DIMENSION
    assert math.isclose(sum(value * value for value in first), 1.0, rel_tol=1e-6)


def test_synthetic_vector_path_rejects_real_projects() -> None:
    with pytest.raises(SyntheticVectorError) as error:
        require_synthetic_project(False)

    assert error.value.code == "SYNTHETIC_INDEX_ONLY"


def test_build_synthetic_index_versions_vectors_and_records_no_external_request() -> None:
    db = project_db()
    try:
        status = build_synthetic_vector_index(db)
        index = db.execute("SELECT * FROM vector_index_versions").fetchone()
        embedding_count = db.execute("SELECT COUNT(*) FROM chunk_embeddings").fetchone()[0]
        event = db.execute(
            "SELECT details_json FROM audit_events WHERE event_type='retrieval.synthetic_index_built'"
        ).fetchone()
    finally:
        db.close()

    assert status["vector_state"] == "ready"
    assert status["vector_backend"] == "memory_cosine"
    assert status["actual_model"] == SYNTHETIC_ACTUAL_MODEL
    assert status["dimension"] == SYNTHETIC_DIMENSION
    assert index["indexed_chunk_count"] == embedding_count == 2
    assert '"external_request": false' in event["details_json"]


def test_hybrid_search_returns_traceable_chunks_and_applies_filters() -> None:
    db = project_db()
    try:
        build_synthetic_vector_index(db)
        hits = search_synthetic_hybrid(db, "收入风险", limit=10)
        filtered = search_synthetic_hybrid(db, "复核", document_id="doc-asset", limit=10)
    finally:
        db.close()

    assert hits[0]["document_id"] == "doc-income"
    assert hits[0]["chunk_id"]
    assert hits[0]["snippet"] == "营业收入异常需要复核合同与回款证据。"
    assert hits[0]["match_kind"] == "semantic"
    assert {hit["document_id"] for hit in filtered} == {"doc-asset"}


def test_hybrid_search_rejects_stale_index_after_page_chunks_change() -> None:
    db = project_db()
    try:
        build_synthetic_vector_index(db)
        replace_page_chunks(
            db,
            page_id="page-income",
            document_id="doc-income",
            page_number=1,
            block_number=1,
            original_text="营业收入原文已更新。",
            parse_method="native_pdf",
            parse_version="v2",
        )
        with pytest.raises(SyntheticVectorError, match="过期") as error:
            search_synthetic_hybrid(db, "营业收入")
    finally:
        db.close()

    assert error.value.code == "SYNTHETIC_INDEX_STALE"
