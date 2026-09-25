import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { RiskWorkspace } from './RiskWorkspace'
import type { EvidenceSelection, RiskRecord } from '../types'

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

const candidateEvidence: EvidenceSelection = {
  document_id: 'document-2',
  document_name: 'new-evidence.pdf',
  page_number: 3,
  block_number: 1,
  parse_method: 'native_pdf',
  parse_version: 'pypdf-v1',
  snippet: 'new counter evidence',
  match_kind: 'content',
  fiscal_year: null,
  entity_name: null,
  document_type: null,
  account_names: [],
  direction: 'counter',
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
    candidateEvidence: [],
    onReassess: vi.fn().mockResolvedValue(true),
    onClearCandidateEvidence: vi.fn(),
    onFindEvidence: vi.fn(),
    onFakeExplanation: vi.fn().mockResolvedValue(undefined),
    onOpenEvidence: vi.fn(),
    onOpenNotes: vi.fn(),
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
    expect(screen.getByText('尚未生成 · 当前仅允许本地模拟服务')).toBeVisible()
  })

  it('does not offer a model explanation after human confirmation', () => {
    renderWorkspace({ selectedRisk: { ...risk, status: '已核实' } })

    expect(screen.queryByRole('button', { name: '生成合成解释草稿' })).not.toBeInTheDocument()
    expect(screen.getByText('当前状态不允许生成解释')).toBeVisible()
    expect(screen.getByText('人工确认后的风险不会被新的模型内容静默改变。')).toBeVisible()
  })

  it('requires an explicit reason before attaching new evidence and reopening one risk', async () => {
    const user = userEvent.setup()
    const verified = { ...risk, status: '已核实' as const }
    const props = renderWorkspace({ selectedRisk: verified, candidateEvidence: [candidateEvidence] })
    const submit = screen.getByRole('button', { name: '关联证据并重新评估' })

    expect(screen.getByText(/当前状态“已核实”将显式重开为“待复核”/)).toBeVisible()
    expect(submit).toBeDisabled()
    await user.type(screen.getByLabelText('重新评估原因'), '新反证可能改变原结论')
    await user.click(submit)

    expect(props.onReassess).toHaveBeenCalledWith(
      verified,
      [candidateEvidence],
      '新反证可能改变原结论',
    )
  })

  it('shows an accessible comparison with the previous immutable version', () => {
    const oldSnapshot = { ...risk, status: '已核实', model_explanation: '旧解释', versions: [] }
    const newEvidence = {
      ...risk.evidence[0],
      id: 'evidence-2',
      document_name: 'new-evidence.pdf',
      page_number: 3,
      direction: 'counter',
    }
    renderWorkspace({
      selectedRisk: {
        ...risk,
        version: 2,
        versions: [
          {
            version: 2,
            change_reason: '增量回溯：新反证可能改变原结论',
            created_at: '2026-09-23T00:00:00Z',
            snapshot: { ...oldSnapshot, status: '待复核', model_explanation: null, evidence: [...risk.evidence, newEvidence] },
          },
          { version: 1, change_reason: '已核实', created_at: '2026-09-22T00:00:00Z', snapshot: oldSnapshot },
        ],
      },
    })

    expect(screen.getByLabelText('版本 2 差异')).toHaveTextContent('状态已核实待复核')
    expect(screen.getByLabelText('版本 2 差异')).toHaveTextContent('新增证据反证 · new-evidence.pdf · 第 3 页')
    expect(screen.getByLabelText('版本 2 差异')).toHaveTextContent('AI 解释已有解释已清除，等待重新复核')
  })
})
