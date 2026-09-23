from __future__ import annotations

import sqlite3
from typing import Any

MAX_SEARCH_LENGTH = 200
MAX_SEARCH_RESULTS = 50


def _exact_snippet(text: str, term: str, *, width: int = 320) -> str:
    """Return an exact source substring so it can be promoted to evidence safely."""
    folded_text = text.casefold()
    position = folded_text.find(term.casefold())
    if position < 0:
        return text[:width].strip()
    start = max(0, position - 110)
    end = min(len(text), max(position + len(term) + 110, start + width))
    return text[start:end].strip()


def _fts_phrase(term: str) -> str:
    return f'"{term.replace(chr(34), chr(34) * 2)}"'


def search_project_pages(
    db: sqlite3.Connection,
    query: str,
    *,
    document_id: str | None = None,
    page_number: int | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    term = query.strip()
    if not term:
        return []
    if len(term) > MAX_SEARCH_LENGTH:
        raise ValueError(f"搜索内容不能超过 {MAX_SEARCH_LENGTH} 个字符")
    limit = max(1, min(limit, MAX_SEARCH_RESULTS))

    filters: list[str] = []
    parameters: list[Any] = []
    if document_id is not None:
        filters.append("p.document_id=?")
        parameters.append(document_id)
    if page_number is not None:
        filters.append("p.page_number=?")
        parameters.append(page_number)
    filter_sql = f" AND {' AND '.join(filters)}" if filters else ""

    if len(term) >= 3:
        rows = db.execute(
            f"""SELECT p.document_id, d.filename document_name, p.page_number,
                p.block_number, p.original_text, p.parse_method, p.parse_version,
                bm25(pages_fts) search_rank
            FROM pages_fts
            JOIN pages p ON p.rowid=pages_fts.rowid
            JOIN documents d ON d.id=p.document_id
            WHERE pages_fts MATCH ?{filter_sql}
            ORDER BY search_rank, p.page_number, p.block_number
            LIMIT ?""",
            (_fts_phrase(term), *parameters, limit),
        ).fetchall()
    else:
        rows = db.execute(
            f"""SELECT p.document_id, d.filename document_name, p.page_number,
                p.block_number, p.original_text, p.parse_method, p.parse_version,
                0 search_rank
            FROM pages p JOIN documents d ON d.id=p.document_id
            WHERE instr(lower(p.original_text), lower(?)) > 0{filter_sql}
            ORDER BY p.page_number, p.block_number
            LIMIT ?""",
            (term, *parameters, limit),
        ).fetchall()

    results: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int]] = set()
    for row in rows:
        source = row["original_text"]
        snippet = _exact_snippet(source, term)
        if not snippet:
            continue
        key = (row["document_id"], row["page_number"], row["block_number"])
        seen.add(key)
        results.append(
            {
                "document_id": row["document_id"],
                "document_name": row["document_name"],
                "page_number": row["page_number"],
                "block_number": row["block_number"],
                "parse_method": row["parse_method"],
                "parse_version": row["parse_version"],
                "snippet": snippet,
                "match_kind": "content",
            }
        )

    remaining = limit - len(results)
    if remaining <= 0:
        return results

    filename_filters = ["instr(lower(d.filename), lower(?)) > 0"]
    filename_parameters: list[Any] = [term]
    if document_id is not None:
        filename_filters.append("d.id=?")
        filename_parameters.append(document_id)
    if page_number is not None:
        filename_filters.append("p.page_number=?")
        filename_parameters.append(page_number)
    filename_rows = db.execute(
        f"""SELECT p.document_id, d.filename document_name, p.page_number,
            p.block_number, p.original_text, p.parse_method, p.parse_version
        FROM documents d JOIN pages p ON p.document_id=d.id
        WHERE {' AND '.join(filename_filters)}
          AND p.rowid=(
              SELECT p2.rowid FROM pages p2
              WHERE p2.document_id=d.id
              {"AND p2.page_number=?" if page_number is not None else ""}
              ORDER BY p2.page_number, p2.block_number LIMIT 1
          )
        ORDER BY d.filename COLLATE NOCASE
        LIMIT ?""",
        (
            *filename_parameters,
            *((page_number,) if page_number is not None else ()),
            remaining,
        ),
    ).fetchall()
    for row in filename_rows:
        key = (row["document_id"], row["page_number"], row["block_number"])
        if key in seen:
            continue
        snippet = row["original_text"][:320].strip()
        if not snippet:
            continue
        results.append(
            {
                "document_id": row["document_id"],
                "document_name": row["document_name"],
                "page_number": row["page_number"],
                "block_number": row["block_number"],
                "parse_method": row["parse_method"],
                "parse_version": row["parse_version"],
                "snippet": snippet,
                "match_kind": "filename",
            }
        )
    return results
