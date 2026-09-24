import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api'
import type {
  OutputDraftRecord,
  OutputExportRecord,
  OutputSnapshotDetail,
  Project,
  RiskRecord,
} from '../types'
import { OutputWorkspace } from './OutputWorkspace'

vi.mock('../api', () => ({
  api: {
    listOutputSnapshots: vi.fn(),
    getOutputSnapshot: vi.fn(),
    createRiskRegisterSnapshot: vi.fn(),
    listOutputDrafts: vi.fn(),
    createOutputDraft: vi.fn(),
    updateOutputDraft: vi.fn(),
    finalizeOutputDraft: vi.fn(),
    listOutputExports: vi.fn(),
    createExcelExport: vi.fn(),
    createWordExport: vi.fn(),
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

const draft: OutputDraftRecord = {
  id: 'draft-1',
  snapshot_id: snapshot.id,
  output_kind: 'risk_register',
  status: 'editing',
  version: 1,
  title: '2025 年度合成审计风险清单',
  notes: '',
  items: [{
    risk_id: 'risk-1',
    risk_number: 'R-0001',
    heading: '银行存款期末余额需要复核',
    body: '已核对原始回函。',
  }],
  materials_title: '资料清单',
  materials: [{
    id: 'M-001',
    risk_id: 'risk-1',
    risk_number: 'R-0001',
    title: 'R-0001 原始文件、审批记录及补充支持材料',
    purpose: '用于复核银行存款期末余额。',
    requested_scope: '合成测试公司 · 2024—2025',
    priority: '高',
  }],
  interview_title: '访谈提纲',
  interviews: [{
    id: 'Q-001',
    risk_id: 'risk-1',
    risk_number: 'R-0001',
    audience: '业务负责人 / 财务负责人',
    question: '请说明余额形成原因。',
    objective: '核实事实背景。',
  }, {
    id: 'Q-002',
    risk_id: 'risk-1',
    risk_number: 'R-0001',
    audience: '业务负责人 / 财务负责人',
    question: '支持材料如何形成和复核？',
    objective: '了解证据形成过程。',
  }],
  created_at: '2026-09-23T02:10:00Z',
  updated_at: '2026-09-23T02:10:00Z',
  finalized_at: null,
  versions: [{ version: 1, change_reason: '从不可变快照创建草稿', created_at: '2026-09-23T02:10:00Z' }],
}

const excel: OutputExportRecord = {
  id: 'export-1',
  draft_id: draft.id,
  draft_version: 3,
  snapshot_id: snapshot.id,
  export_format: 'xlsx',
  template_version: 'risk-register-excel-v1',
  filename: '风险清单-20260923-v3-export1.xlsx',
  file_sha256: 'abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890',
  size_bytes: 24576,
  created_at: '2026-09-23T02:30:00Z',
  download_url: '/api/v1/projects/project-1/outputs/exports/export-1/file',
}

const word: OutputExportRecord = {
  ...excel,
  id: 'export-2',
  export_format: 'docx',
  template_version: 'audit-work-products-word-v1',
  filename: '审计工作成果-20260923-v3-export2.docx',
  download_url: '/api/v1/projects/project-1/outputs/exports/export-2/file',
}

describe('OutputWorkspace', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.listOutputSnapshots).mockResolvedValue([])
    vi.mocked(api.listOutputDrafts).mockResolvedValue([])
    vi.mocked(api.listOutputExports).mockResolvedValue([])
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

  it('creates an immutable snapshot before exposing editable output fields', async () => {
    vi.mocked(api.createRiskRegisterSnapshot).mockResolvedValue(snapshot)
    const user = userEvent.setup()
    render(<OutputWorkspace project={project} risks={[risk('已核实')]} onOpenRisks={vi.fn()} />)

    const create = await screen.findByRole('button', { name: '生成风险清单快照' })
    await waitFor(() => expect(create).toBeEnabled())
    await user.click(create)

    expect(api.createRiskRegisterSnapshot).toHaveBeenCalledWith(project.id)
    expect(await screen.findByText(/已固化 1 项风险及其证据引用/)).toBeVisible()
    expect(screen.getByText('快照已锁定，尚未创建草稿')).toBeVisible()
    expect(screen.getByRole('button', { name: '创建可编辑草稿' })).toBeEnabled()
  })

  it('edits, versions, finalizes, and exports a draft through the real workflow', async () => {
    vi.mocked(api.listOutputSnapshots).mockResolvedValue([snapshot])
    vi.mocked(api.getOutputSnapshot).mockResolvedValue(snapshot)
    vi.mocked(api.createOutputDraft).mockResolvedValue(draft)
    const saved = {
      ...draft,
      version: 2,
      title: '经复核的风险清单',
      versions: [
        { version: 2, change_reason: '人工编辑输出草稿', created_at: '2026-09-23T02:20:00Z' },
        ...draft.versions,
      ],
    }
    const finalized: OutputDraftRecord = {
      ...saved,
      status: 'finalized',
      version: 3,
      finalized_at: '2026-09-23T02:25:00Z',
      versions: [
        { version: 3, change_reason: '最终固化输出草稿', created_at: '2026-09-23T02:25:00Z' },
        ...saved.versions,
      ],
    }
    vi.mocked(api.updateOutputDraft).mockResolvedValue(saved)
    vi.mocked(api.finalizeOutputDraft).mockResolvedValue(finalized)
    vi.mocked(api.createExcelExport).mockResolvedValue(excel)
    vi.mocked(api.createWordExport).mockResolvedValue(word)
    const user = userEvent.setup()
    render(<OutputWorkspace project={project} risks={[risk('已核实')]} onOpenRisks={vi.fn()} />)

    await user.click(await screen.findByRole('button', { name: '创建可编辑草稿' }))
    expect(screen.getByText('R-0001-E01')).toBeVisible()
    expect(screen.getByRole('tab', { name: '资料清单 1' })).toBeVisible()
    expect(screen.getByRole('tab', { name: '访谈提纲 2' })).toBeVisible()
    await user.click(screen.getByRole('tab', { name: '资料清单 1' }))
    expect(screen.getByRole('textbox', { name: '资料名称' })).toHaveValue('R-0001 原始文件、审批记录及补充支持材料')
    await user.click(screen.getByRole('tab', { name: '访谈提纲 2' }))
    expect(screen.getAllByRole('textbox', { name: '访谈问题' })).toHaveLength(2)
    await user.click(screen.getByRole('tab', { name: '风险清单 1' }))
    const title = screen.getByRole('textbox', { name: '成果包标题' })
    await user.clear(title)
    await user.type(title, '经复核的风险清单')
    await user.click(screen.getByRole('button', { name: '保存' }))

    expect(api.updateOutputDraft).toHaveBeenCalledWith(
      project.id,
      draft.id,
      expect.objectContaining({ title: '经复核的风险清单' }),
    )
    expect(await screen.findByText(/草稿已保存为 v2/)).toBeVisible()
    await user.click(screen.getByRole('button', { name: '最终固化' }))
    expect(screen.getByText('确认最终固化草稿 v2？')).toBeVisible()
    await user.click(screen.getByRole('button', { name: '确认最终固化' }))

    expect(await screen.findByText('最终草稿 v3')).toBeVisible()
    expect(screen.getByText('最终固化输出草稿')).toBeVisible()
    expect(screen.getByRole('textbox', { name: '成果包标题' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '从快照新建草稿' })).toBeEnabled()
    await user.click(screen.getByRole('button', { name: '生成 Excel' }))
    expect(await screen.findByText(excel.filename)).toBeVisible()
    expect(screen.getByRole('link', { name: '下载' })).toHaveAttribute('href', excel.download_url)
    expect(api.createExcelExport).toHaveBeenCalledWith(project.id, draft.id)
    await user.click(screen.getByRole('button', { name: '生成 Word' }))
    expect(await screen.findByText(word.filename)).toBeVisible()
    expect(screen.getAllByRole('link', { name: '下载' })).toHaveLength(2)
    expect(api.createWordExport).toHaveBeenCalledWith(project.id, draft.id)
  })
})
