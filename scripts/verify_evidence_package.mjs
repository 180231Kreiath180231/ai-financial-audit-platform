import fs from 'node:fs/promises'
import path from 'node:path'
import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool'

const [inputPath, outputDir] = process.argv.slice(2)
if (!inputPath || !outputDir) {
  throw new Error('Usage: node verify_evidence_package.mjs <input.xlsx> <output-dir>')
}

await fs.mkdir(outputDir, { recursive: true })
const input = await FileBlob.load(inputPath)
const workbook = await SpreadsheetFile.importXlsx(input)
workbook.recalculate()

const checks = []
for (const [sheetName, range, slug] of [
  ['证据包说明', 'A1:F8', 'cover'],
  ['风险索引', 'A1:G8', 'risks'],
  ['证据索引', 'A1:Q9', 'evidence'],
]) {
  const inspection = await workbook.inspect({
    kind: 'table',
    range: `${sheetName}!${range}`,
    include: 'values,formulas',
    tableMaxRows: 12,
    tableMaxCols: 20,
    maxChars: 8000,
  })
  checks.push(inspection.ndjson)
  const preview = await workbook.render({ sheetName, range, scale: 1.5, format: 'png' })
  await fs.writeFile(path.join(outputDir, `${slug}.png`), new Uint8Array(await preview.arrayBuffer()))
}

const errors = await workbook.inspect({
  kind: 'match',
  searchTerm: '#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',
  options: { useRegex: true, maxResults: 300 },
  summary: 'final formula error scan',
})

console.log(checks.join('\n'))
console.log(errors.ndjson)
