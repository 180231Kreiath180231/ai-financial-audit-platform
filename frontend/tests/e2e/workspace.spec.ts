import { expect, test, type Page } from '@playwright/test'

async function openDocuments(page: Page) {
  const mobileNavigation = page.getByRole('navigation', { name: '移动端主功能' })
  if (await mobileNavigation.isVisible()) {
    await mobileNavigation.getByRole('button', { name: '资料' }).click()
  } else {
    await page.getByRole('navigation', { name: '主功能' }).getByRole('button', { name: '资料' }).click()
  }
}

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
  await expect(page.getByRole('heading', { name: '项目概览' })).toBeVisible()
  await expect(page.getByText('从资料到工作成果')).toBeVisible()

  await openDocuments(page)
  if (test.info().project.name === 'mobile') {
    await page.getByRole('navigation', { name: '项目工作区' }).getByRole('button', { name: '资料' }).click()
  }
  await expect(page.getByRole('heading', { name: '资料队列' })).toBeVisible()
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
  await openDocuments(page)

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

  const projectSearch = page.getByRole('region', { name: '项目全文检索' })
  await projectSearch.getByRole('button', { name: '构建合成索引' }).click()
  await expect(projectSearch.getByText('语义检索 · 合成就绪')).toBeVisible()
  await expect(projectSearch.getByRole('button', { name: '混合检索已开启' })).toHaveAttribute('aria-pressed', 'true')
  await projectSearch.getByRole('searchbox', { name: '搜索全部本地文档' }).fill('AUDIT-EVIDENCE-2025')
  await projectSearch.getByRole('button', { name: '检索', exact: true }).click()
  await expect(projectSearch.getByText('1 条命中 · 合成混合检索 · 未调用外部服务')).toBeVisible()
  await projectSearch.getByRole('button', { name: /playwright-evidence\.pdf/ }).click()
  const reader = page.getByRole('region', { name: /playwright-evidence\.pdf 阅读器/ })
  await expect(reader).toBeVisible()
  await reader.getByRole('textbox', { name: '搜索文档原文' }).fill('AUDIT-EVIDENCE-2025')
  await reader.getByRole('button', { name: '查找' }).click()
  const searchHit = reader.getByRole('button', { name: /第 1 页/ })
  await expect(searchHit).toBeVisible()
  await searchHit.click()
  await expect(page.getByLabel('页码')).toHaveValue('1')
})

test('versions document metadata and filters without a keyword', async ({ page }) => {
  test.skip(test.info().project.name !== 'desktop', 'desktop metadata acceptance path')
  await page.goto('/')
  await openDocuments(page)

  await page.locator('input[type="file"]').setInputFiles({
    name: 'playwright-metadata.pdf',
    mimeType: 'application/pdf',
    buffer: syntheticTextPdf('METADATA-EVIDENCE-2025'),
  })
  const documentList = page.getByLabel('已导入文档')
  await expect(documentList.getByRole('button', { name: /playwright-metadata\.pdf/ })).toBeVisible({ timeout: 20_000 })

  const projectSearch = page.getByRole('region', { name: '项目全文检索' })
  await projectSearch.getByText('结构化筛选').click()
  const filterGrid = projectSearch.locator('.project-search-filter-grid')
  await filterGrid.locator('select').first().selectOption({ label: 'playwright-metadata.pdf' })
  await projectSearch.getByRole('button', { name: '编辑所选文档标注' }).click()
  const editor = projectSearch.locator('.document-metadata-editor')
  await editor.getByRole('spinbutton', { name: '年度' }).fill('2025')
  await editor.getByRole('textbox', { name: '主体' }).fill('E2E 合成主体')
  await editor.getByRole('textbox', { name: '文档类型' }).fill('E2E 专项报告')
  await editor.getByRole('textbox', { name: '科目标签' }).fill('E2E 营业收入，应收账款')
  await editor.getByRole('button', { name: '保存标注' }).click()
  await expect(editor.getByRole('status')).toContainText('标注已保存为版本 1')

  await projectSearch.getByRole('button', { name: '清除筛选' }).click()
  await filterGrid.getByRole('combobox', { name: '主体' }).fill('E2E 合成主体')
  await filterGrid.getByRole('combobox', { name: '科目' }).fill('E2E 营业收入')
  await filterGrid.getByRole('combobox', { name: '文档类型' }).fill('E2E 专项报告')
  await projectSearch.getByRole('button', { name: '检索' }).click()

  await expect(projectSearch.getByText('1 条命中 · 3 项筛选 · 本地全文检索 · 未调用外部服务')).toBeVisible()
  await projectSearch.getByRole('button', { name: /playwright-metadata\.pdf/ }).click()
  await expect(page.getByRole('region', { name: /playwright-metadata\.pdf 阅读器/ })).toBeVisible()
})

