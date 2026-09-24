import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api'
import type { AuditNoteRecord, DocumentRecord, Project, RiskRecord } from '../types'
import { NotesWorkspace } from './NotesWorkspace'

vi.mock('../api', () => ({
  api: {
    listNotes: vi.fn(),
    createNote: vi.fn(),
    updateNote: vi.fn(),
    deleteNote: vi.fn(),
  },
}))

const project = {
  id: 'project-1', name: '合成审计', entity_name: '示例公司', year_start: 2025, year_end: 2025,
  storage_path: 'C:/audit/project-1', model_profile: 'fake-local', is_synthetic: true,
  created_at: '2026-09-23T00:00:00Z', document_count: 1, page_count: 2, queued_count: 0,
  running_count: 0, failed_count: 0, completed_count: 1, storage_available: true,
  storage_error_code: null, external_access_enabled: false,
} satisfies Project

const document = {
  id: 'document-1', filename: '凭证.pdf', sha256: 'abc', size_bytes: 100, page_count: 2,
  parse_method: 'native', parse_version: 'v1', created_at: '2026-09-23T00:00:00Z',
  native_page_count: 2, scan_page_count: 0, vision_page_count: 0, external_vision_page_count: 0,
  vision_status: 'not_required', fiscal_year: 2025, entity_name: '示例公司', document_type: '凭证',
  account_names: [], metadata_version: 1, metadata_updated_at: null,
} satisfies DocumentRecord

const risk = {
  id: 'risk-1', risk_number: 'R-0001', risk_type: '人工线索', risk_level: '待评估', status: '待复核',
  summary: '收入截止异常', trigger_rule_id: 'MANUAL-DRAFT', trigger_rule_version: 'v1', input_values: {},
  baseline_values: {}, calculation_result: {}, model_explanation: null, uncertainty: '', human_opinion: '',
  model_provider: null, actual_model: null, model_call_id: null, version: 1,
  created_at: '2026-09-23T00:00:00Z', updated_at: '2026-09-23T00:00:00Z', evidence: [], versions: [],
} satisfies RiskRecord

const savedNote = {
  id: 'note-1', title: '收入截止复核', body: '核对期后回款和发票日期。', tags: ['收入', '截止'],
  model_readable: true, risks: [{ risk_id: risk.id, risk_number: risk.risk_number, summary: risk.summary }],
  pages: [{ document_id: document.id, document_name: document.filename, page_number: 2 }],
  created_at: '2026-09-23T00:00:00Z', updated_at: '2026-09-23T00:00:00Z',
} satisfies AuditNoteRecord

function renderWorkspace() {
  const props = { project, risks: [risk], documents: [document], onBack: vi.fn(), onOpenRisk: vi.fn(), onOpenPage: vi.fn() }
  render(<NotesWorkspace {...props} />)
  return props
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.listNotes).mockResolvedValue([])
  HTMLDialogElement.prototype.showModal = vi.fn(function (this: HTMLDialogElement) { this.setAttribute('open', '') })
  HTMLDialogElement.prototype.close = vi.fn(function (this: HTMLDialogElement) { this.removeAttribute('open') })
})

describe('NotesWorkspace', () => {
  it('creates a note with explicit model, risk, and page links', async () => {
    const user = userEvent.setup()
    vi.mocked(api.createNote).mockResolvedValue(savedNote)
    renderWorkspace()

    await screen.findByRole('heading', { name: '未命名备忘录' })
    await user.type(screen.getByLabelText('备忘录标题'), ' 收入截止复核 ')
    await user.type(screen.getByLabelText('备忘录正文'), ' 核对期后回款和发票日期。 ')
    await user.type(screen.getByLabelText('备忘录标签'), '收入，截止')
    await user.click(screen.getByRole('checkbox', { name: /允许模型读取这条备忘录/ }))
    await user.click(screen.getByRole('checkbox', { name: /R-0001 收入截止异常/ }))
    await user.clear(screen.getByLabelText('关联页码'))
    await user.type(screen.getByLabelText('关联页码'), '2')
    await user.click(screen.getByRole('button', { name: '添加页码' }))
    await user.click(screen.getByRole('button', { name: '保存备忘录' }))

    expect(api.createNote).toHaveBeenCalledWith(project.id, {
      title: '收入截止复核', body: '核对期后回款和发票日期。', tags: ['收入', '截止'], model_readable: true,
      risk_ids: [risk.id], pages: [{ document_id: document.id, page_number: 2 }],
    })
    expect(await screen.findByRole('status')).toHaveTextContent('备忘录已创建')
  })

  it('requires confirmation before deletion', async () => {
    const user = userEvent.setup()
    vi.mocked(api.listNotes).mockResolvedValue([savedNote])
    vi.mocked(api.deleteNote).mockResolvedValue(undefined)
    renderWorkspace()

    await screen.findByRole('heading', { name: '收入截止复核' })
    await user.click(screen.getByRole('button', { name: '删除' }))
    expect(api.deleteNote).not.toHaveBeenCalled()
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveTextContent('风险和原始文档不会被删除')
    await user.click(screen.getByRole('button', { name: '确认删除' }))

    await waitFor(() => expect(api.deleteNote).toHaveBeenCalledWith(project.id, savedNote.id))
    expect(await screen.findByRole('status')).toHaveTextContent('备忘录已删除')
  })

  it('opens linked risks and source pages', async () => {
    const user = userEvent.setup()
    vi.mocked(api.listNotes).mockResolvedValue([savedNote])
    const props = renderWorkspace()

    await screen.findByRole('heading', { name: '收入截止复核' })
    await user.click(screen.getByRole('button', { name: '查看' }))
    await user.click(screen.getByRole('button', { name: '凭证.pdf · 第 2 页' }))

    expect(props.onOpenRisk).toHaveBeenCalledWith(risk.id)
    expect(props.onOpenPage).toHaveBeenCalledWith(document.id, 2)
  })
})
