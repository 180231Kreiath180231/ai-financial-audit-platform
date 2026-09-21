from pathlib import Path
from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor


OUT = Path(__file__).resolve().parents[1] / "docs"
OUT.mkdir(parents=True, exist_ok=True)

NAVY = "17365D"
BLUE = "2F5597"
LIGHT_BLUE = "EAF1F8"
PALE = "F6F8FB"
GRAY = "666666"
BORDER = "D9E1E8"
BLACK = RGBColor(0, 0, 0)


def set_cell_shading(cell, fill):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_margins(cell, top=100, start=120, bottom=100, end=120):
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for m, v in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{m}"))
        if node is None:
            node = OxmlElement(f"w:{m}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(v))
        node.set(qn("w:type"), "dxa")


def set_cell_width(cell, width_cm):
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_w = tc_pr.find(qn("w:tcW"))
    if tc_w is None:
        tc_w = OxmlElement("w:tcW")
        tc_pr.append(tc_w)
    tc_w.set(qn("w:w"), str(int(Cm(width_cm).twips)))
    tc_w.set(qn("w:type"), "dxa")


def set_fixed_table_width(table, widths):
    tbl_pr = table._tbl.tblPr
    for i, width in enumerate(widths):
        table.columns[i].width = Cm(width)

    layout = tbl_pr.find(qn("w:tblLayout"))
    if layout is None:
        layout = OxmlElement("w:tblLayout")
        tbl_pr.append(layout)
    layout.set(qn("w:type"), "fixed")

    tbl_w = tbl_pr.find(qn("w:tblW"))
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        tbl_pr.append(tbl_w)
    tbl_w.set(qn("w:w"), str(int(Cm(sum(widths)).twips)))
    tbl_w.set(qn("w:type"), "dxa")

    tbl_ind = tbl_pr.find(qn("w:tblInd"))
    if tbl_ind is None:
        tbl_ind = OxmlElement("w:tblInd")
        tbl_pr.append(tbl_ind)
    tbl_ind.set(qn("w:w"), "0")
    tbl_ind.set(qn("w:type"), "dxa")


def suppress_paragraph_borders(paragraph):
    p_pr = paragraph._p.get_or_add_pPr()
    p_bdr = p_pr.find(qn("w:pBdr"))
    if p_bdr is None:
        p_bdr = OxmlElement("w:pBdr")
        p_pr.append(p_bdr)
    for edge in ("top", "left", "bottom", "right", "between", "bar"):
        node = p_bdr.find(qn(f"w:{edge}"))
        if node is None:
            node = OxmlElement(f"w:{edge}")
            p_bdr.append(node)
        node.set(qn("w:val"), "nil")


def set_table_borders(table):
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.first_child_found_in("w:tblBorders")
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        node = borders.find(qn(f"w:{edge}"))
        if node is None:
            node = OxmlElement(f"w:{edge}")
            borders.append(node)
        node.set(qn("w:val"), "single")
        node.set(qn("w:sz"), "4")
        node.set(qn("w:color"), BORDER)


def set_repeat_header(row):
    tr_pr = row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)


def prevent_row_split(row):
    tr_pr = row._tr.get_or_add_trPr()
    cant_split = OxmlElement("w:cantSplit")
    tr_pr.append(cant_split)


def set_run_font(run, name="Microsoft YaHei", size=None, bold=None, color=None):
    run.font.name = name
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), name)
    run._element.get_or_add_rPr().rFonts.set(qn("w:ascii"), name)
    run._element.get_or_add_rPr().rFonts.set(qn("w:hAnsi"), name)
    if size:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if color:
        run.font.color.rgb = RGBColor.from_string(color)


def add_hyperlink(paragraph, text, url):
    part = paragraph.part
    r_id = part.relate_to(url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink", is_external=True)
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)
    run = OxmlElement("w:r")
    r_pr = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), BLUE)
    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "single")
    r_pr.append(color)
    r_pr.append(underline)
    run.append(r_pr)
    t = OxmlElement("w:t")
    t.text = text
    run.append(t)
    hyperlink.append(run)
    paragraph._p.append(hyperlink)


def setup_doc(title, subtitle, purpose, short_title):
    doc = Document()
    section = doc.sections[0]
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.0)
    section.bottom_margin = Cm(1.8)
    section.left_margin = Cm(2.15)
    section.right_margin = Cm(2.15)

    styles = doc.styles
    normal = styles["Normal"]
    normal.font.name = "Microsoft YaHei"
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = BLACK
    normal.paragraph_format.space_after = Pt(5)
    normal.paragraph_format.line_spacing = 1.28

    for name, size, before, after in (("Title", 22, 0, 12), ("Heading 1", 16, 16, 7), ("Heading 2", 13, 11, 5), ("Heading 3", 11, 8, 4)):
        st = styles[name]
        st.font.name = "Microsoft YaHei"
        st._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
        st.font.size = Pt(size)
        st.font.bold = True
        st.font.color.rgb = BLACK
        st.paragraph_format.space_before = Pt(before)
        st.paragraph_format.space_after = Pt(after)
        st.paragraph_format.keep_with_next = True
        if name == "Title":
            p_pr = st._element.get_or_add_pPr()
            p_bdr = p_pr.find(qn("w:pBdr"))
            if p_bdr is not None:
                p_pr.remove(p_bdr)

    title_p = doc.add_paragraph(style="Title")
    title_p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    suppress_paragraph_borders(title_p)
    set_run_font(title_p.add_run(title), size=22, bold=True)
    sub = doc.add_paragraph()
    set_run_font(sub.add_run(subtitle), size=11, color=GRAY)
    sub.paragraph_format.space_after = Pt(14)
    intro = doc.add_paragraph()
    set_run_font(intro.add_run(purpose), size=11)
    intro.paragraph_format.space_after = Pt(14)

    meta = doc.add_table(rows=3, cols=2)
    meta.alignment = WD_TABLE_ALIGNMENT.LEFT
    meta.autofit = False
    meta.columns[0].width = Cm(3.2)
    meta.columns[1].width = Cm(13.0)
    for row, values in zip(meta.rows, (("文档版本", "1.0"), ("基准日期", "2026年9月19日"), ("适用范围", "单人内部审计师使用的Windows本地优先MVP"))):
        for i, value in enumerate(values):
            row.cells[i].text = value
            row.cells[i].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            set_cell_margins(row.cells[i])
        set_cell_shading(row.cells[0], LIGHT_BLUE)
        row.cells[0].paragraphs[0].runs[0].bold = True
    set_table_borders(meta)
    doc.add_paragraph()

    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run_font(footer.add_run(f"{short_title}  版本 1.0  2026年9月"), size=8.5, color=GRAY)
    return doc


def add_heading(doc, text, level=1):
    return doc.add_paragraph(text, style=f"Heading {level}")


