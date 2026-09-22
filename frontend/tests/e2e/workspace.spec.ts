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

test('creates and reviews a versioned risk from resolved evidence', async ({ page }) => {
  test.skip(test.info().project.name !== 'desktop', 'desktop risk acceptance path')
  await page.goto('/')

  await page.locator('input[type="file"]').setInputFiles({
    name: 'playwright-risk-evidence.pdf',
    mimeType: 'application/pdf',
    buffer: syntheticTextPdf('RISK-EVIDENCE-LOCAL-ONLY'),
  })
  const documentList = page.getByLabel('已导入文档')
  const documentRow = documentList.getByRole('button', { name: /playwright-risk-evidence\.pdf/ })
  await expect(documentRow).toBeVisible({ timeout: 20_000 })
  await documentRow.click()

  await page.getByRole('textbox', { name: '搜索文档原文' }).fill('RISK-EVIDENCE-LOCAL-ONLY')
  await page.getByRole('button', { name: '查找' }).click()
  await page.getByRole('button', { name: '支持证据' }).click()

  const decisionPanel = page.getByRole('complementary', { name: '复核与处置面板' })
  await expect(decisionPanel.getByRole('heading', { name: '证据草稿（1）' })).toBeVisible()
  await decisionPanel.getByRole('button', { name: '人工处置' }).click()
  await decisionPanel.getByLabel('风险摘要').fill('核对本地合成证据对应事项')
  await decisionPanel.getByRole('button', { name: '创建风险草稿' }).click()

  await expect(page.getByRole('heading', { name: '风险台账' })).toBeVisible()
  await expect(page.getByText('R-0001', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('RISK-EVIDENCE-LOCAL-ONLY')).toBeVisible()
  await page.getByRole('button', { name: '生成合成解释草稿' }).click()
  await expect(page.getByRole('status')).toContainText('外部请求 0 次')
  await expect(page.getByText(/^合成解释草稿：/)).toBeVisible()

  await page.getByLabel('复核备注').fill('已核对合成原文与页码')
  await page.getByRole('button', { name: '转为已核实' }).click()
  await expect(page.getByRole('status')).toContainText('已转为“已核实”')
  await expect(page.getByText('v3', { exact: true }).first()).toBeVisible()

  await page.getByRole('button', { name: /playwright-risk-evidence\.pdf · 第 1 页/ }).click()
  await expect(page.getByRole('region', { name: /playwright-risk-evidence\.pdf 阅读器/ })).toBeVisible()
  await expect(page.getByLabel('页码')).toHaveValue('1')
  await expect(page.getByRole('button', { name: '支持证据' })).toBeVisible()
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

test('settings exposes audited local model routing without external requests', async ({ page }) => {
  test.skip(test.info().project.name !== 'desktop', 'desktop settings acceptance path')
  await page.goto('/')

  await page.getByRole('navigation', { name: '主功能' }).getByRole('button', { name: '设置' }).click()
  await expect(page.getByRole('heading', { name: '模型与外发设置' })).toBeVisible()
  await expect(page.getByText('严格离线', { exact: true }).first()).toBeVisible()
  await expect(page.getByRole('button', { name: '授权当前项目' })).toBeDisabled()
  await page.getByRole('button', { name: '运行本地自检' }).click()
  await expect(page.getByRole('status')).toContainText('外部请求 0 次')

  const providers = page.getByRole('region', { name: '服务商' })
  await providers.getByLabel('显示名称').fill('Synthetic E2E Provider')
  await providers.getByLabel(/Base URL/).fill('https://models.invalid/v1')
  await providers.getByRole('button', { name: '保存服务商' }).click()
  const providerRow = providers.locator('article').filter({ hasText: 'Synthetic E2E Provider' })
  await expect(providerRow).toBeVisible()
  await providerRow.getByRole('button', { name: '编辑' }).click()
  await expect(providers.getByText('编辑 OpenAI-compatible 服务商')).toBeVisible()
  await providers.getByLabel('显示名称').fill('Synthetic E2E Provider Updated')
  await providers.getByRole('button', { name: '保存修改' }).click()
  await expect(providers.getByText('Synthetic E2E Provider Updated')).toBeVisible()

  const models = page.getByRole('region', { name: '模型能力档案' })
  await models.getByLabel('服务商').selectOption({ label: 'Synthetic E2E Provider Updated' })
  await models.getByLabel('显示名称').fill('Synthetic E2E Fallback')
  await models.getByLabel('模型标识').fill('synthetic-e2e-fallback')
  await models.getByRole('checkbox', { name: /作为备用模型/ }).check()
  await models.getByRole('button', { name: '保存模型档案' }).click()
  const modelRow = models.locator('article').filter({ hasText: 'Synthetic E2E Fallback' })
  await expect(modelRow.getByText('备用', { exact: true })).toBeVisible()

  await modelRow.getByRole('button', { name: '删除模型 Synthetic E2E Fallback' }).click()
  await expect(page.getByRole('dialog')).toContainText('历史调用审计不会被删除')
  await page.getByRole('dialog').getByRole('button', { name: '确认删除' }).click()
  await expect(models.getByText('Synthetic E2E Fallback')).toHaveCount(0)

  await providerRow.getByRole('button', { name: '删除服务商 Synthetic E2E Provider Updated' }).click()
  await page.getByRole('dialog').getByRole('button', { name: '确认删除' }).click()
  await expect(providers.getByText('Synthetic E2E Provider Updated')).toHaveCount(0)
})
