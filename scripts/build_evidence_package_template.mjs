import fs from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { SpreadsheetFile, Workbook } from '@oai/artifact-tool'

const outputPath = new URL('../templates/evidence-package-excel-v1.xlsx', import.meta.url)
const outputFile = fileURLToPath(outputPath)
const workbook = Workbook.create()
const fontFamily = 'Arial'
const navy = '#17365D'
const paleBlue = '#EAF1F8'
const border = '#D9D9D9'
const text = '#1F2937'

function styleBase(sheet, range) {
  const body = sheet.getRange(range)
  body.format.font = { name: fontFamily, size: 10, color: text }
  body.format.verticalAlignment = 'center'
  sheet.showGridLines = false
}

function styleHeader(sheet, range) {
  const header = sheet.getRange(range)
  header.format = {
    fill: navy,
    font: { name: fontFamily, size: 10, bold: true, color: '#FFFFFF' },
    horizontalAlignment: 'center',
    verticalAlignment: 'center',
    wrapText: true,
    borders: { preset: 'all', style: 'thin', color: border },
  }
  header.format.rowHeight = 30
}

function styleTemplateRow(sheet, range) {
  const row = sheet.getRange(range)
  row.format = {
    fill: '#FFFFFF',
    font: { name: fontFamily, size: 10, color: text },
    verticalAlignment: 'center',
    wrapText: true,
    borders: { preset: 'all', style: 'thin', color: border },
  }
  row.format.rowHeight = 42
}

const cover = workbook.worksheets.add('证据包说明')
cover.getRange('A1').values = [['审计证据包索引']]
cover.getRange('A1:F1').format.font = { name: fontFamily, size: 16, bold: true, color: text }
cover.getRange('A1:F1').format.rowHeight = 30
cover.getRange('A2:F6').values = [
  ['项目名称', '{{project_name}}', '', '模板版本', '{{template_version}}', ''],
  ['审计主体', '{{entity_name}}', '', '审计期间', '{{audit_period}}', ''],
  ['源快照', '{{snapshot_id}}', '', '最终草稿', '{{draft_version}}', ''],
  ['内容摘要', '{{content_sha256}}', '', '生成时间', '{{generated_at}}', ''],
  ['风险数量', '{{risk_count}}', '', '证据数量', '{{evidence_count}}', ''],
]
styleBase(cover, 'A1:F10')
cover.getRange('A2:A6').format = { fill: paleBlue, font: { name: fontFamily, size: 10, bold: true, color: text } }
cover.getRange('D2:D6').format = { fill: paleBlue, font: { name: fontFamily, size: 10, bold: true, color: text } }
cover.getRange('A2:F6').format.borders = { preset: 'all', style: 'thin', color: border }
cover.getRange('A2:F6').format.wrapText = true
cover.getRange('A8').values = [['本文件仅保存快照中已锁定的风险与证据索引，不复制原始证据文件，也不替代原始文件保管。']]
cover.mergeCells('A8:F8')
cover.getRange('A8:F8').format = { font: { name: fontFamily, size: 10, italic: true, color: '#4E5B6C' }, wrapText: true }
cover.getRange('A8:F8').format.rowHeight = 48
cover.getRange('A:F').format.columnWidth = 18
cover.getRange('A:A').format.columnWidth = 15
cover.getRange('B:C').format.columnWidth = 26
cover.getRange('D:D').format.columnWidth = 15
cover.getRange('E:F').format.columnWidth = 26
cover.freezePanes.freezeRows(1)
cover.tabColor = navy

const risks = workbook.worksheets.add('风险索引')
risks.getRange('A1:G5').values = [
  ['审计证据包风险索引', '', '', '', '', '', ''],
  ['项目名称', '{{project_name}}', '', '模板版本', '{{template_version}}', '', ''],
  ['审计主体', '{{entity_name}}', '', '审计期间', '{{audit_period}}', '', ''],
  ['源快照', '{{snapshot_id}}', '', '生成时间', '{{generated_at}}', '', ''],
  ['内容摘要', '{{content_sha256}}', '', '风险数量', '{{risk_count}}', '', ''],
]
risks.getRange('A7:G7').values = [[
  '风险编号', '风险版本', '状态', '风险等级', '风险标题', '支持证据', '反证',
]]
risks.getRange('A8:G8').values = [['', '', '', '', '', '', '']]
for (const row of [2, 3, 4, 5]) {
  risks.mergeCells(`B${row}:C${row}`)
  risks.mergeCells(`E${row}:G${row}`)
}
styleBase(risks, 'A1:G8')
risks.getRange('A2:G5').format.wrapText = true
risks.getRange('A4:G4').format.rowHeight = 30
risks.getRange('A5:G5').format.rowHeight = 42
risks.getRange('A1:G1').format.font = { name: fontFamily, size: 14, bold: true, color: text }
styleHeader(risks, 'A7:G7')
styleTemplateRow(risks, 'A8:G8')
risks.getRange('A:A').format.columnWidth = 14
risks.getRange('B:D').format.columnWidth = 12
risks.getRange('E:E').format.columnWidth = 36
risks.getRange('F:G').format.columnWidth = 24
risks.freezePanes.freezeRows(7)
risks.tabColor = '#4F81BD'

const evidence = workbook.worksheets.add('证据索引')
evidence.getRange('A1:Q5').values = [
  ['审计证据包证据索引', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', ''],
  ['项目名称', '{{project_name}}', '', '模板版本', '{{template_version}}', '', '', '', '', '', '', '', '', '', '', '', ''],
  ['审计主体', '{{entity_name}}', '', '审计期间', '{{audit_period}}', '', '', '', '', '', '', '', '', '', '', '', ''],
  ['源快照', '{{snapshot_id}}', '', '生成时间', '{{generated_at}}', '', '', '', '', '', '', '', '', '', '', '', ''],
  ['内容摘要', '{{content_sha256}}', '', '证据数量', '{{evidence_count}}', '', '', '', '', '', '', '', '', '', '', '', ''],
]
evidence.getRange('A7:Q7').values = [[
  '证据编号', '风险编号', '方向', '来源类型', '来源定位', '原文引用', '解析方式', '解析版本',
  '源证据 ID', '文档 ID', '数据集 ID', '页码', '块序号', '起始行', '结束行', '期间', '科目编码',
]]
evidence.getRange('A8:Q8').values = [[
  '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '',
]]
for (const row of [2, 3, 4, 5]) {
  evidence.mergeCells(`B${row}:C${row}`)
  evidence.mergeCells(`E${row}:H${row}`)
}
styleBase(evidence, 'A1:Q8')
evidence.getRange('A2:Q5').format.wrapText = true
evidence.getRange('A4:Q4').format.rowHeight = 30
evidence.getRange('A5:Q5').format.rowHeight = 42
evidence.getRange('A1:Q1').format.font = { name: fontFamily, size: 14, bold: true, color: text }
styleHeader(evidence, 'A7:Q7')
styleTemplateRow(evidence, 'A8:Q8')
evidence.getRange('A:D').format.columnWidth = 13
evidence.getRange('E:E').format.columnWidth = 30
evidence.getRange('F:F').format.columnWidth = 42
evidence.getRange('G:H').format.columnWidth = 14
evidence.getRange('I:K').format.columnWidth = 24
evidence.getRange('L:Q').format.columnWidth = 12
evidence.freezePanes.freezeRows(7)
evidence.tabColor = '#95B3D7'

workbook.recalculate()
const output = await SpreadsheetFile.exportXlsx(workbook)
await output.save(outputFile)
await fs.rm(`${outputFile}.inspect.ndjson`, { force: true })