test('detects a scanned page and completes the local Fake Vision trace', async ({ page }) => {
  test.skip(test.info().project.name !== 'desktop', 'desktop scanned-page acceptance path')
  await page.goto('/')
  await openDocuments(page)

  await page.locator('input[type="file"]').setInputFiles({
    name: 'playwright-scanned-page.pdf',
    mimeType: 'application/pdf',
    buffer: syntheticTextPdf(''),
  })
  const documentList = page.getByLabel('已导入文档')
  const documentRow = documentList.getByRole('button', { name: /playwright-scanned-page\.pdf/ })
  await expect(documentRow).toContainText('扫描页 1', { timeout: 20_000 })
  await expect(documentRow).toContainText('合成视觉完成 · 外部请求 0 次')
  await documentRow.click()

  const viewer = page.getByRole('region', { name: /playwright-scanned-page\.pdf 阅读器/ })
  await expect(page.getByRole('complementary', { name: '复核与处置面板' }).getByRole('heading')).toHaveText('playwright-scanned-page.pdf')
  await expect(viewer.getByRole('status')).toContainText('第 1 页 · 合成视觉解析')
  await expect(viewer.getByRole('status')).toContainText('Fake Provider / fake-structured-v1 · 外部请求 0 次')
  await viewer.getByRole('textbox', { name: '搜索文档原文' }).fill('Fake Vision')
  await viewer.getByRole('button', { name: '查找' }).click()
  await expect(viewer.getByRole('button', { name: /第 1 页/ })).toContainText('Fake Vision')
  await expect(viewer.getByLabel('页码')).toHaveValue('1')
})

