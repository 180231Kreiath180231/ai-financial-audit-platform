from __future__ import annotations

import json
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
    fiscal_year: int | None = None,
    entity_name: str | None = None,
    account_name: str | None = None,
    document_type: str | None = None,
    parse_method: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    term = query.strip()
    structured_filters = any(
        value is not None and value != ""
        for value in (
            document_id,
            page_number,
            fiscal_year,
            entity_name,
            account_name,
            document_type,
            parse_method,
        )
    )
    if not term and not structured_filters:
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
    if fiscal_year is not None:
        filters.append("d.fiscal_year=?")
        parameters.append(fiscal_year)
    if entity_name:
        filters.append("d.entity_name=? COLLATE NOCASE")
        parameters.append(entity_name)
    if account_name:
        filters.append(
            "EXISTS (SELECT 1 FROM json_each(d.account_names_json) WHERE value=? COLLATE NOCASE)"
        )
        parameters.append(account_name)
    if document_type:
        filters.append("d.document_type=? COLLATE NOCASE")
        parameters.append(document_type)
    if parse_method:
        filters.append("d.parse_method=?")
        parameters.append(parse_method)
    filter_sql = f" AND {' AND '.join(filters)}" if filters else ""

    select_columns = """p.document_id, d.filename document_name, p.page_number,
                p.block_number, p.original_text, p.parse_method, p.parse_version,
                d.fiscal_year, d.entity_name, d.document_type, d.account_names_json"""

    if not term:
        rows = db.execute(
            f"""SELECT {select_columns}, 0 search_rank
            FROM pages p JOIN documents d ON d.id=p.document_id
            WHERE 1=1{filter_sql}
              AND p.rowid=(SELECT p2.rowid FROM pages p2
                           WHERE p2.document_id=d.id
                           {"AND p2.page_number=?" if page_number is not None else ""}
                           ORDER BY p2.page_number, p2.block_number LIMIT 1)
            ORDER BY d.filename COLLATE NOCASE, p.page_number
            LIMIT ?""",
            (
                *parameters,
                *((page_number,) if page_number is not None else ()),
                limit,
            ),
        ).fetchall()
    elif len(term) >= 3:
        rows = db.execute(
            f"""SELECT {select_columns},
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
            f"""SELECT {select_columns},
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
        snippet = _exact_snippet(source, term) if term else source[:320].strip()
        if not snippet and term:
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
                "match_kind": "content" if term else "metadata",
                "fiscal_year": row["fiscal_year"],
                "entity_name": row["entity_name"],
                "document_type": row["document_type"],
                "account_names": json.loads(row["account_names_json"] or "[]"),
            }
        )

    if not term:
        return results

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
    if fiscal_year is not None:
        filename_filters.append("d.fiscal_year=?")
        filename_parameters.append(fiscal_year)
    if entity_name:
        filename_filters.append("d.entity_name=? COLLATE NOCASE")
        filename_parameters.append(entity_name)
    if account_name:
        filename_filters.append(
            "EXISTS (SELECT 1 FROM json_each(d.account_names_json) WHERE value=? COLLATE NOCASE)"
        )
        filename_parameters.append(account_name)
    if document_type:
        filename_filters.append("d.document_type=? COLLATE NOCASE")
        filename_parameters.append(document_type)
    if parse_method:
        filename_filters.append("d.parse_method=?")
        filename_parameters.append(parse_method)
    filename_rows = db.execute(
        f"""SELECT p.document_id, d.filename document_name, p.page_number,
            p.block_number, p.original_text, p.parse_method, p.parse_version,
            d.fiscal_year, d.entity_name, d.document_type, d.account_names_json
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
                "fiscal_year": row["fiscal_year"],
                "entity_name": row["entity_name"],
                "document_type": row["document_type"],
                "account_names": json.loads(row["account_names_json"] or "[]"),
            }
        )
    return results