def add_para(doc, text, bold_lead=None):
    p = doc.add_paragraph()
    if bold_lead and text.startswith(bold_lead):
        set_run_font(p.add_run(bold_lead), bold=True)
        set_run_font(p.add_run(text[len(bold_lead):]))
    else:
        set_run_font(p.add_run(text))
    return p


def add_bullets(doc, items, level=0):
    for item in items:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p.paragraph_format.left_indent = Cm(0.65 if level == 0 else 1.2)
        p.paragraph_format.first_line_indent = Cm(-0.35)
        p.paragraph_format.keep_together = True
        set_run_font(p.add_run("• "))
        set_run_font(p.add_run(item))


def add_numbered(doc, items):
    for item in items:
        p = doc.add_paragraph(style="List Number")
        set_run_font(p.add_run(item))


def add_table(doc, headers, rows, widths=None, font_size=8.8):
    table = doc.add_table(rows=1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    if widths:
        set_fixed_table_width(table, widths)
    hdr = table.rows[0]
    set_repeat_header(hdr)
    for i, header in enumerate(headers):
        cell = hdr.cells[i]
        cell.text = header
        if widths:
            set_cell_width(cell, widths[i])
        set_cell_shading(cell, NAVY)
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        set_cell_margins(cell, 110, 100, 110, 100)
        for run in cell.paragraphs[0].runs:
            set_run_font(run, size=font_size, bold=True, color="FFFFFF")
        cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        cell.paragraphs[0].paragraph_format.keep_with_next = True
    for r_idx, row_data in enumerate(rows):
        row = table.add_row()
        prevent_row_split(row)
        for i, value in enumerate(row_data):
            cell = row.cells[i]
            cell.text = str(value)
            if widths:
                set_cell_width(cell, widths[i])
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            set_cell_margins(cell, 95, 100, 95, 100)
            if r_idx % 2:
                set_cell_shading(cell, PALE)
            for p in cell.paragraphs:
                p.paragraph_format.space_after = Pt(0)
                p.paragraph_format.line_spacing = 1.12
                for run in p.runs:
                    set_run_font(run, size=font_size)
    if widths:
        set_fixed_table_width(table, widths)
    set_table_borders(table)
    doc.add_paragraph().paragraph_format.space_after = Pt(1)
    return table


def add_source_link(doc, label, url):
    p = doc.add_paragraph()
    set_run_font(p.add_run(label + "  "), bold=True)
    add_hyperlink(p, url, url)


def save(doc, name):
    path = OUT / name
    doc.core_properties.title = name.replace(".docx", "")
    doc.core_properties.subject = "AI财务审计分析平台MVP开发文档"
    doc.core_properties.author = ""
    doc.core_properties.last_modified_by = ""
    doc.save(path)
    return path


def build_prd():
    doc = setup_doc(
        "AI财务审计分析平台 MVP 产品需求说明书",
        "本地优先 多模型 API 低负载实施版",
        "本文档给出MVP的正式产品范围、功能要求、数据边界和验收口径。开发应以本版本为准。产品面向单人内部审计师，原始资料和审计结果保存在本地，模型能力通过用户配置的外部API提供。",
        "产品需求说明书",
    )
    add_heading(doc, "产品结论", 1)
    add_para(doc, "本项目可以进入开发。MVP采用本地优先架构，不部署本地大模型，不运行Docker或服务器级知识库。DeepSeek、GLM、Kimi、通义千问及其他OpenAI兼容模型通过统一网关接入。")
    add_para(doc, "必须修正的原始需求", bold_lead="必须修正的原始需求")
    add_bullets(doc, [
        "将全程离线改为本地优先。启用外部模型API时，系统必须联网并向所选服务商发送最小必要数据。",
        "将每次使用11年全量文档作为上下文改为在全量资料中检索，每次仅发送相关证据和结构化数据。",
        "将Z-score单一异常识别改为确定性规则、稳健统计、趋势指标和模型解释相结合。",
        "将扫描件全部精确高亮改为MVP保证页码定位，坐标高亮取决于OCR结果是否包含可靠坐标。",
        "将完整推理过程改为分析依据、证据、计算步骤、规则、假设和不确定性。",
    ])

    add_heading(doc, "产品定位和目标", 1)
    add_para(doc, "平台用于多年财务审计资料的本地管理、异常发现、证据检索、审计程序生成、访谈准备和报告出稿。AI负责文档理解、证据归纳和文字生成；本地程序负责金额计算、统计检测、任务状态、缓存和审计留痕。")
    add_table(doc, ["目标", "MVP结果"], [
        ("降低资料审阅时间", "批量导入、增量处理、页码检索和风险聚合"),
        ("提高异常分析深度", "历史基线、稳健统计、相关证据和潜在原因"),
        ("形成可核查工作产品", "风险卡片、资料清单、访谈问题、证据包和固定模板报告"),
        ("控制本地资源", "16GB轻薄本可用，应用进程受控，后台任务自动降速和暂停"),
        ("避免模型绑定", "用户可配置模型服务商、模型名称、任务路由和备用模型"),
    ], [4.2, 12.0])

    add_heading(doc, "用户和使用场景", 1)
    add_para(doc, "唯一目标用户为单人内部审计师。MVP不建设组织、角色和复杂权限体系，但服务只绑定本机回环地址，并保留本地访问令牌，防止局域网误访问。")
    add_bullets(doc, [
        "审前准备时批量导入多年审计报告、年报、科目资料、凭证、合同、会议纪要和银行资料。",
        "风险评估时识别跨年度异动、异常余额、勾稽差异和需要补充证据的事项。",
        "现场审计时查看证据、记录备忘录、生成资料清单和访谈问题。",
        "报告阶段将已核实风险写入固定Word、Excel和PDF模板。",
    ])

    add_heading(doc, "产品范围", 1)
    add_heading(doc, "MVP必须完成", 2)
    add_bullets(doc, [
        "批量和增量导入PDF，识别原生PDF和扫描PDF。",
        "任务暂停、继续、失败重试、损坏文件跳过和断点恢复。",
        "原生PDF本地抽取文字、表格、页码和可用坐标。",
        "扫描页调用视觉模型API并保存结构化结果、模型版本和页面对应关系。",
        "年度、主体、科目、金额、风险类型和文档类型抽取及人工校正。",
        "全文检索、向量检索和DuckDB结构化查询联合取证。",
        "异常卡片、风险状态、证据链接、人工意见和历史版本。",
        "资料清单、访谈问题、风险清单、管理层材料和证据包导出。",
        "多模型配置、能力识别、任务路由、备用模型、成本记录和缓存。",
        "轻薄本资源治理和严格离线开关。",
    ])
    add_heading(doc, "MVP明确不做", 2)
    add_bullets(doc, [
        "全自动三张表深度勾稽和全自动责任界定。",
        "领导任期自动拆分和复杂关系图谱。",
        "本地大模型、本地Embedding模型和GPU推理。",
        "多用户、部门、权限和审批体系。",
        "复杂大屏、实时流数据和移动端应用。",
        "对全部扫描件承诺字符级坐标高亮。",
    ])

    add_heading(doc, "功能需求", 1)
    function_rows = [
        ("项目工作区", "创建项目、设置年度范围、选择模型方案、显示处理概况和最近活动", "P0"),
        ("文档上传", "批量上传、增量上传、哈希去重、进度、暂停、继续、重试和跳过", "P0"),
        ("报告解析", "PDF.js阅读器、页码跳转、原文检索、批注、结构化数据和人工校正", "P0"),
        ("异常预警", "时间轴、筛选、风险卡片、状态、证据、反证、批量导出", "P0"),
        ("访谈提纲", "按风险汇总问题，可编辑、排序和导出", "P0"),
        ("报告生成", "固定模板、AI草稿、人工二次编辑、Word Excel PDF导出", "P0"),
        ("审计备忘录", "多条笔记、命名、编辑、删除、关联风险和允许AI读取", "P0"),
        ("模型设置", "服务商、Base URL、API Key、模型名称、能力、任务路由和测试连接", "P0"),
        ("调用记录", "记录发送范围、模型、耗时、Token、费用、缓存和错误", "P0"),
        ("严格离线模式", "阻止外部请求，保留本地查询和已生成结果", "P1"),
    ]
    add_table(doc, ["模块", "核心要求", "优先级"], function_rows, [3.1, 11.5, 1.5], 8.5)

    add_heading(doc, "多模型路由", 1)
    add_para(doc, "系统不固定任何模型名称。模型版本变化时，用户可在界面新增或修改配置，不需要升级应用。每个模型记录文本、视觉、JSON、工具调用、Embedding、上下文长度和文件上传等能力。")
    add_table(doc, ["任务档案", "默认能力要求", "路由规则"], [
        ("视觉识别", "图片输入和结构化输出", "当前模型不支持视觉时自动切换视觉备用模型"),
        ("快速抽取", "低延迟、JSON输出", "优先低成本模型，失败后切换备用模型"),
        ("风险分析", "长上下文、推理、稳定指令遵循", "使用用户指定主模型，高风险可启用第二模型复核"),
        ("报告生成", "长文本和格式稳定", "只发送已确认风险和必要证据"),
        ("Embedding", "向量接口", "向量维度变更时创建新索引版本，不混用旧向量"),
    ], [3.2, 5.8, 7.0], 8.5)

    add_heading(doc, "数据处理和证据要求", 1)
    add_numbered(doc, [
        "上传后计算SHA-256文件哈希，同一项目内默认不重复处理相同文件。",
        "原生PDF优先本地解析，只有扫描页或解析失败页进入视觉API。",
        "每个文字块保存项目、文档、页码、块序号、原文、抽取方式和版本。",
        "每条风险保存触发规则、输入值、基线值、计算结果、模型解释、支持证据、反证和人工状态。",
        "新增资料只触发相关年度、科目、主体和风险的重新检索与分析。",
        "风险结论更新时保留旧版本，不覆盖审计历史。",
    ])

    add_heading(doc, "异常识别规则", 1)
    add_para(doc, "MVP不允许模型直接计算金额。异常引擎先在本地生成可复现指标，再把指标和证据交给模型解释。十一年度数据点较少，Z-score只能作为辅助指标。")
    add_table(doc, ["方法", "用途", "限制"], [
        ("确定性财务规则", "借贷平衡、合计、期初期末、勾稽和重复记录", "规则必须版本化"),
        ("同比和趋势", "年度变动、连续上升下降、趋势拐点", "需处理缺失年度和会计政策变化"),
        ("中位数和MAD", "降低极端年份对历史基线的影响", "样本过少时只提示不定性"),
        ("Z-score", "辅助衡量偏离程度", "不得单独决定高风险"),
        ("结构占比", "科目占总资产、收入或费用比例变化", "分母和口径必须一致"),
        ("模型解释", "结合合同、纪要、报告等非结构化证据解释原因", "只能形成线索，最终由审计人员确认"),
    ], [3.0, 7.0, 6.0], 8.4)

    add_heading(doc, "资源和性能要求", 1)
    add_table(doc, ["指标", "验收要求"], [
        ("目标设备", "Windows 10或11，4核8线程以上，16GB内存，SSD剩余空间100GB以上"),
        ("常驻内存", "应用后端、索引和任务服务空闲合计不高于2.5GB，不含用户浏览器其他标签"),
        ("工作内存", "常规任务目标不高于5GB，DuckDB默认内存上限2GB"),
        ("应用CPU", "持续平均目标不高于35%，短时峰值不高于45%"),
        ("整机保护", "整机CPU连续超过50%时暂停后台任务，低于30%后恢复"),
        ("任务并发", "本地CPU任务固定1个，外部API请求默认2个并可配置"),
        ("运行方式", "不得要求Docker、WSL、GPU或本地模型"),
    ], [4.0, 12.0])

    add_heading(doc, "安全和隐私要求", 1)
    add_bullets(doc, [
        "界面必须清楚显示当前是否允许外部API请求。",
        "每次外发记录服务商、模型、任务、文档页码、发送时间、结果状态和数据摘要。",
        "API Key使用Windows凭据保护或等效方式加密，日志不得记录明文密钥。",
        "外部文件上传应设置最短保存时间，并在任务完成后调用删除接口。",
        "本地服务只监听127.0.0.1，禁止默认暴露至局域网。",
        "严格离线模式通过统一网络拦截器阻断全部模型和Embedding请求。",
        "模型输出不得直接写入最终审计结论，必须经过人工状态确认。",
    ])

    add_heading(doc, "验收标准", 1)
    acceptance = [
        ("导入", "可批量和增量导入PDF；损坏文件不阻塞整批任务"),
        ("恢复", "程序关闭后再次打开，任务、文档、风险和笔记状态完整"),
        ("模型", "至少成功配置两家不同厂商，并可在界面切换"),
        ("路由", "文本模型不支持视觉时自动使用视觉备用模型并在结果中标明"),
        ("证据", "每条AI风险至少包含文档名、页码和原文片段"),
        ("计算", "金额和统计指标均能通过本地代码复算"),
        ("增量", "新增资料只重算受影响事项，并保存前后结论"),
        ("人工复核", "风险可标记待核实、已核实、排除，并同步到导出结果"),
        ("报告", "Word、Excel和PDF导出与当前风险状态一致"),
        ("性能", "在基准轻薄本压力测试中满足CPU和内存保护要求"),
        ("隐私", "可查看全部外发记录，严格离线模式下无外部请求"),
        ("失败处理", "API超时、限流和余额不足可重试、切换备用模型或人工跳过"),
    ]
    add_table(doc, ["验收域", "通过条件"], acceptance, [3.0, 13.0], 8.7)
    return save(doc, "01_AI财务审计分析平台_MVP产品需求说明书.docx")


def build_architecture():
    doc = setup_doc(
        "AI财务审计分析平台 MVP 技术架构设计",
        "单机低负载 多模型 API 本地证据仓",
        "本文档定义MVP的技术边界、模块、数据结构、模型网关、任务状态和资源治理方法。目标是让应用在16GB轻薄本上稳定运行，并保持财务计算和证据链可复现。",
        "技术架构设计说明书",
    )
    add_heading(doc, "架构决策", 1)
    add_table(doc, ["决策", "选项", "原因"], [
        ("运行形态", "本地Web应用", "使用系统浏览器，避免Electron常驻开销；后端只监听127.0.0.1"),
        ("部署方式", "原生Windows安装包", "不要求Docker、WSL或服务器组件"),
        ("事务存储", "SQLite", "单用户、零运维、适合任务和风险状态"),
        ("分析引擎", "DuckDB", "进程内分析PDF抽取表和多年财务数据，可限制线程和内存"),
        ("检索", "SQLite FTS5加sqlite-vec", "全文与向量同库，避免独立向量服务"),
        ("模型接入", "LiteLLM SDK加厂商适配器", "统一协议，同时保留视觉和文件API等厂商能力"),
        ("任务队列", "SQLite持久化单工作器", "无需Redis或Celery，支持暂停和恢复"),
        ("文件存储", "本地目录加哈希索引", "减少MinIO等常驻服务"),
    ], [3.1, 4.5, 8.4], 8.4)

    add_heading(doc, "总体架构", 1)
    add_para(doc, "界面通过本地HTTP接口访问后端。后端将文件处理、结构化查询、证据检索和模型调用拆成独立模块。任何模型请求必须经过模型网关和外发审计器。")
    arch = [
        ("表现层", "React PDF.js ECharts", "上传、阅读、风险、访谈、报告、设置"),
        ("应用层", "FastAPI Uvicorn", "本地API、业务校验、流式响应和文件下载"),
        ("任务层", "SQLite任务表 单工作器", "任务分步执行、暂停、重试和断点恢复"),
        ("审计引擎", "DuckDB Python规则", "金额计算、基线、异常分数和勾稽"),
        ("检索层", "FTS5 sqlite-vec", "关键词、向量、元数据过滤和融合排序"),
        ("模型层", "LiteLLM SDK Provider Adapter", "DeepSeek GLM Kimi 千问 自定义端点"),
        ("存储层", "SQLite DuckDB 本地目录", "元数据、结构化数据、原始文件和导出物"),
        ("控制层", "Resource Governor Egress Audit", "CPU内存控制、外发记录和离线开关"),
    ]
    add_table(doc, ["层级", "技术", "职责"], arch, [2.4, 5.1, 8.5], 8.5)

    add_heading(doc, "技术组件", 1)
    components = [
        ("frontend", "React TypeScript", "标签页、表单、流式结果和本地状态"),
        ("pdf-viewer", "PDF.js", "页码跳转、文本搜索、高亮和批注"),
        ("backend", "FastAPI Uvicorn", "REST和SSE接口、校验、任务控制"),
        ("metadata-db", "SQLite", "项目、文档、风险、笔记、任务、模型、缓存和日志"),
        ("analytics", "DuckDB", "年度指标、规则结果和异常统计"),
        ("retrieval", "FTS5 sqlite-vec", "混合检索和元数据过滤"),
        ("model-gateway", "LiteLLM SDK", "协议归一化、重试、备用模型和用量"),
        ("document", "pypdf pdfplumber", "原生PDF页级提取和表格候选"),
        ("report", "python-docx docxtpl openpyxl", "Word和Excel模板输出"),
        ("resource", "psutil Windows Job Object", "监控、降速、暂停和进程CPU上限"),
    ]
    add_table(doc, ["模块标识", "建议技术", "职责"], components, [3.2, 4.6, 8.2], 8.4)

    add_heading(doc, "核心数据模型", 1)
    data_rows = [
        ("projects", "项目名称、年度范围、模式、默认模型方案", "项目根记录"),
        ("documents", "哈希、路径、类型、页数、解析状态、版本", "原始文件索引"),
        ("pages", "文档、页码、文本、图像路径、解析方法", "页级证据"),
        ("chunks", "页面、块序号、文本、元数据、索引版本", "检索最小单元"),
        ("extracted_values", "年度、主体、科目、金额、来源、校正状态", "结构化抽取"),
        ("risk_items", "风险类型、等级、状态、摘要、规则版本", "风险主记录"),
        ("risk_evidence", "风险、文档、页码、块、证据方向", "支持证据和反证"),
        ("risk_versions", "旧结论、新结论、变化原因、确认状态", "增量更新历史"),
        ("notes", "标题、正文、关联项目和风险", "审计备忘录"),
        ("tasks", "类型、状态、当前步骤、进度、重试和错误", "可恢复任务"),
        ("model_profiles", "服务商、端点、模型、能力、密钥引用", "多模型配置"),
        ("model_calls", "请求摘要、外发范围、用量、费用、耗时和结果", "模型审计日志"),
        ("cache_entries", "任务指纹、模型、提示词、证据哈希和结果", "可控缓存"),
        ("exports", "模板、版本、文件路径、生成时间和风险快照", "历史出稿"),
    ]
    add_table(doc, ["数据表", "关键字段", "用途"], data_rows, [3.6, 7.6, 4.8], 8.1)

    add_heading(doc, "文档处理管线", 1)
    add_numbered(doc, [
        "登记文件并计算SHA-256，命中已有文件时复用解析结果。",
        "检测是否存在可用文本层。原生PDF进入本地提取，扫描页进入图像任务。",
        "扫描页按需逐页渲染。单页完成上传后立即释放图像内存和临时文件。",
        "模型网关选择视觉模型并要求固定JSON输出。输出先做JSON Schema验证。",
        "本地规则检查金额格式、借贷方向、合计和跨页一致性。",
        "保存页级文本、结构化数据和模型调用记录，再生成检索块。",
        "调用Embedding API，将向量写入带版本的sqlite-vec索引。",
    ])

    add_heading(doc, "检索和上下文构建", 1)
    add_para(doc, "系统在全部11年资料中检索，但不把全部资料发送给模型。上下文构建器先读取结构化指标，再执行全文和向量检索，最后按页码、年度、科目和来源去重。")
    add_table(doc, ["步骤", "处理", "默认上限"], [
        ("问题解析", "识别年度、主体、科目、风险类型和任务意图", "1次快速模型调用"),
        ("结构化查询", "DuckDB返回指标和异常结果", "200行"),
        ("关键词召回", "FTS5查询关键名词和精确数字", "50块"),
        ("向量召回", "sqlite-vec语义检索", "50块"),
        ("融合排序", "规则分数加可选API Rerank", "保留20至30块"),
        ("上下文封装", "按证据编号、页码和来源组合", "由模型上下文预算控制"),
    ], [2.8, 9.0, 4.2], 8.5)

    add_heading(doc, "模型网关设计", 1)
    add_para(doc, "网关提供统一任务接口，并允许适配器直接调用厂商原生视觉、文件和Responses接口。不能把所有模型假定为完全兼容；每个模型必须通过能力注册表声明支持项。")
    add_table(doc, ["能力字段", "含义", "处理方式"], [
        ("text", "文本对话", "所有分析模型必须支持"),
        ("vision", "图片输入", "不支持时路由至视觉备用模型"),
        ("json_schema", "结构化输出", "不支持时使用提示约束和本地修复器"),
        ("tool_calls", "工具调用", "仅在能力验证通过后启用"),
        ("embedding", "文本向量", "维度写入索引版本，不同维度不得混用"),
        ("files", "文件上传和复用", "记录远端文件ID、到期时间和删除结果"),
        ("reasoning", "推理模式", "只保存可展示的分析依据，不保存隐藏思维链"),
    ], [3.0, 6.1, 6.9], 8.4)

    add_heading(doc, "任务状态机", 1)
    add_table(doc, ["状态", "允许动作", "说明"], [
        ("queued", "开始 取消", "等待单工作器"),
        ("running", "暂停 取消", "执行一个可重入步骤"),
        ("pausing", "等待", "当前安全点完成后暂停"),
        ("paused", "继续 取消", "进度和中间结果已落盘"),
        ("retry_wait", "立即重试 跳过", "API限流或临时错误"),
        ("failed", "重试 跳过 查看错误", "不可自动恢复或重试耗尽"),
        ("completed", "查看结果 重新运行", "所有输出已提交"),
        ("cancelled", "重新运行", "保留日志，清理临时文件"),
    ], [3.0, 5.0, 8.0], 8.5)

    add_heading(doc, "资源治理", 1)
    add_para(doc, "资源目标通过应用进程限制和整机负载监控共同实现。应用无法控制其他软件，因此验收应约束本应用进程，并要求整机负载超过阈值时暂停后台任务。")
    add_table(doc, ["控制项", "默认值", "实现"], [
        ("本地CPU任务并发", "1", "单工作器串行处理页面、解析和统计"),
        ("API并发", "2", "异步HTTP信号量，可由用户调整为1至4"),
        ("DuckDB线程", "逻辑核心25%且最多2", "连接初始化时设置threads"),
        ("DuckDB内存", "2GB", "设置memory_limit并允许用户降低"),
        ("应用CPU硬上限", "35%至40%", "Windows Job Object CPU rate control"),
        ("整机暂停阈值", "CPU超过50%持续10秒", "psutil采样后暂停后台工作"),
        ("整机恢复阈值", "CPU低于30%持续10秒", "自动恢复队列"),
        ("内存保护", "系统使用率超过70%", "暂停新任务并释放临时对象"),
        ("磁盘保护", "剩余低于10GB", "停止新导入并提示清理"),
    ], [4.0, 4.3, 7.7], 8.4)

    add_heading(doc, "安全设计", 1)
    add_bullets(doc, [
        "本地服务只绑定127.0.0.1，并在浏览器会话中使用随机本地令牌。",
        "API Key不写入SQLite明文字段，使用Windows DPAPI或系统凭据库。",
        "模型请求经过统一外发拦截器；严格离线模式在此层直接拒绝请求。",
        "日志保存请求摘要和证据编号，不默认保存完整敏感正文。",
        "远端文件在任务完成后主动删除，并记录删除是否成功。",
        "导出文件包含生成时间、风险快照和模型来源，但不包含隐藏推理内容。",
    ])

    add_heading(doc, "部署目录", 1)
    add_table(doc, ["目录", "内容", "备份要求"], [
        ("data/app.db", "SQLite元数据、任务和审计日志", "必须"),
        ("data/analytics", "DuckDB项目分析库", "必须"),
        ("data/files", "原始PDF和用户附件", "必须"),
        ("data/derived", "OCR结果、缩略图、解析JSON和向量索引", "建议"),
        ("data/templates", "Word和Excel模板", "必须"),
        ("data/exports", "历史生成结果", "按项目策略"),
        ("data/temp", "逐页图片和临时响应", "不备份，启动时清理"),
    ], [4.0, 7.8, 4.2], 8.5)

    doc.add_page_break()
    add_heading(doc, "技术风险和处置", 1)
    add_table(doc, ["风险", "影响", "处置"], [
        ("视觉模型数字误识别", "金额和表格不可靠", "本地勾稽、第二模型复核、人工校正和来源页保留"),
        ("供应商接口变化", "模型调用失败", "能力注册表、适配器隔离、用户可改Base URL和模型名"),
        ("11年样本过少", "统计误报", "MAD、规则、趋势和审计判断组合，不让Z-score单独定级"),
        ("API数据外发", "涉密和合规风险", "最小证据、外发日志、项目策略和严格离线模式"),
        ("SQLite单写限制", "批量任务竞争", "单工作器和短事务，避免并行写"),
        ("轻薄本资源波动", "影响用户日常办公", "硬上限、整机阈值、空闲优先和可暂停任务"),
    ], [4.2, 4.4, 7.4], 8.4)
    return save(doc, "02_AI财务审计分析平台_MVP技术架构设计说明书.docx")


def build_open_source():
    doc = setup_doc(
        "AI财务审计平台 开源选型与许可评估",
        "GitHub 社区采用度 活跃度 可复用边界",
        "本文档列出MVP可直接采用或用于架构借鉴的GitHub项目。主清单以GitHub Stars约2000以上、仓库未归档、近期仍更新且许可证可核查为门槛。Stars为2026年9月19日附近的快照，会随时间变化。",
        "开源项目选型与许可证评估",
    )
    add_heading(doc, "评审结论", 1)
    add_para(doc, "正式MVP不应fork一个通用AI平台直接改造。建议采用轻量库组合，自研审计风险工作台；RAGFlow、Dify、PaddleOCR等大型项目用于借鉴文档解析、工作流和引用设计，FinGPT、FinRobot、OpenBB等财务项目用于借鉴数据接口、任务拆分和评测方法，均不作为轻薄本的整套运行时依赖。")
    add_table(doc, ["类别", "结论"], [
        ("正式依赖", "React、FastAPI、PDF.js、DuckDB、SQLite生态、LiteLLM SDK和文档导出库"),
        ("可选依赖", "PyOD、River、ECharts和Splink按MVP数据质量决定"),
        ("架构借鉴", "RAGFlow、Dify、FastGPT、PaddleOCR、MinerU、Docling、LangGraph及财务领域项目"),
        ("不建议直接引入", "服务器级知识库全套、独立向量数据库、Docker编排和本地大模型"),
    ], [3.6, 12.4])

    add_heading(doc, "正式依赖候选", 1)
    primary = [
        ("react/react", "约250.6k", "MIT", "前端组件体系", "采用"),
        ("fastapi/fastapi", "约102.5k", "MIT", "本地HTTP API和流式接口", "采用"),
        ("Kludex/uvicorn", "约11.0k", "BSD-3-Clause", "FastAPI本地服务器", "采用"),
        ("mozilla/pdf.js", "约53.9k", "Apache-2.0", "PDF阅读、页码跳转、搜索和高亮", "采用"),
        ("duckdb/duckdb", "约41.6k", "MIT", "多年财务数据进程内分析", "采用"),
        ("asg017/sqlite-vec", "约8.1k", "Apache-2.0", "SQLite内向量检索", "采用前做Windows兼容验证"),
        ("BerriAI/litellm", "约59.2k", "核心MIT，enterprise目录另行许可", "多模型SDK、错误归一和备用路由", "采用SDK，不部署Proxy"),
        ("py-pdf/pypdf", "约10.2k", "BSD-3-Clause", "PDF拆分、页处理和元数据", "采用"),
        ("jsvine/pdfplumber", "约10.8k", "MIT", "原生PDF文本、坐标和表格候选", "采用"),
        ("apache/echarts", "约67.4k", "Apache-2.0", "11年趋势和风险时间轴", "采用精简组件"),
        ("giampaolo/psutil", "约11.3k", "BSD-3-Clause", "整机CPU和内存监测", "采用"),
        ("python-openxml/python-docx", "约5.7k", "MIT", "Word内容和简单模板处理", "采用"),
        ("elapouya/python-docx-template", "约2.7k", "LGPL-2.1", "固定Word模板填充", "条件采用并保留动态链接边界"),
        ("yzhao062/pyod", "约10.0k", "BSD-2-Clause", "表格型异常检测算法", "可选"),
        ("online-ml/river", "约6.1k", "BSD-3-Clause", "增量统计和在线模型", "二期可选"),
    ]
    add_table(doc, ["GitHub项目", "Stars", "许可证", "用途", "建议"], primary, [4.0, 2.0, 2.8, 5.3, 2.4], 7.7)

    add_heading(doc, "重点架构借鉴项目", 1)
    refs = [
        ("langgenius/dify", "约156.5k", "修改版Apache-2.0", "模型配置、工作流、可观测性", "只借鉴，不复用前端；多租户和品牌条款需注意"),
        ("infiniflow/ragflow", "约91.0k", "Apache-2.0", "文档切片、混合检索、引用可视化", "借鉴证据链；完整部署不适合轻薄本"),
        ("labring/FastGPT", "约29.7k", "修改版Apache-2.0", "知识库问答、工作流和模型配置", "只借鉴交互与流程；发布前逐条复核附加条款"),
        ("1Panel-dev/MaxKB", "约22.8k", "GPL-3.0", "知识库问答、应用编排和文档管理", "只借鉴产品结构，不作为闭源MVP核心依赖"),
        ("PaddlePaddle/PaddleOCR", "约89.9k", "Apache-2.0", "中文OCR、版面、表格和坐标", "作为未来本地OCR降级方案"),
        ("opendatalab/MinerU", "约80.3k", "Apache附加条款", "复杂PDF转Markdown和JSON", "借鉴解析接口，商用前复核附加条款"),
        ("docling-project/docling", "约67.1k", "MIT", "文档结构化和多格式抽取", "借鉴统一文档对象模型"),
        ("langchain-ai/langgraph", "约42.0k", "MIT", "暂停恢复、人工介入和持久工作流", "借鉴状态机；MVP用更轻的自研任务表"),
        ("qdrant/qdrant", "约34.7k", "Apache-2.0", "向量检索、过滤和索引", "数据量超SQLite能力后再迁移"),
        ("fivetran/great_expectations", "约11.8k", "Apache-2.0", "数据质量规则和验证报告", "借鉴规则版本和验证结果结构"),
        ("moj-analytical-services/splink", "约2.4k", "MIT", "跨系统实体模糊匹配", "二期用于客户供应商和合同关联"),
    ]
    add_table(doc, ["GitHub项目", "Stars", "许可证", "借鉴内容", "使用边界"], refs, [4.1, 2.0, 2.7, 4.6, 4.1], 7.55)

    add_heading(doc, "财务领域借鉴项目", 1)
    finance_refs = [
        ("anthropics/financial-services", "约35.2k", "Apache-2.0", "财务分析、GL对账和人工复核工作流", "最接近本项目场景；借鉴任务拆分、证据链和人审边界，不绑定Claude"),
        ("AI4Finance-Foundation/FinGPT", "约21.3k", "MIT", "金融语料、情绪分析、评测和数据适配", "偏投研与模型训练；MVP只借鉴数据标准和评测方法，不部署本地模型"),
        ("AI4Finance-Foundation/FinRobot", "约8.0k", "Apache-2.0", "财务Agent、研究流程和报告生成", "偏投研场景；借鉴任务编排、工具调用和人工复核节点"),
        ("OpenBB-finance/OpenBB", "约73.3k", "AGPL-3.0", "金融数据连接器、标准化接口和可追溯来源", "偏市场数据；强Copyleft，不作为闭源MVP核心依赖"),
        ("microsoft/qlib", "约48.7k", "MIT", "时序数据、实验管理和可重复评测", "偏量化投资；借鉴数据版本、指标基线和回测式验收"),
        ("virattt/ai-hedge-fund", "约63.6k", "MIT", "多Agent角色分工、路由和结果汇总", "演示与投研属性较强；只借鉴轻量编排，不采用其投资判断逻辑"),
    ]
    add_table(doc, ["GitHub项目", "Stars", "许可证", "可借鉴内容", "使用边界"], finance_refs, [4.2, 2.0, 2.6, 4.8, 3.9], 7.45)

    add_heading(doc, "许可证判断", 1)
    add_table(doc, ["许可证类型", "本项目处理"], [
        ("MIT BSD Apache-2.0", "通常可用于商业和内部项目，但必须保留版权和许可证文本，并完成依赖清单。"),
        ("LGPL-2.1", "优先作为独立Python依赖使用，不复制其源码进入自有模块；发布前由法务复核。"),
        ("GPL-3.0或AGPL-3.0", "不作为MVP核心依赖，避免分发或网络服务场景下产生源代码开放义务。"),
        ("修改版Apache或附加条款", "不得按普通Apache处理；使用前逐条审阅多租户、品牌、收入门槛和署名要求。"),
        ("企业目录双许可", "只使用明确处于开源许可证范围内的核心代码，禁止复制enterprise目录。"),
    ], [4.4, 11.6], 8.7)

    add_heading(doc, "不采用完整平台的原因", 1)
    add_bullets(doc, [
        "RAGFlow、Dify和FastGPT需要多个常驻服务，增加内存、磁盘和升级成本。",
        "通用聊天平台缺少风险状态、证据反证、财务规则版本和固定审计模板。",
        "直接改造大型前端会把大量无关功能带入单人MVP。",
        "修改版许可证可能限制多租户、品牌移除或商业交付。",
        "轻量库组合更容易执行CPU硬上限、严格离线模式和外发数据审计。",
    ])

    add_heading(doc, "选型落地顺序", 1)
    add_numbered(doc, [
        "先验证FastAPI、SQLite、DuckDB和PDF.js的单机闭环。",
        "接入LiteLLM SDK并完成DeepSeek、GLM、Kimi和千问的文本调用兼容测试。",
        "分别验证四家视觉接口、JSON输出、文件删除和异常处理。",
        "验证sqlite-vec在Windows打包环境中的安装和索引性能；失败时回退为纯FTS5加内存余弦检索。",
        "在真实脱敏样本上比较pdfplumber本地抽取与视觉模型识别准确率。",
        "完成许可证归档、第三方声明和版本锁定后再进入发布。",
    ])

    doc.add_page_break()
    add_heading(doc, "项目链接", 1)
    links = [
        ("React", "https://github.com/facebook/react"),
        ("FastAPI", "https://github.com/fastapi/fastapi"),
        ("PDF.js", "https://github.com/mozilla/pdf.js"),
        ("DuckDB", "https://github.com/duckdb/duckdb"),
        ("sqlite-vec", "https://github.com/asg017/sqlite-vec"),
        ("LiteLLM", "https://github.com/BerriAI/litellm"),
        ("RAGFlow", "https://github.com/infiniflow/ragflow"),
        ("Dify", "https://github.com/langgenius/dify"),
        ("FastGPT", "https://github.com/labring/FastGPT"),
        ("MaxKB", "https://github.com/1Panel-dev/MaxKB"),
        ("PaddleOCR", "https://github.com/PaddlePaddle/PaddleOCR"),
        ("MinerU", "https://github.com/opendatalab/MinerU"),
        ("Docling", "https://github.com/docling-project/docling"),
        ("LangGraph", "https://github.com/langchain-ai/langgraph"),
        ("PyOD", "https://github.com/yzhao062/pyod"),
        ("Anthropic Financial Services", "https://github.com/anthropics/financial-services"),
        ("FinGPT", "https://github.com/AI4Finance-Foundation/FinGPT"),
        ("FinRobot", "https://github.com/AI4Finance-Foundation/FinRobot"),
        ("OpenBB", "https://github.com/OpenBB-finance/OpenBB"),
        ("Qlib", "https://github.com/microsoft/qlib"),
        ("AI Hedge Fund", "https://github.com/virattt/ai-hedge-fund"),
    ]
    for label, url in links:
        add_source_link(doc, label, url)
    return save(doc, "03_AI财务审计分析平台_开源项目选型与许可证评估.docx")


def build_plan():
    doc = setup_doc(
        "AI财务审计平台 MVP 开发与验收计划",
        "迭代顺序 测试矩阵 发布条件",
        "本文档将产品和技术要求拆成可执行迭代，并给出功能、性能、安全和模型兼容验收标准。计划假设由一名具备Python和React经验的全栈开发人员主导，内部审计人员持续提供样本和业务验收。",
        "开发计划与验收标准",
    )
    add_heading(doc, "开发原则", 1)
    add_bullets(doc, [
        "先完成本地证据闭环，再增加AI解释。",
        "每个模型调用都必须可替换、可缓存、可追踪和可重试。",
        "每个金额结论都必须能由本地代码复算。",
        "每个迭代都在16GB基准轻薄本上执行性能测试。",
        "真实资料测试前先使用脱敏或合成样本。",
    ])

    add_heading(doc, "计划假设", 1)
    add_table(doc, ["项目", "假设"], [
        ("团队", "一名全栈开发人员加一名兼职审计业务验收人员"),
        ("周期", "建议10至14周；接口和真实样本质量会影响工期"),
        ("设备", "Windows 10或11，4核8线程以上，16GB内存，SSD"),
        ("数据", "MVP以PDF为主，提供至少三组脱敏测试资料"),
        ("模型", "至少准备两家文本模型和一家视觉模型API账号"),
        ("交付", "原生Windows安装包、用户手册、第三方声明和测试报告"),
    ], [3.8, 12.2])

    add_heading(doc, "迭代计划", 1)
    phases = [
        ("迭代零", "工程和基准", "项目结构、SQLite迁移、配置、日志、安装验证、性能采样", "可启动空应用并记录资源基线"),
        ("迭代一", "文档工作区", "项目、批量上传、哈希去重、PDF.js、页码跳转、任务状态", "原生PDF可导入查看和恢复"),
        ("迭代二", "多模型网关", "服务商配置、密钥、文本视觉能力、路由、重试、缓存、用量", "两家文本模型和一家视觉模型通过"),
        ("迭代三", "解析和检索", "原生PDF抽取、扫描页视觉识别、FTS5、Embedding、sqlite-vec", "从问题跳转到证据页"),
        ("迭代四", "异常和风险", "DuckDB指标、MAD和趋势、风险卡片、状态、证据、增量更新", "真实样本形成可复核风险"),
        ("迭代五", "访谈和报告", "资料清单、访谈问题、模板编辑、Word Excel PDF导出", "风险状态与导出一致"),
        ("迭代六", "资源和发布", "CPU硬上限、整机暂停、离线模式、安全测试、安装包和文档", "全部验收项通过"),
    ]
    add_table(doc, ["阶段", "主题", "主要工作", "阶段出口"], phases, [2.2, 3.2, 7.4, 3.2], 8.15)

    add_heading(doc, "开发工作分解", 1)
    wbs = [
        ("前端", "五个标签页、项目切换、模型设置、进度、风险卡片、备忘录、PDF弹窗"),
        ("后端", "本地API、SSE进度、文件服务、输入校验、异常处理和导出"),
        ("任务", "单工作器、持久状态、安全点、暂停继续、重试和清理"),
        ("PDF", "类型检测、文本层、本地抽取、逐页渲染、页码和证据"),
        ("模型", "LiteLLM封装、厂商适配器、能力表、外发拦截器和缓存"),
        ("检索", "FTS5、Embedding、向量索引、元数据过滤、融合排序"),
        ("分析", "标准科目、年度指标、规则、MAD、趋势和风险等级"),
        ("报告", "模板字段、预览、人工编辑、Word Excel PDF和历史记录"),
        ("安全", "密钥加密、回环绑定、外发日志、文件删除和离线模式"),
        ("性能", "Job Object、psutil监控、DuckDB上限、压力测试和降速"),
    ]
    add_table(doc, ["工作包", "内容"], wbs, [3.2, 12.8], 8.7)

    add_heading(doc, "测试数据集", 1)
    add_table(doc, ["数据集", "最低内容", "用途"], [
        ("A 原生报告", "3个年度原生PDF，含报表、附注和可复制文字", "页码、文本、表格、检索和高亮"),
        ("B 扫描报告", "100页扫描PDF，含表格、印章、倾斜页和低清页", "视觉识别、失败处理和人工校正"),
        ("C 多年财务", "11年科目数据和已知异常清单", "历史基线、MAD、趋势和误报分析"),
        ("D 增量证据", "能够支持或推翻已有风险的新合同或纪要", "受影响风险重算和版本差异"),
        ("E API故障", "超时、429、余额不足、无效JSON和服务不可用", "重试、备用模型和人工跳过"),
        ("F 大批量", "500个PDF或等量合成文件", "队列、恢复、磁盘和性能保护"),
    ], [3.2, 7.8, 5.0], 8.4)

    add_heading(doc, "功能验收矩阵", 1)
    functional = [
        ("F01", "批量导入", "导入50个PDF，其中2个损坏", "48个进入处理，2个报错且整批继续"),
        ("F02", "增量去重", "重复上传同一文件", "命中哈希并复用结果，不重复调用API"),
        ("F03", "暂停恢复", "解析中暂停并重启应用", "任务保持暂停，继续后从安全点执行"),
        ("F04", "模型切换", "切换两家OpenAI兼容服务商", "无需改代码即可完成问答"),
        ("F05", "能力路由", "默认文本模型不支持图片", "自动使用视觉模型并标明实际模型"),
        ("F06", "原生PDF证据", "点击风险证据", "PDF弹窗打开到准确页码并搜索到原文"),
        ("F07", "扫描PDF证据", "点击扫描件证据", "至少打开到准确页码"),
        ("F08", "本地计算", "抽查10个金额指标", "与独立脚本复算一致"),
        ("F09", "风险状态", "修改为已核实或排除", "列表、详情和导出同步更新"),
        ("F10", "增量回溯", "加入推翻旧风险的新证据", "只重算相关风险并保留旧版本"),
        ("F11", "报告导出", "导出三种格式", "内容可打开、字段完整、证据引用存在"),
        ("F12", "离线模式", "启用离线后执行AI任务", "请求被阻止并给出明确提示"),
    ]
    add_table(doc, ["编号", "能力", "测试", "通过条件"], functional, [1.5, 3.2, 5.2, 6.1], 8.0)

    add_heading(doc, "性能验收", 1)
    perf = [
        ("P01", "空闲资源", "启动10分钟后", "后端及索引服务内存不高于2.5GB，CPU均值低于5%"),
        ("P02", "本地解析", "连续处理原生PDF", "应用CPU持续均值不高于35%，短时峰值不高于45%"),
        ("P03", "整机保护", "人为制造整机CPU超过50%", "10秒内暂停后台任务，低于30%后恢复"),
        ("P04", "内存保护", "系统内存超过70%", "不启动新任务并显示等待原因"),
        ("P05", "长任务恢复", "批量任务中强制退出", "重启后已完成步骤不重复"),
        ("P06", "交互响应", "后台处理时浏览风险和PDF", "常用操作无持续卡顿，后台自动降速"),
        ("P07", "磁盘保护", "剩余空间低于10GB", "停止新导入且不破坏已有项目"),
    ]
    add_table(doc, ["编号", "测试项", "条件", "通过标准"], perf, [1.5, 3.4, 5.1, 6.0], 8.0)

    add_heading(doc, "模型兼容验收", 1)
    add_table(doc, ["能力", "最低覆盖", "验证内容"], [
        ("文本", "DeepSeek GLM Kimi 千问中任意两家", "流式和非流式、超时、Token用量和错误归一"),
        ("视觉", "任意两家视觉模型", "单页、密集表格、低清页、JSON输出和页码绑定"),
        ("结构化输出", "至少两家", "Schema验证、无效JSON修复和失败回退"),
        ("Embedding", "至少一家", "向量维度、批量调用、缓存和索引版本"),
        ("备用路由", "至少一主一备", "限流、超时和服务不可用时切换"),
        ("文件生命周期", "支持文件接口的服务商", "上传、到期设置、主动删除和删除日志"),
    ], [3.2, 5.3, 7.5], 8.4)

    add_heading(doc, "安全验收", 1)
    add_bullets(doc, [
        "本地端口不能从局域网其他设备访问。",
        "SQLite、日志、崩溃报告和导出文件中不出现明文API Key。",
        "严格离线模式通过网络抓包验证无外部请求。",
        "外发日志能对应到项目、文档页码、模型和时间。",
        "远端文件删除失败会进入重试队列并提示用户。",
        "删除项目必须二次确认，并优先提供可恢复的回收站策略。",
    ])

    add_heading(doc, "发布条件", 1)
    add_numbered(doc, [
        "所有P0功能验收通过，无阻塞级缺陷。",
        "性能验收P01至P07全部通过，并附基准设备信息。",
        "至少两家文本模型和两家视觉模型完成兼容测试。",
        "第三方许可证、版本、源码地址和版权声明归档完成。",
        "安装、升级、备份、恢复和卸载流程均完成一次实机演练。",
        "使用真实资料前，用户已确认外部API数据处理政策和项目敏感等级。",
        "审计人员完成风险清单、证据跳转、访谈提纲和报告导出的业务验收。",
    ])

    doc.add_page_break()
    add_heading(doc, "交付清单", 1)
    add_table(doc, ["交付物", "内容"], [
        ("Windows安装包", "应用程序、运行时和卸载程序"),
        ("配置说明", "模型服务商、密钥、存储路径和资源上限"),
        ("用户手册", "项目、上传、分析、复核、导出、备份和离线模式"),
        ("测试报告", "功能、模型兼容、性能、安全和恢复结果"),
        ("第三方声明", "依赖名称、版本、许可证、源码地址和修改说明"),
        ("数据字典", "SQLite表、DuckDB表、字段和索引"),
        ("接口文档", "本地API、模型适配器和导出接口"),
        ("模板包", "风险清单、管理层材料和证据包模板"),
    ], [4.0, 12.0], 8.6)
    return save(doc, "04_AI财务审计分析平台_MVP开发计划与验收标准.docx")


if __name__ == "__main__":
    paths = [build_prd(), build_architecture(), build_open_source(), build_plan()]
    for path in paths:
        print(path)