test('creates, reviews, and freezes a versioned risk from resolved evidence', async ({ page }) => {
  test.skip(test.info().project.name !== 'desktop', 'desktop risk acceptance path')
  await page.goto('/')
  await openDocuments(page)

  await page.locator('input[type="file"]').setInputFiles({
    name: 'playwright-risk-evidence.pdf',
    mimeType: 'application/pdf',
    buffer: syntheticTextPdf('RISK-EVIDENCE-LOCAL-ONLY'),
  })
  const documentList = page.getByLabel('已导入文档')
  const documentRow = documentList.getByRole('button', { name: /playwright-risk-evidence\.pdf/ })
  await expect(documentRow).toBeVisible({ timeout: 20_000 })
  const projectSearch = page.getByRole('region', { name: '项目全文检索' })
  await projectSearch.getByRole('searchbox', { name: '搜索全部本地文档' }).fill('RISK-EVIDENCE-LOCAL-ONLY')
  await projectSearch.getByRole('button', { name: '检索' }).click()
  await projectSearch.getByRole('button', { name: '支持证据' }).click()

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

  await page.getByRole('navigation', { name: '主功能' }).getByRole('button', { name: '输出' }).click()
  await page.getByRole('button', { name: '生成风险清单快照' }).click()
  await expect(page.getByRole('status')).toContainText('已固化 1 项风险及其证据引用')
  await page.getByRole('button', { name: '创建可编辑草稿' }).click()
  await expect(page.getByText('R-0001-E01')).toBeVisible()
  await expect(page.getByRole('textbox', { name: '人工编辑正文' })).toHaveValue('已核对合成原文与页码')
  await page.getByRole('tab', { name: '资料清单 1' }).click()
  await expect(page.getByRole('textbox', { name: '资料名称' })).toHaveValue(/R-0001/)
  await page.getByRole('tab', { name: '访谈提纲 2' }).click()
  await expect(page.getByRole('textbox', { name: '访谈问题' })).toHaveCount(2)
  await page.getByRole('tab', { name: '管理层材料 1' }).click()
  await expect(page.getByRole('textbox', { name: '沟通事项' })).toHaveValue('核对本地合成证据对应事项')
  await expect(page.getByRole('textbox', { name: '需管理层回复' })).toHaveValue(/责任安排和预计完成时间/)
  await page.getByRole('button', { name: '最终固化' }).click()
  await page.getByRole('button', { name: '确认最终固化' }).click()
  await expect(page.getByText('最终草稿 v2')).toBeVisible()
  await page.getByRole('button', { name: '生成 Excel' }).click()
  const excelDownload = page.waitForEvent('download')
  await page.getByRole('link', { name: '下载' }).click()
  await expect((await excelDownload).suggestedFilename()).toMatch(/^风险清单-\d{8}-v2-[a-f0-9]{8}\.xlsx$/)
  await page.getByRole('button', { name: '生成 Word' }).click()
  await expect(page.getByText(/^审计工作成果-\d{8}-v2-[a-f0-9]{8}\.docx$/)).toBeVisible()
  const wordDownload = page.waitForEvent('download')
  await page.getByRole('link', { name: '下载' }).first().click()
  await expect((await wordDownload).suggestedFilename()).toMatch(/^审计工作成果-\d{8}-v2-[a-f0-9]{8}\.docx$/)
  await page.getByRole('button', { name: '生成 PDF' }).click()
  await expect(page.getByText(/^审计工作成果归档件-\d{8}-v2-[a-f0-9]{8}\.pdf$/)).toBeVisible()
  const pdfDownload = page.waitForEvent('download')
  await page.getByRole('link', { name: '下载' }).first().click()
  await expect((await pdfDownload).suggestedFilename()).toMatch(/^审计工作成果归档件-\d{8}-v2-[a-f0-9]{8}\.pdf$/)
  await page.getByRole('button', { name: '生成证据包' }).click()
  await expect(page.getByText(/^审计证据包索引-\d{8}-v2-[a-f0-9]{8}\.xlsx$/)).toBeVisible()
  const evidenceDownload = page.waitForEvent('download')
  await page.getByRole('link', { name: '下载' }).first().click()
  await expect((await evidenceDownload).suggestedFilename()).toMatch(/^审计证据包索引-\d{8}-v2-[a-f0-9]{8}\.xlsx$/)

  await page.getByRole('navigation', { name: '主功能' }).getByRole('button', { name: '资料' }).click()
  await page.locator('input[type="file"]').setInputFiles({
    name: 'playwright-risk-counter-evidence.pdf',
    mimeType: 'application/pdf',
    buffer: syntheticTextPdf('RISK-COUNTER-EVIDENCE-NEW'),
  })
  await expect(documentList.getByRole('button', { name: /playwright-risk-counter-evidence\.pdf/ })).toBeVisible({ timeout: 20_000 })
  await projectSearch.getByRole('searchbox', { name: '搜索全部本地文档' }).fill('RISK-COUNTER-EVIDENCE-NEW')
  await projectSearch.getByRole('button', { name: '检索' }).click()
  await projectSearch.getByRole('button', { name: '反证' }).click()

  await page.getByRole('navigation', { name: '主功能' }).getByRole('button', { name: '风险' }).click()
  await expect(page.getByText(/当前状态“已核实”将显式重开为“待复核”/)).toBeVisible()
  await page.getByLabel('重新评估原因').fill('新反证可能推翻原结论，重新评估')
  await page.getByRole('button', { name: '关联证据并重新评估' }).click()
  await expect(page.getByRole('status')).toContainText('已关联新证据并重开为“待复核”')
  await expect(page.getByText('v4', { exact: true }).first()).toBeVisible()
  await expect(page.getByLabel('版本 4 差异')).toContainText('新增证据')
  await expect(page.getByLabel('版本 4 差异')).toContainText('playwright-risk-counter-evidence.pdf')

  await page.getByRole('navigation', { name: '主功能' }).getByRole('button', { name: '输出' }).click()
  await expect(page.getByText('最终草稿 v2')).toBeVisible()
})

