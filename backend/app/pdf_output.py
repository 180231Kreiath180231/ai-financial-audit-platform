from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

PDF_TEMPLATE_VERSION = "audit-work-products-pdf-v2"
PDF_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2] / "templates" / "audit-work-products-pdf-v2.json"
)

_FONT_CANDIDATES = (
    (Path("C:/Windows/Fonts/msyh.ttc"), Path("C:/Windows/Fonts/msyhbd.ttc")),
    (Path("C:/Windows/Fonts/simsun.ttc"), Path("C:/Windows/Fonts/simhei.ttf")),
)
_FONT_REGULAR = "HengjianPdfRegular"
_FONT_BOLD = "HengjianPdfBold"


class PdfRenderError(RuntimeError):
    pass


def render_pdf_export(
    snapshot: dict[str, Any],
    draft: dict[str, Any],
    target: Path,
    created_at: str,
) -> None:
    try:
        template = json.loads(PDF_TEMPLATE_PATH.read_text(encoding="utf-8"))
        if template.get("template_version") != PDF_TEMPLATE_VERSION:
            raise PdfRenderError("PDF 模板版本与生成器不一致")
        palette = {
            key: colors.HexColor(value) for key, value in template["colors"].items()
        }
        margins = template["margins_mm"]
    except PdfRenderError:
        raise
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PdfRenderError("PDF 模板配置无效") from exc
    _register_fonts()
    document = SimpleDocTemplate(
        str(target),
        pagesize=A4,
        leftMargin=margins["left"] * mm,
        rightMargin=margins["right"] * mm,
        topMargin=margins["top"] * mm,
        bottomMargin=margins["bottom"] * mm,
        title=draft["title"],
        author="衡鉴审计工作台",
        subject=f"不可变快照 {snapshot['id']} / 最终草稿 {draft['id']} v{draft['version']}",
    )
    styles = _styles(palette)
    story: list[Any] = []
    payload = snapshot["snapshot"]
    project = payload["project"]
    risks = {risk["risk_id"]: risk for risk in payload["risks"]}

    story.extend(
        [
            Spacer(1, 24 * mm),
            Paragraph(_paragraph_text(project["name"]), styles["title"]),
            Paragraph("审计工作成果归档件", styles["subtitle"]),
            Spacer(1, 10 * mm),
            Paragraph(
                "本文件汇集最终固化的管理层沟通材料、风险清单、资料索取项目和访谈问题。"
                "风险事实、规则计算和证据引用来自不可变快照。",
                styles["body"],
            ),
            Spacer(1, 8 * mm),
        ]
    )
    metadata = [
        ("成果包标题", draft["title"]),
        ("审计主体", project["entity_name"]),
        ("审计期间", f"{project['year_start']} 至 {project['year_end']}"),
        ("源快照", snapshot["id"]),
        ("最终草稿", f"v{draft['version']}"),
        ("生成时间", created_at),
        (
            "成果范围",
            f"管理层事项 {len(draft['management'])} 项 / 风险 {len(draft['items'])} 项 / "
            f"资料 {len(draft['materials'])} 项 / 访谈问题 {len(draft['interviews'])} 项",
        ),
    ]
    story.append(_key_value_table(metadata, styles, palette, (34 * mm, 136 * mm)))
    if draft["notes"]:
        story.extend(
            [
                Spacer(1, 5 * mm),
                Paragraph(f"<b>编制备注</b>  {_paragraph_text(draft['notes'])}", styles["body"]),
            ]
        )

    story.extend(
        [PageBreak(), Paragraph(_paragraph_text(draft["management_title"]), styles["h1"])]
    )
    story.append(
        Paragraph(
            "以下内容用于管理层沟通准备。风险状态、风险等级和证据编号保持源快照记录；"
            "管理层意见和后续安排应由相关人员确认后另行留痕。",
            styles["body"],
        )
    )
    for item in draft["management"]:
        risk = risks[item["risk_id"]]
        citations = "、".join(evidence["citation"] for evidence in risk["evidence"])
        story.extend(
            [
                Spacer(1, 4 * mm),
                Paragraph(
                    f"{_paragraph_text(risk['risk_number'])} {_paragraph_text(item['heading'])}",
                    styles["h2"],
                ),
                _key_value_table(
                    [
                        ("风险等级", risk["risk_level"]),
                        ("风险状态", risk["status"]),
                        ("事项摘要", item["summary"]),
                        ("需管理层回复", item["response_request"]),
                        ("证据编号", citations),
                    ],
                    styles,
                    palette,
                    (32 * mm, 138 * mm),
                ),
            ]
        )

    story.extend([PageBreak(), Paragraph("风险清单", styles["h1"])])
    story.append(
        Paragraph(
            "以下内容按最终草稿顺序列示。风险编号、状态、规则、版本和证据引用保持源快照记录。",
            styles["body"],
        )
    )
    for item in draft["items"]:
        risk = risks[item["risk_id"]]
        story.extend(
            [
                Spacer(1, 4 * mm),
                Paragraph(
                    f"{_paragraph_text(risk['risk_number'])} {_paragraph_text(item['heading'])}",
                    styles["h2"],
                ),
            ]
        )
        if item["body"]:
            story.append(Paragraph(_paragraph_text(item["body"]), styles["body"]))
        details = [
            ("风险类型", risk["risk_type"]),
            ("风险等级", risk["risk_level"]),
            ("状态", risk["status"]),
            ("触发规则", f"{risk['trigger_rule_id']} / {risk['trigger_rule_version']}"),
            ("风险版本", f"v{risk['risk_version']}"),
            ("不确定性", risk["uncertainty"]),
        ]
        story.append(_key_value_table(details, styles, palette, (28 * mm, 142 * mm)))
        story.extend([Spacer(1, 3 * mm), Paragraph("证据索引", styles["h3"])])
        evidence_rows: list[list[Any]] = [
            [
                Paragraph("编号", styles["table_header"]),
                Paragraph("方向", styles["table_header"]),
                Paragraph("来源定位", styles["table_header"]),
                Paragraph("原文引用", styles["table_header"]),
            ]
        ]
        for evidence in risk["evidence"]:
            evidence_rows.append(
                [
                    Paragraph(_paragraph_text(evidence["citation"]), styles["table"]),
                    Paragraph(
                        "支持" if evidence["direction"] == "support" else "反证",
                        styles["table_center"],
                    ),
                    Paragraph(_paragraph_text(evidence["source_reference"]), styles["table"]),
                    Paragraph(_paragraph_text(evidence["quote"]), styles["table"]),
                ]
            )
        story.append(
            _styled_table(
                evidence_rows,
                palette,
                (28 * mm, 14 * mm, 45 * mm, 83 * mm),
                repeat_rows=1,
            )
        )

    story.extend([PageBreak(), Paragraph(_paragraph_text(draft["materials_title"]), styles["h1"])])
    story.append(
        Paragraph(
            "资料项目按最终草稿顺序列示。项目编号和关联风险保持锁定，具体提供方式与时间由审计人员另行确认。",
            styles["body"],
        )
    )
    for item in draft["materials"]:
        story.extend(
            [
                Spacer(1, 4 * mm),
                Paragraph(
                    f"{_paragraph_text(item['id'])} {_paragraph_text(item['title'])}",
                    styles["h2"],
                ),
                _key_value_table(
                    [
                        ("关联风险", item["risk_number"]),
                        ("优先级", item["priority"]),
                        ("取证用途", item["purpose"]),
                        ("索取范围", item["requested_scope"]),
                    ],
                    styles,
                    palette,
                    (28 * mm, 142 * mm),
                ),
            ]
        )

    story.extend([PageBreak(), Paragraph(_paragraph_text(draft["interview_title"]), styles["h1"])])
    story.append(
        Paragraph(
            "以下问题用于访谈准备。访谈记录、补充证据和后续判断应另行留痕，不以问题表述替代审计结论。",
            styles["body"],
        )
    )
    for item in draft["interviews"]:
        story.extend(
            [
                Spacer(1, 4 * mm),
                Paragraph(
                    f"{_paragraph_text(item['id'])} 关联风险 {_paragraph_text(item['risk_number'])}",
                    styles["h2"],
                ),
                _key_value_table(
                    [
                        ("建议访谈对象", item["audience"]),
                        ("访谈目的", item["objective"]),
                        ("访谈问题", item["question"]),
                    ],
                    styles,
                    palette,
                    (32 * mm, 138 * mm),
                ),
            ]
        )

    def decorate_page(canvas, _document) -> None:
        canvas.saveState()
        canvas.setTitle(draft["title"])
        canvas.setAuthor("衡鉴审计工作台")
        canvas.setSubject(
            f"不可变快照 {snapshot['id']} / 最终草稿 {draft['id']} v{draft['version']}"
        )
        canvas.setKeywords(snapshot["content_sha256"])
        canvas.setFont(_FONT_REGULAR, 8)
        canvas.setFillColor(palette["muted"])
        canvas.drawString(document.leftMargin, 9 * mm, f"最终草稿 v{draft['version']}")
        canvas.drawRightString(A4[0] - document.rightMargin, 9 * mm, f"第 {canvas.getPageNumber()} 页")
        canvas.restoreState()

    document.build(story, onFirstPage=decorate_page, onLaterPages=decorate_page)
    try:
        reader = PdfReader(target)
    except Exception as exc:
        raise PdfRenderError("生成的 PDF 无法重新打开") from exc
    if not reader.pages:
        raise PdfRenderError("生成的 PDF 不包含任何页面")


