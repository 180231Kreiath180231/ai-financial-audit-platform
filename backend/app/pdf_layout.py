from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium

LAYOUT_SCHEMA_VERSION = "pdf-layout.v1"
TABLE_CANDIDATE_SCHEMA_VERSION = "table-candidate.v1"

_NUMBER_TOKEN = re.compile(r"^[\(\-+]?\d[\d,]*(?:\.\d+)?%?\)?$")


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _table_candidate(text: str) -> dict[str, Any]:
    tokens = [token for token in re.split(r"\s+", text.strip()) if token]
    numeric_count = sum(bool(_NUMBER_TOKEN.match(token)) for token in tokens)
    explicit_columns = "\t" in text or text.count("|") >= 2
    if not explicit_columns and not (len(tokens) >= 3 and numeric_count >= 2):
        return {}
    return {
        "schema_version": TABLE_CANDIDATE_SCHEMA_VERSION,
        "reason": "explicit_columns" if explicit_columns else "numeric_columns",
        "token_count": len(tokens),
        "numeric_token_count": numeric_count,
        "confirmed": False,
    }


def extract_pdf_layout(path: Path) -> list[dict[str, Any]]:
    """Extract conservative text-region coordinates without claiming table accuracy."""
    document = pdfium.PdfDocument(str(path))
    pages: list[dict[str, Any]] = []
    try:
        for page_index in range(len(document)):
            page = document[page_index]
            text_page = None
            try:
                width, height = page.get_size()
                text_page = page.get_textpage()
                character_count = text_page.count_chars()
                rectangle_count = (
                    text_page.count_rects(0, character_count) if character_count else 0
                )
                blocks: list[dict[str, Any]] = []
                seen: set[tuple[str, int, int, int, int]] = set()
                for rectangle_index in range(rectangle_count):
                    left, bottom, right, top = text_page.get_rect(rectangle_index)
                    text = text_page.get_text_bounded(left, bottom, right, top).strip()
                    if not text:
                        continue
                    key = (
                        text,
                        round(left * 10),
                        round(bottom * 10),
                        round(right * 10),
                        round(top * 10),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    candidate = _table_candidate(text)
                    blocks.append(
                        {
                            "text": text,
                            "bbox": {
                                "schema_version": LAYOUT_SCHEMA_VERSION,
                                "origin": "pdf_bottom_left",
                                "left": left,
                                "bottom": bottom,
                                "right": right,
                                "top": top,
                                "normalized_top_left": {
                                    "x": _clamp(left / width) if width else 0.0,
                                    "y": _clamp((height - top) / height) if height else 0.0,
                                    "width": _clamp((right - left) / width) if width else 0.0,
                                    "height": _clamp((top - bottom) / height) if height else 0.0,
                                },
                            },
                            "block_kind": "table_candidate" if candidate else "text",
                            "table_candidate": candidate,
                        }
                    )
                pages.append(
                    {
                        "page_number": page_index + 1,
                        "page_width": width,
                        "page_height": height,
                        "blocks": blocks,
                    }
                )
            finally:
                if text_page is not None:
                    text_page.close()
                page.close()
    finally:
        document.close()
    return pages