test('creates, updates, and confirms deletion of an audit note', async ({ page }) => {
  test.skip(test.info().project.name !== 'desktop', 'desktop audit-note acceptance path')
  await page.goto('/')

  await page.getByRole('navigation', { name: '主功能' }).getByRole('button', { name: '风险' }).click()
  await page.getByRole('button', { name: '审计备忘录' }).click()
  await expect(page.getByRole('heading', { name: '审计备忘录' })).toBeVisible()
  await page.getByRole('button', { name: '新建备忘录' }).click()
  await page.getByLabel('备忘录标题').fill('Playwright 审计备忘录')
  await page.getByLabel('备忘录正文').fill('仅用于验证本地备忘录的创建、更新和确认删除闭环。')
  await page.getByLabel('备忘录标签').fill('端到端, 本地')
  await page.getByRole('checkbox', { name: /允许模型读取这条备忘录/ }).check()
  await page.getByRole('button', { name: '保存备忘录' }).click()
  await expect(page.getByRole('status')).toContainText('备忘录已创建')
  await expect(page.getByText('模型可读', { exact: true })).toBeVisible()

  await page.getByLabel('备忘录正文').fill('已更新：模型读取仍受严格离线和项目授权约束。')
  await page.getByRole('button', { name: '保存备忘录' }).click()
  await expect(page.getByRole('status')).toContainText('备忘录已更新')

  await page.getByRole('button', { name: '删除' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('风险和原始文档不会被删除')
  await dialog.getByRole('button', { name: '确认删除' }).click()
  await expect(page.getByRole('status')).toContainText('备忘录已删除')
})

test('imports a trial balance and traces a deterministic risk to CSV rows', async ({ page }) => {
  test.skip(test.info().project.name !== 'desktop', 'desktop financial-data acceptance path')
  await page.goto('/')
  await page.getByRole('navigation', { name: '主功能' }).getByRole('button', { name: '分析' }).click()
  await expect(page.getByRole('heading', { name: '财务数据' })).toBeVisible()

  const csv = [
    '年度,期间,科目编码,科目名称,期初借方,期初贷方,本期借方,本期贷方,期末借方,期末贷方,币种,是否末级',
    '2024,FY,001001,库存现金,0,0,1000,0,1000,0,CNY,1',
    '2024,FY,004001,实收资本,0,0,0,1000,0,1000,CNY,1',
    '2025,FY,001001,库存现金,900,0,200,0,1100,0,CNY,1',
    '2025,FY,004001,实收资本,0,1000,0,150,0,1150,CNY,1',
  ].join('\r\n')
  await page.getByLabel('选择科目余额表 CSV').setInputFiles({
    name: 'synthetic-trial-balance.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(`\ufeff${csv}`, 'utf8'),
  })
  await expect(page.getByRole('heading', { name: '结构校验完成' })).toBeVisible()
  await expect(page.getByText('001001').first()).toBeVisible()
  await page.getByRole('button', { name: '确认导入并运行规则' }).click()

  await expect(page.getByRole('heading', { name: 'synthetic-trial-balance.csv' })).toBeVisible({ timeout: 20_000 })
  await expect(page.getByText('2025-FY 期初借贷总额不平衡')).toBeVisible()
  await page.getByRole('button', { name: /2025-FY 期初借贷总额不平衡/ }).click()
  await expect(page.getByText('difference：-100.00')).toBeVisible()
  await expect(page.getByText('汇总计算范围').first()).toBeVisible()

  await page.getByRole('button', { name: '趋势与稳健统计' }).click()
  await expect(page.getByRole('heading', { name: '趋势与稳健统计' })).toBeVisible()
  await expect(page.getByText(/样本不足 · 2 期/)).toBeVisible()
  await expect(page.getByRole('img', { name: /库存现金.*2 个期间/ })).toBeVisible()
  await page.getByLabel('结构占比基准').selectOption('004001')
  await expect(page.getByText(/结构占比分母：/).locator('..')).toContainText('004001 · 实收资本')
  await expect(page.getByRole('cell', { name: /1,?100/ })).toBeVisible()

  await page.getByRole('navigation', { name: '主功能' }).getByRole('button', { name: '风险' }).click()
  await expect(page.getByText('2025-FY 期初借贷总额不平衡').first()).toBeVisible()
  await page.getByText('2025-FY 期初借贷总额不平衡').first().click()
  await page.getByRole('button', { name: /synthetic-trial-balance\.csv · CSV 行/ }).click()
  await expect(page.getByRole('heading', { name: '财务数据' })).toBeVisible()
  await expect(page.getByText('汇总计算范围').first()).toBeVisible()
})

test('mobile workspace exposes all three panes', async ({ page }) => {
  test.skip(test.info().project.name !== 'mobile', 'mobile-only assertion')
  await page.goto('/')
  await openDocuments(page)
  const switcher = page.getByRole('navigation', { name: '项目工作区' })
  await expect(switcher.getByRole('button', { name: '资料' })).toBeVisible()
  await switcher.getByRole('button', { name: '处置' }).click()
  const decisionPanel = page.getByRole('complementary', { name: '复核与处置面板' })
  await expect(decisionPanel).toBeVisible()
  await expect(decisionPanel.getByRole('button', { name: '判断依据' })).toBeVisible()

  const mobileNavigation = page.getByRole('navigation', { name: '移动端主功能' })
  await mobileNavigation.getByRole('button', { name: '更多' }).click()
  const moreMenu = page.getByRole('menu', { name: '更多功能' })
  await expect(moreMenu.getByRole('menuitem', { name: /输出/ })).toBeVisible()
  await expect(moreMenu.getByRole('menuitem', { name: /设置/ })).toBeVisible()
  await moreMenu.getByRole('menuitem', { name: /设置/ }).click()
  await expect(page.getByRole('heading', { name: '模型与外发设置' })).toBeVisible()
})

test('project assistant supports an explicit general-knowledge conversation', async ({ page }) => {
  await page.goto('/')

  await page.getByRole('button', { name: /AI 审计助手/ }).click()
  const assistant = page.getByRole('complementary', { name: 'AI 审计助手' })
  await expect(assistant).toBeVisible()
  await expect(assistant).toContainText('联网检索未启用')

  await assistant.getByLabel('回答范围').selectOption('general')
  await assistant.getByRole('button', { name: '专业问答' }).click()
  const question = assistant.getByLabel('向 AI 审计助手提问')
  await question.fill('什么是审计抽样？')
  await assistant.getByRole('button', { name: /发送/ }).click()

  await expect(assistant.getByText('通用知识', { exact: true }).last()).toBeVisible()
  await expect(assistant.getByText('本地模拟', { exact: true }).last()).toBeVisible()
  await expect(assistant.getByText(/当前使用本地模拟服务/).last()).toBeVisible()
  await expect(assistant.getByLabel('本次包含最近对话')).not.toBeChecked()

  await assistant.getByRole('button', { name: '关闭 AI 助手' }).click()
  await expect(page.getByRole('button', { name: /AI 审计助手/ })).toBeVisible()
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
  await providers.getByRole('combobox', { name: /服务商类型/ }).selectOption('paddleocr_aistudio')
  await expect(providers.getByRole('textbox', { name: /Base URL/ })).toHaveValue('https://paddleocr.aistudio-app.com/api/v2/ocr/jobs')
  await expect(providers.getByRole('textbox', { name: /Base URL/ })).toHaveAttribute('readonly')
  await expect(providers.getByLabel(/Access Token/)).toHaveAttribute('type', 'password')
  await providers.getByRole('combobox', { name: /服务商类型/ }).selectOption('openai_compatible')
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
  await models.getByRole('combobox').selectOption({ label: 'Synthetic E2E Provider Updated' })
  await models.getByLabel('显示名称').fill('Synthetic E2E Fallback')
  await models.getByRole('textbox', { name: /^模型标识/ }).fill('synthetic-e2e-fallback')
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
