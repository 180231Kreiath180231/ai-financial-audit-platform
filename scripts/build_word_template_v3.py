from pathlib import Path

from docx import Document

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "templates" / "audit-work-products-word-v2.docx"
TARGET = ROOT / "templates" / "audit-work-products-word-v3.docx"


document = Document(SOURCE)
document.core_properties.subject = "审计工作成果 Word v3 模板"
document.save(TARGET)