def _register_fonts() -> None:
    if _FONT_REGULAR in pdfmetrics.getRegisteredFontNames():
        return
    for regular, bold in _FONT_CANDIDATES:
        if regular.is_file() and bold.is_file():
            pdfmetrics.registerFont(TTFont(_FONT_REGULAR, str(regular)))
            pdfmetrics.registerFont(TTFont(_FONT_BOLD, str(bold)))
            pdfmetrics.registerFontFamily(
                "HengjianPdf",
                normal=_FONT_REGULAR,
                bold=_FONT_BOLD,
                italic=_FONT_REGULAR,
                boldItalic=_FONT_BOLD,
            )
            return
    raise PdfRenderError("未找到可嵌入的 Windows 中文字体")


def _styles(palette: dict[str, colors.Color]) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "PdfTitle",
            parent=base["Title"],
            fontName=_FONT_BOLD,
            fontSize=24,
            leading=32,
            alignment=TA_LEFT,
            textColor=palette["navy"],
            spaceAfter=8,
        ),
        "subtitle": ParagraphStyle(
            "PdfSubtitle",
            parent=base["Normal"],
            fontName=_FONT_REGULAR,
            fontSize=13,
            leading=20,
            textColor=palette["muted"],
        ),
        "h1": ParagraphStyle(
            "PdfHeading1",
            parent=base["Heading1"],
            fontName=_FONT_BOLD,
            fontSize=18,
            leading=25,
            textColor=palette["navy"],
            spaceAfter=8,
        ),
        "h2": ParagraphStyle(
            "PdfHeading2",
            parent=base["Heading2"],
            fontName=_FONT_BOLD,
            fontSize=12,
            leading=18,
            textColor=palette["navy"],
            spaceBefore=4,
            spaceAfter=5,
        ),
        "h3": ParagraphStyle(
            "PdfHeading3",
            parent=base["Heading3"],
            fontName=_FONT_BOLD,
            fontSize=10,
            leading=15,
            textColor=palette["navy"],
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "PdfBody",
            parent=base["BodyText"],
            fontName=_FONT_REGULAR,
            fontSize=9.5,
            leading=15,
            textColor=palette["text"],
            spaceAfter=5,
        ),
        "table": ParagraphStyle(
            "PdfTable",
            parent=base["BodyText"],
            fontName=_FONT_REGULAR,
            fontSize=8,
            leading=12,
            textColor=palette["text"],
        ),
        "table_center": ParagraphStyle(
            "PdfTableCenter",
            parent=base["BodyText"],
            fontName=_FONT_REGULAR,
            fontSize=8,
            leading=12,
            alignment=TA_CENTER,
            textColor=palette["text"],
        ),
        "table_header": ParagraphStyle(
            "PdfTableHeader",
            parent=base["BodyText"],
            fontName=_FONT_BOLD,
            fontSize=8,
            leading=12,
            alignment=TA_CENTER,
            textColor=colors.white,
        ),
    }


