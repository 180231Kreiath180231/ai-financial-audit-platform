import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api'
import type { FinancialTrendAnalysis } from '../types'
import { FinancialTrendPanel } from './FinancialTrendPanel'

vi.mock('../api', () => ({
  api: {
    financialTrendAccounts: vi.fn(),
    financialTrendAnalysis: vi.fn(),
  },
}))

const analysis: FinancialTrendAnalysis = {
  dataset_id: 'dataset-1',
  analysis_version: 'FIN-TREND-v1',
  account: { account_code: '1001', account_name: '库存现金' },
  denominator: null,
  period_type: 'annual',
  currency: 'CNY',
  value_basis: '期末净额（期末借方-期末贷方），金额单位为元',
  sample_count: 3,
  sample_quality: 'limited',
  uncertainty: '样本不超过 11 期，MAD 与 Z-score 仅作辅助，不单独决定风险等级。',
  missing_periods: ['2023-FY'],
  mean: '200.00',
  median: '120.00',
  mad: '20.00',
  standard_deviation: '141.42',
  points: [
    { period_key: '2022-FY', closing_net: '100.00', yoy_change: null, yoy_percent: null, direction: null, trend_run: 0, turning_point: false, z_score: '-0.7071', robust_z_score: '-0.6745', structure_ratio: null, signals: [] },
    { period_key: '2024-FY', closing_net: '400.00', yoy_change: null, yoy_percent: null, direction: null, trend_run: 0, turning_point: false, z_score: '1.4142', robust_z_score: '9.4429', structure_ratio: null, signals: ['MAD 稳健偏离'] },
    { period_key: '2025-FY', closing_net: '100.00', yoy_change: '-300.00', yoy_percent: '-75.0000', direction: 'down', trend_run: 1, turning_point: false, z_score: '-0.7071', robust_z_score: '-0.6745', structure_ratio: null, signals: [] },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.financialTrendAccounts).mockResolvedValue([
    { account_code: '1001', account_name: '库存现金', period_count: 3, period_start: '2022-FY', period_end: '2025-FY' },
    { account_code: 'A-TOTAL', account_name: '资产总计', period_count: 4, period_start: '2022-FY', period_end: '2025-FY' },
  ])
  vi.mocked(api.financialTrendAnalysis).mockResolvedValue(analysis)
})

describe('FinancialTrendPanel', () => {
  it('shows exact values, missing periods, and non-decisive statistical signals', async () => {
    render(<FinancialTrendPanel projectId="project-1" datasetId="dataset-1" />)

    expect(await screen.findByText(/缺失期间：2023-FY/)).toBeVisible()
    expect(screen.getByText('MAD 稳健偏离')).toBeVisible()
    expect(screen.getByText('-75%')).toBeVisible()
    expect(screen.getByRole('img', { name: /库存现金.*3 个期间.*1 期存在辅助信号/ })).toBeVisible()
    expect(screen.getByText(/统计信号不直接确定风险等级/)).toBeVisible()
  })

  it('uses a user-selected total account as the explicit structure denominator', async () => {
    const user = userEvent.setup()
    vi.mocked(api.financialTrendAnalysis).mockImplementation(async (_project, _dataset, _account, denominator) => ({
      ...analysis,
      denominator: denominator ? { account_code: 'A-TOTAL', account_name: '资产总计', basis: '期末净额绝对值（借方-贷方）' } : null,
      points: analysis.points.map((point) => ({ ...point, structure_ratio: denominator ? '10.0000' : null })),
    }))
    render(<FinancialTrendPanel projectId="project-1" datasetId="dataset-1" />)

    await screen.findByRole('img')
    await user.selectOptions(screen.getByLabelText('结构占比基准'), 'A-TOTAL')

    await waitFor(() => expect(api.financialTrendAnalysis).toHaveBeenLastCalledWith(
      'project-1', 'dataset-1', '1001', 'A-TOTAL',
    ))
    expect((await screen.findByText(/结构占比分母：/)).closest('.trend-denominator')).toHaveTextContent('A-TOTAL · 资产总计')
    expect(screen.getAllByText('10%')).toHaveLength(3)
  })
})
