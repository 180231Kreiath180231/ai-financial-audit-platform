import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { RiskWorkspace } from './RiskWorkspace'
import type { RiskRecord } from '../types'

const risk: RiskRecord = {
  id: 'risk-1',
  risk_number: 'R-0001',
  risk_type: '人工线索',
  risk_level: '待评估',
  status: '待复核',
  summary: '核对合成项目中的异常说明',
  trigger_rule_id: 'MANUAL-DRAFT',
  trigger_rule_version: 'v1',
  input_values: {},
  baseline_values: {},
  calculation_result: {},
  model_explanation: null,
  uncertainty: '尚未生成解释。',
  human_opinion: '',
  model_provider: null,
  actual_model: null,
  model_call_id: null,
  version: 1,
  created_at: '2026-09-22T00:00:00Z',
  updated_at: '2026-09-22T00:00:00Z',
  evidence: [{
    id: 'evidence-1',
    kind: 'document',
    document_id: 'document-1',
    document_name: 'synthetic.pdf',
    page_number: 1,
    block_number: 1,
    dataset_id: null,
    line_start: null,
    line_end: null,
    period_key: null,
    account_code: null,
    quote: 'AUDIT-EVIDENCE-2025',
    direction: 'support',
    parse_method: 'native',
    parse_version: 'pypdf-v1',
  }],
  versions: [{
    version: 1,
    change_reason: '创建人工风险草稿',
    created_at: '2026-09-22T00:00:00Z',
    snapshot: {},
  }],
}

function renderWorkspace(overrides: Partial<Parameters<typeof RiskWorkspace>[0]> = {}) {
  const props = {
    risks: [risk],
    selectedRisk: risk,
    busy: null,
    error: null,
    notice: null,
    onSelect: vi.fn(),
    onTransition: vi.fn().mockResolvedValue(true),
    onFakeExplanation: vi.fn().mockResolvedValue(undefined),
    onOpenEvidence: vi.fn(),
    ...overrides,
  }
  render(<RiskWorkspace {...props} />)
  return props
}

describe('RiskWorkspace', () => {
  it('shows traceable evidence and opens its source', async () => {
    const user = userEvent.setup()
    const props = renderWorkspace()

    await user.click(screen.getByRole('button', { name: /synthetic\.pdf · 第 1 页/ }))

    expect(props.onOpenEvidence).toHaveBeenCalledWith(risk.evidence[0])
    expect(screen.getByText('native / pypdf-v1 · 块 1')).toBeVisible()
  })

  it('requires a review note before changing status and preserves the note', async () => {
    const user = userEvent.setup()
    const props = renderWorkspace()
    const verified = screen.getByRole('button', { name: '转为已核实' })

    expect(verified).toBeDisabled()
    await user.type(screen.getByLabelText('复核备注'), '已核对原始凭证')
    expect(verified).toBeEnabled()
    await user.click(verified)

    expect(props.onTransition).toHaveBeenCalledWith(risk, '已核实', '已核对原始凭证')
  })

  it('labels the local synthetic explanation action', async () => {
    const user = userEvent.setup()
    const props = renderWorkspace()

    await user.click(screen.getByRole('button', { name: '生成合成解释草稿' }))

    expect(props.onFakeExplanation).toHaveBeenCalledWith(risk)
    expect(screen.getByText('尚未生成 · 仅允许 Fake Provider')).toBeVisible()
  })
})