def _paragraph_text(value: Any) -> str:
    return escape(str(value or "")).replace("\n", "<br/>")


def _key_value_table(
    values: list[tuple[str, Any]],
    styles: dict[str, ParagraphStyle],
    palette: dict[str, colors.Color],
    widths: tuple[float, float],
) -> Table:
    rows: list[list[Any]] = []
    for label, value in values:
        rows.append(
            [
                Paragraph(_paragraph_text(label), styles["table_header"]),
                Paragraph(_paragraph_text(value), styles["table"]),
            ]
        )
    table = _styled_table(rows, palette, widths)
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, -1), palette["navy"])]))
    return table


def _styled_table(
    rows: list[list[Any]],
    palette: dict[str, colors.Color],
    widths: tuple[float, ...],
    *,
    repeat_rows: int = 0,
) -> Table:
    table = Table(rows, colWidths=widths, repeatRows=repeat_rows, hAlign="LEFT")
    commands: list[tuple[Any, ...]] = [
        ("GRID", (0, 0), (-1, -1), 0.45, palette["border"]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if repeat_rows:
        commands.append(("BACKGROUND", (0, 0), (-1, repeat_rows - 1), palette["navy"]))
        first_data_row = repeat_rows
    else:
        first_data_row = 0
    for row_index in range(first_data_row, len(rows)):
        if (row_index - first_data_row) % 2 == 1:
            commands.append(("BACKGROUND", (0, row_index), (-1, row_index), palette["pale_blue"]))
    table.setStyle(TableStyle(commands))
    return table
