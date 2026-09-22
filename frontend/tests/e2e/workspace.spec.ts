import { expect, test } from '@playwright/test'

function syntheticTextPdf(text: string): Buffer {
  const stream = `BT /F1 18 Tf 72 720 Td (${text}) Tj ET`
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>',
    `<< /Length ${Buffer.byteLength(stream)} >>\nstream\n${stream}\nendstream`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
  ]
  let pdf = '%PDF-1.4\n'
  const offsets = [0]
  objects.forEach((body, index) => {
    offsets.push(Buffer.byteLength(pdf))
    pdf += `${index + 1} 0 obj\n${body}\nendobj\n`
  })
  const xrefOffset = Buffer.byteLength(pdf)
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`
  pdf += offsets.slice(1).map((offset) => `${offset.toString().padStart(10, '0')} 00000 n \n`).join('')
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`
  return Buffer.from(pdf)
}

test('loads the local-first project workspace', async ({ page }) => {
  await page.goto('/')
  if (test.info().project.name === 'mobile') {
    await page.getByRole('navigation', { name: '项目工作区' }).getByRole('button', { name: '资料' }).click()
  }
  await expect(page.getByRole('heading', { name: '项目资料' })).toBeVisible()
  await expect(page.getByText('合成演示项目')).toBeVisible()
  await expect(page.getByRole('button', { name: '选择 PDF' })).toBeVisible()

  if (test.info().project.name === 'desktop') {
    await expect(page.getByText('严格离线', { exact: true }).first()).toBeVisible()
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
    await page.getByRole('button', { name: '切换为浅色主题' }).click()
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
  }
})

test('imports a synthetic PDF and jumps to a matching evidence page', async ({ page }) => {
  test.skip(test.info().project.name !== 'desktop', 'desktop acceptance path')
  await page.goto('/')

  await page.locator('input[type="file"]').setInputFiles({
    name: 'playwright-evidence.pdf',
    mimeType: 'application/pdf',
    buffer: syntheticTextPdf('AUDIT-EVIDENCE-2025'),
  })
  await expect(page.getByRole('status')).toContainText('1 个 PDF 已进入本地任务队列')
  const documentList = page.getByLabel('已导入文档')
  const documentRow = documentList.getByRole('button', { name: /playwright-evidence\.pdf/ })
  await expect(documentRow).toBeVisible({
    timeout: 20_000,
  })

  await documentRow.click()
  await expect(page.getByRole('region', { name: /playwright-evidence\.pdf 阅读器/ })).toBeVisible()
  await page.getByRole('textbox', { name: '搜索文档原文' }).fill('AUDIT-EVIDENCE-2025')
  await page.getByRole('button', { name: '查找' }).click()
  await expect(page.getByRole('button', { name: /第 1 页/ })).toBeVisible()
  await page.getByRole('button', { name: /第 1 页/ }).click()
  await expect(page.getByLabel('页码')).toHaveValue('1')
})

test('mobile workspace exposes all three panes', async ({ page }) => {
  test.skip(test.info().project.name !== 'mobile', 'mobile-only assertion')
  await page.goto('/')
  const switcher = page.getByRole('navigation', { name: '项目工作区' })
  await expect(switcher.getByRole('button', { name: '资料' })).toBeVisible()
  await switcher.getByRole('button', { name: '处置' }).click()
  const decisionPanel = page.getByRole('complementary', { name: '复核与处置面板' })
  await expect(decisionPanel).toBeVisible()
  await expect(decisionPanel.getByRole('button', { name: '判断依据' })).toBeVisible()
})
