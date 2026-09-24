from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.shared import RGBColor


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "templates" / "audit-work-products-word-v1.docx"
TARGET = ROOT / "templates" / "audit-work-products-word-v2.docx"


document = Document(SOURCE)
title = document.styles["Title"]
title.font.color.rgb = RGBColor(0, 0, 0)
paragraph_properties = title.element.get_or_add_pPr()
border = paragraph_properties.find(qn("w:pBdr"))
if border is not None:
    paragraph_properties.remove(border)
document.save(TARGET)
