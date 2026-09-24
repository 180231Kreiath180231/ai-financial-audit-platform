import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api'
import type { FinancialDataset, FinancialPreview, Project } from '../types'
import { FinancialDataWorkspace } from './FinancialDataWorkspace'

vi.mock('../api', () => ({
  api: {
    listFinancialDatasets: vi.fn(),
    getFinancialDataset: vi.fn(),
    previewFinancialData: vi.fn(),
    confirmFinancialData: vi.fn(),
    financialResultRows: vi.fn(),
    archiveFinancialDataset: vi.fn(),
    reuseFinancialRuleRun: vi.fn(),
    financialTrendAccounts: vi.fn(),
    financialTrendAnalysis: vi.fn(),
  },
}))

const project: Project = {
  id: 'project-1',
  name: '合成审计项目',
  entity_name: '合成主体',
  year_start: 2024,
  year_end: 2025,
  storage_path: 'C:/synthetic',
  model_profile: '严格离线 / Fake Provider',
  is_synthetic: true,
  created_at: '2026-09-22T00:00:00Z',
  document_count: 0,
  page_count: 0,
  queued_count: 0,
  running_count: 0,
  failed_count: 0,
  completed_count: 0,
  storage_available: true,
  storage_error_code: null,
  external_access_enabled: false,
}

const dataset: FinancialDataset = {
  id: 'dataset-1',
  filename: 'synthetic.csv',
  sha256: 'a'.repeat(64),
  size_bytes: 1024,
  encoding: 'utf-8-sig',
  period_type: 'annual',
  period_start: '2024-FY',
  period_end: '2025-FY',
  row_count: 4,
  currency: 'CNY',
  amount_unit: '元',
  status: 'active',
  created_at: '2026-09-22T00:00:00Z',
  archived_at: null,
  rule_run_id: 'run-1',
  rule_set_version: 'TB-RULESET-v1',
  rule_run_status: 'completed',
  passed_count: 7,
  failed_count: 1,
  unavailable_count: 1,
  completed_at: '2026-09-22T00:01:00Z',
  import_warnings: [],
  rule_results: [{
    id: 'result-1',
    rule_id: 'TB-BAL-OPEN-001',
    rule_version: 'v1',
    period_key: '2025-FY',
    status: 'fail',
    summary: '2025-FY 期初借贷总额不平衡',
    input_values: { debit_total: '900.00', credit_total: '1000.00' },
    baseline_values: { tolerance: '0.01', currency: 'CNY' },
    calculation_result: { difference: '-100.00' },
    scope: { kind: 'period', period_key: '2025-FY' },
    affected_count: 2,
    line_start: 4,
    line_end: 5,
    created_at: '2026-09-22T00:01:00Z',
  }],
}

const validPreview: FinancialPreview = {
  preview_id: 'preview-1',
  duplicate_dataset_id: null,
  valid: true,
  encoding: 'utf-8-sig',
  size_bytes: 1024,
  row_count: 4,
  currency: 'CNY',
  amount_unit: '元',
  period_type: 'annual',
  period_start: '2024-FY',
  period_end: '2025-FY',
  extra_columns: [],
  warnings: [],
  errors: [],
  sample_rows: [{ 行号: '2', 年度: '2024', 期间: 'FY', 科目编码: '001001', 科目名称: '库存现金', 期末借方: '1000.00', 期末贷方: '0.00', 币种: 'CNY' }],
}

function renderWorkspace() {
  return render(
    <FinancialDataWorkspace
      project={project}
      tasks={[]}
      focusTarget={null}
      onRefreshProject={vi.fn().mockResolvedValue(undefined)}
    />,
  )
}

describe('FinancialDataWorkspace', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.listFinancialDatasets).mockResolvedValue([])
  })

  it('validates a CSV before enabling confirmation', async () => {
    const user = userEvent.setup()
    vi.mocked(api.previewFinancialData).mockResolvedValue(validPreview)
    vi.mocked(api.confirmFinancialData).mockResolvedValue({
      reused_dataset_id: null,
      task: null,
    })
    renderWorkspace()

    await user.upload(
      screen.getByLabelText('选择科目余额表 CSV'),
      new File(['synthetic'], 'synthetic.csv', { type: 'text/csv' }),
    )

    expect(await screen.findByRole('heading', { name: '结构校验完成' })).toBeVisible()
    expect(screen.getByText('001001')).toBeVisible()
    const confirm = screen.getByRole('button', { name: '确认导入并运行规则' })
    expect(confirm).toBeEnabled()
    await user.click(confirm)
    expect(api.confirmFinancialData).toHaveBeenCalledWith('project-1', 'preview-1')
  })

  it('keeps structural errors visible and blocks import', async () => {
    const user = userEvent.setup()
    vi.mocked(api.previewFinancialData).mockResolvedValue({
      ...validPreview,
      preview_id: null,
      valid: false,
      errors: [{
        code: 'CSV_AMOUNT_INVALID',
        message: '第 2 行金额无效',
        action: '修正金额后重新上传',
        line_number: 2,
        field: '本期借方',
      }],
      sample_rows: [],
    })
    renderWorkspace()

    await user.upload(
      screen.getByLabelText('选择科目余额表 CSV'),
      new File(['invalid'], 'invalid.csv', { type: 'text/csv' }),
    )

    expect(await screen.findByText('CSV_AMOUNT_INVALID')).toBeVisible()
    expect(screen.getByRole('button', { name: '确认导入并运行规则' })).toBeDisabled()
  })

  it('shows deterministic calculations and paged source rows', async () => {
    vi.mocked(api.listFinancialDatasets).mockResolvedValue([dataset])
    vi.mocked(api.getFinancialDataset).mockResolvedValue(dataset)
    vi.mocked(api.financialResultRows).mockResolvedValue({
      total: 2,
      offset: 0,
      limit: 100,
      rows: [{
        line_number: 4,
        year: 2025,
        period: 'FY',
        account_code: '001001',
        account_name: '库存现金',
        opening_debit: '900.00',
        opening_credit: '0.00',
        period_debit: '200.00',
        period_credit: '0.00',
        closing_debit: '1100.00',
        closing_credit: '0.00',
        currency: 'CNY',
        reason: '期初借贷总额计算范围',
      }],
    })
    renderWorkspace()

    expect(await screen.findByRole('heading', { name: 'synthetic.csv' })).toBeVisible()
    expect(await screen.findByText('difference：-100.00')).toBeVisible()
    expect(await screen.findByText('001001')).toBeVisible()
    expect(screen.getByText('期初借贷总额计算范围')).toBeVisible()
    await waitFor(() => expect(api.financialResultRows).toHaveBeenCalledWith(
      'project-1',
      'dataset-1',
      'result-1',
      0,
      100,
    ))
  })
})
