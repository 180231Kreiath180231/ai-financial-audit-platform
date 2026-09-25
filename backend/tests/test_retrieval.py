import hashlib
import sqlite3

import pytest

from backend.app.migrations import PROJECT_MIGRATIONS, apply_migrations
from backend.app.retrieval import (
    CHUNK_VERSION,
    reciprocal_rank_fusion,
    replace_page_chunks,
    retrieval_status,
    split_text_chunks,
)


def project_db() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    apply_migrations(connection, "project", PROJECT_MIGRATIONS)
    connection.execute(
        """INSERT INTO documents
        (id, filename, sha256, size_bytes, page_count, parse_method, parse_version,
         stored_path, created_at)
        VALUES ('doc-1', '合成资料.pdf', ?, 12, 1, 'native_pdf', 'v1', 'x.pdf', 'now')""",
        ("a" * 64,),
    )
    return connection


def test_split_text_chunks_preserves_exact_offsets_and_is_deterministic() -> None:
    source = "甲" * 620 + "。" + "乙" * 620 + "。" + "丙" * 120

    first = split_text_chunks(source)
    second = split_text_chunks(source)

    assert first == second
    assert len(first) == 2
    assert all(text == source[start:end] for start, end, text in first)
    assert first[1][0] < first[0][1]


@pytest.mark.parametrize(
    ("target", "overlap"),
    [(31, 0), (100, -1), (100, 100)],
)
def test_split_text_chunks_rejects_invalid_windows(target: int, overlap: int) -> None:
    with pytest.raises(ValueError):
        split_text_chunks("合成文本", target_chars=target, overlap_chars=overlap)


def test_reciprocal_rank_fusion_deduplicates_and_keeps_source_ranks() -> None:
    fused = reciprocal_rank_fusion(["a", "b", "b", "c"], ["b", "d", "a"])

    assert [item["id"] for item in fused] == ["b", "a", "d", "c"]
    assert fused[0]["keyword_rank"] == 2
    assert fused[0]["vector_rank"] == 1
    assert fused[2]["keyword_rank"] is None


def test_page_chunks_are_traceable_and_mark_ready_vector_index_stale() -> None:
    db = project_db()
    source = "可复核的合成审计证据。" * 100
    try:
        db.execute(
            """INSERT INTO pages
            (id, document_id, page_number, block_number, original_text, parse_method, parse_version)
            VALUES ('page-1', 'doc-1', 1, 1, ?, 'native_pdf', 'v1')""",
            (source,),
        )
        count = replace_page_chunks(
            db,
            page_id="page-1",
            document_id="doc-1",
            page_number=1,
            block_number=1,
            original_text=source,
            parse_method="native_pdf",
            parse_version="v1",
        )
        rows = db.execute("SELECT * FROM retrieval_chunks ORDER BY chunk_number").fetchall()
        status = retrieval_status(db)
        db.execute(
            """INSERT INTO vector_index_versions
            (id, model_profile_id, actual_model, dimension, chunk_version, backend,
             status, indexed_chunk_count, created_at)
            VALUES ('index-1', 'profile-1', 'embedding-test', 3, ?, 'memory_cosine',
                    'ready', ?, 'now')""",
            (CHUNK_VERSION, count),
        )

        replace_page_chunks(
            db,
            page_id="page-1",
            document_id="doc-1",
            page_number=1,
            block_number=1,
            original_text=source + "新增文本。",
            parse_method="native_pdf",
            parse_version="v2",
        )
        vector_state = db.execute(
            "SELECT status FROM vector_index_versions WHERE id='index-1'"
        ).fetchone()[0]
    finally:
        db.close()

    assert count == len(rows) == 2
    assert status["chunk_state"] == "ready"
    assert status["external_request"] is False
    assert all(row["text"] == source[row["char_start"] : row["char_end"]] for row in rows)
    assert all(
        row["text_sha256"] == hashlib.sha256(row["text"].encode("utf-8")).hexdigest()
        for row in rows
    )
    assert vector_state == "stale"


def test_chunk_embedding_dimension_must_match_its_index_version() -> None:
    db = project_db()
    try:
        db.execute(
            """INSERT INTO pages
            (id, document_id, page_number, block_number, original_text, parse_method, parse_version)
            VALUES ('page-1', 'doc-1', 1, 1, '合成证据', 'native_pdf', 'v1')"""
        )
        replace_page_chunks(
            db,
            page_id="page-1",
            document_id="doc-1",
            page_number=1,
            block_number=1,
            original_text="合成证据",
            parse_method="native_pdf",
            parse_version="v1",
        )
        chunk_id = db.execute("SELECT id FROM retrieval_chunks").fetchone()[0]
        db.execute(
            """INSERT INTO vector_index_versions
            (id, model_profile_id, actual_model, dimension, chunk_version, backend,
             status, indexed_chunk_count, created_at)
            VALUES ('index-1', 'profile-1', 'embedding-test', 3, ?, 'memory_cosine',
                    'building', 0, 'now')""",
            (CHUNK_VERSION,),
        )

        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                """INSERT INTO chunk_embeddings
                (chunk_id, index_version_id, dimension, vector_blob)
                VALUES (?, 'index-1', 4, ?)""",
                (chunk_id, b"not-a-real-vector"),
            )
    finally:
        db.close()
