from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "templates" / "audit-work-products-word-v1.docx"
FONT = "Microsoft YaHei"


def set_font(style, size: float, *, bold: bool = False) -> None:
    style.font.name = FONT
    style.font.size = Pt(size)
    style.font.bold = bold
    style.font.color.rgb = RGBColor(0, 0, 0)
    style._element.rPr.rFonts.set(qn("w:ascii"), FONT)
    style._element.rPr.rFonts.set(qn("w:hAnsi"), FONT)
    style._element.rPr.rFonts.set(qn("w:eastAsia"), FONT)


def build() -> None:
    document = Document()
    section = document.sections[0]
    section.orientation = WD_ORIENT.PORTRAIT
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = Inches(0.72)
    section.bottom_margin = Inches(0.7)
    section.left_margin = Inches(0.8)
    section.right_margin = Inches(0.8)
    section.header_distance = Inches(0.3)
    section.footer_distance = Inches(0.3)

    styles = document.styles
    set_font(styles["Normal"], 10.5)
    styles["Normal"].paragraph_format.line_spacing = 1.35
    styles["Normal"].paragraph_format.space_after = Pt(6)
    set_font(styles["Title"], 22, bold=True)
    styles["Title"].paragraph_format.space_after = Pt(8)
    set_font(styles["Subtitle"], 11)
    styles["Subtitle"].font.color.rgb = RGBColor(78, 91, 108)
    styles["Subtitle"].paragraph_format.space_after = Pt(18)
    for name, size in (("Heading 1", 15), ("Heading 2", 12), ("Heading 3", 10.5)):
        set_font(styles[name], size, bold=True)
        styles[name].paragraph_format.keep_with_next = True
        styles[name].paragraph_format.space_before = Pt(12)
        styles[name].paragraph_format.space_after = Pt(6)

    if "Audit Metadata" not in styles:
        metadata = styles.add_style("Audit Metadata", WD_STYLE_TYPE.PARAGRAPH)
        set_font(metadata, 9)
        metadata.font.color.rgb = RGBColor(78, 91, 108)

    document.core_properties.title = "审计工作成果 Word 模板"
    document.core_properties.subject = "风险清单 资料清单 访谈提纲"
    document.core_properties.author = "衡鉴审计工作台"
    document.add_paragraph("[[DOCUMENT_BODY]]")
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    document.save(TARGET)


if __name__ == "__main__":
    build()
