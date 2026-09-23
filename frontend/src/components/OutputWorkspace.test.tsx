import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api'
import type { OutputSnapshotDetail, Project, RiskRecord } from '../types'
import { OutputWorkspace } from './OutputWorkspace'

vi.mock('../api', () => ({
  api: {
    listOutputSnapshots: vi.fn(),
    getOutputSnapshot: vi.fn(),
    createRiskRegisterSnapshot: vi.fn(),
  },
}))

const project: Project = {
  id: 'project-1',
  name: '2025 年度合成审计',
  entity_name: '示例科技有限公司',
  year_start: 2025,
  year_end: 2025,
  storage_path: 'C:/audit/project-1',
  model_profile: 'fake-local',
  is_synthetic: true,
  created_at: '2026-09-23T00:00:00Z',
  document_count: 1,
  page_count: 1,
  queued_count: 0,
  running_count: 0,
  failed_count: 0,
  completed_count: 1,
  storage_available: true,
  storage_error_code: null,
  external_access_enabled: false,
}

function risk(status: RiskRecord['status']): RiskRecord {
  return {
    id: 'risk-1',
    risk_number: 'R-0001',
    risk_type: '余额异常',
    risk_level: '高',
    status,
    summary: '银行存款期末余额需要复核',
    trigger_rule_id: 'BALANCE-SPIKE',
    trigger_rule_version: 'v1',
    input_values: { closing_balance: 980000 },
    baseline_values: { prior_balance: 120000 },
    calculation_result: { ratio: 8.17 },
    model_explanation: null,
    uncertainty: '需核对银行回函。',
    human_opinion: '已核对原始回函。',
    model_provider: null,
    actual_model: null,
    model_call_id: null,
    version: 2,
    created_at: '2026-09-23T00:00:00Z',
    updated_at: '2026-09-23T01:00:00Z',
    evidence: [{
      id: 'evidence-1',
      kind: 'document',
      document_id: 'document-1',
      document_name: '银行回函.pdf',
      page_number: 1,
      block_number: 2,
      dataset_id: null,
      line_start: null,
      line_end: null,
      period_key: null,
      account_code: null,
      quote: '期末账户余额为 980,000 元。',
      direction: 'support',
      parse_method: 'native',
      parse_version: 'pypdf-v1',
    }],
    versions: [],
  }
}

const snapshot: OutputSnapshotDetail = {
  id: 'snapshot-1',
  output_kind: 'risk_register',
  schema_version: 'output-snapshot-v1',
  template_version: 'format-neutral-risk-register-v1',
  risk_count: 1,
  content_sha256: '1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef',
  created_at: '2026-09-23T02:00:00Z',
  snapshot: {
    schema_version: 'output-snapshot-v1',
    output_kind: 'risk_register',
    project: {
      id: project.id,
      name: project.name,
      entity_name: project.entity_name,
      year_start: project.year_start,
      year_end: project.year_end,
    },
    risks: [{
      risk_id: 'risk-1',
      risk_number: 'R-0001',
      risk_version: 2,
      risk_type: '余额异常',
      risk_level: '高',
      status: '已核实',
      summary: '银行存款期末余额需要复核',
      trigger_rule_id: 'BALANCE-SPIKE',
      trigger_rule_version: 'v1',
      input_values: { closing_balance: 980000 },
      baseline_values: { prior_balance: 120000 },
      calculation_result: { ratio: 8.17 },
      model_explanation: null,
      uncertainty: '需核对银行回函。',
      human_opinion: '已核对原始回函。',
      model_source: { provider: null, actual_model: null, model_call_id: null },
      evidence: [{
        citation: 'R-0001-E01',
        source_evidence_id: 'evidence-1',
        kind: 'document',
        direction: 'support',
        source_reference: '银行回函.pdf · 第 1 页 · 块 2',
        quote: '期末账户余额为 980,000 元。',
      }],
    }],
  },
}

describe('OutputWorkspace', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.listOutputSnapshots).mockResolvedValue([])
  })

  it('explains why no risk can be frozen and links back to review', async () => {
    const onOpenRisks = vi.fn()
    const user = userEvent.setup()
    render(<OutputWorkspace project={project} risks={[risk('待复核')]} onOpenRisks={onOpenRisks} />)

    expect(await screen.findByText('尚无可固化风险')).toBeVisible()
    expect(screen.getByRole('button', { name: '生成风险清单快照' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: '前往风险台账' }))

    expect(onOpenRisks).toHaveBeenCalledOnce()
    expect(api.listOutputSnapshots).toHaveBeenCalledWith(project.id)
  })

  it('creates an immutable preview while keeping undecided file formats disabled', async () => {
    vi.mocked(api.createRiskRegisterSnapshot).mockResolvedValue(snapshot)
    const user = userEvent.setup()
    render(<OutputWorkspace project={project} risks={[risk('已核实')]} onOpenRisks={vi.fn()} />)

    const create = await screen.findByRole('button', { name: '生成风险清单快照' })
    await waitFor(() => expect(create).toBeEnabled())
    await user.click(create)

    expect(api.createRiskRegisterSnapshot).toHaveBeenCalledWith(project.id)
    expect(await screen.findByText(/已固化 1 项风险及其证据引用/)).toBeVisible()
    expect(screen.getByText('R-0001')).toBeVisible()
    expect(screen.getByText('R-0001-E01')).toBeVisible()
    expect(screen.getByText('已核对原始回函。')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Word' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Excel' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'PDF' })).toBeDisabled()
  })
})
