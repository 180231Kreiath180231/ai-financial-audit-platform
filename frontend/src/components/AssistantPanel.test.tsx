import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import { api } from '../api'
import type { AssistantThread, Project, RiskRecord } from '../types'
import { AssistantPanel } from './AssistantPanel'

vi.mock('../api', () => ({
  api: {
    listAssistantThreads: vi.fn(),
    createAssistantThread: vi.fn(),
    sendAssistantMessage: vi.fn(),
    deleteAssistantMessage: vi.fn(),
    deleteAssistantThread: vi.fn(),
    createNote: vi.fn(),
    createRisk: vi.fn(),
  },
}))

const project: Project = {
  id: 'project-1',
  name: '合成项目',
  entity_name: '合成主体',
  year_start: 2024,
  year_end: 2025,
  storage_path: 'C:/synthetic/project-1',
  model_profile: '严格离线 / 本地模拟服务',
  is_synthetic: true,
  created_at: '2026-09-24T00:00:00Z',
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

const emptyThread: AssistantThread = {
  id: 'thread-1',
  title: '新对话',
  default_scope: 'smart',
  messages: [],
  created_at: '2026-09-24T00:00:00Z',
  updated_at: '2026-09-24T00:00:00Z',
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.listAssistantThreads).mockResolvedValue([])
  vi.mocked(api.createAssistantThread).mockResolvedValue(emptyThread)
  vi.mocked(api.sendAssistantMessage).mockResolvedValue({
    ...emptyThread,
    title: '什么是审计抽样？',
    messages: [
      {
        id: 'message-user',
        role: 'user',
        content: '什么是审计抽样？',
        scope: 'general',
        preset: 'knowledge',
        source_kinds: [],
        citations: [],
        prompt_version: null,
        model_provider: null,
        actual_model: null,
        model_call_id: null,
        created_at: '2026-09-24T00:00:00Z',
      },
      {
        id: 'message-assistant',
        role: 'assistant',
        content: '[通用知识] 当前使用本地模拟服务。',
        scope: 'general',
        preset: 'knowledge',
        source_kinds: ['general_knowledge', 'local_simulation'],
        citations: [],
        prompt_version: 'assistant-system.v1',
        model_provider: 'Fake Provider',
        actual_model: 'fake-structured-v1',
        model_call_id: 'call-1',
        created_at: '2026-09-24T00:00:00Z',
      },
    ],
  })
})

test('opens from the bottom and supports project-external general questions', async () => {
  const user = userEvent.setup()
  render(
    <AssistantPanel
      project={project}
      currentDocument={null}
      selectedEvidence={[]}
      strictOffline
      onOpenCitation={vi.fn()}
      onRiskCreated={vi.fn()}
    />,
  )

  const launcher = screen.getByRole('button', { name: /AI 审计助手/ })
  expect(launcher).toHaveTextContent('智能组合 · 联网关闭')
  await user.click(launcher)

  expect(screen.getByRole('complementary', { name: 'AI 审计助手' })).toBeVisible()
  expect(screen.getByText(/通用知识可询问；联网检索未启用/)).toBeVisible()

  await user.selectOptions(screen.getByLabelText('回答范围'), 'general')
  await user.click(screen.getByRole('button', { name: '专业问答' }))
  const input = screen.getByLabelText('向 AI 审计助手提问')
  await user.clear(input)
  await user.type(input, '什么是审计抽样？')
  await user.click(screen.getByRole('button', { name: /发送/ }))

  await waitFor(() => expect(api.sendAssistantMessage).toHaveBeenCalledWith(
    'project-1',
    'thread-1',
    expect.objectContaining({
      content: '什么是审计抽样？',
      scope: 'general',
      preset: 'knowledge',
      include_history: false,
    }),
  ))
  expect(await screen.findByText('[通用知识] 当前使用本地模拟服务。')).toBeVisible()
  expect(screen.getByText('通用知识', { selector: '.assistant-source-kinds span' })).toBeVisible()
  expect(screen.getByText('本地模拟', { selector: '.assistant-source-kinds span' })).toBeVisible()

  await user.keyboard('{Escape}')
  expect(screen.getByRole('button', { name: /AI 审计助手/ })).toHaveFocus()
  await user.keyboard('{Control>}/{/Control}')
  expect(screen.getByLabelText('向 AI 审计助手提问')).toHaveFocus()
})

test('requires explicit confirmation before creating a note or risk draft', async () => {
  const user = userEvent.setup()
  const onRiskCreated = vi.fn()
  const tracedThread: AssistantThread = {
    ...emptyThread,
    messages: [
      {
        id: 'question-1',
        role: 'user',
        content: '这项收入确认是否异常？',
        scope: 'project',
        preset: 'free',
        source_kinds: [],
        citations: [],
        prompt_version: null,
        model_provider: null,
        actual_model: null,
        model_call_id: null,
        created_at: '2026-09-24T00:00:00Z',
      },
      {
        id: 'answer-1',
        role: 'assistant',
        content: '建议核对期后回款和合同履约节点。',
        scope: 'project',
        preset: 'free',
        source_kinds: ['project_evidence', 'local_simulation'],
        citations: [{
          source_kind: 'document',
          label: '收入合同 · 第 3 页',
          document_id: 'document-1',
          document_name: '收入合同.pdf',
          page_number: 3,
          block_number: 2,
          note_id: null,
          quote: '验收后确认收入',
          parse_method: 'native',
          parse_version: '1',
        }],
        prompt_version: 'assistant-system.v1',
        model_provider: 'Fake Provider',
        actual_model: 'fake-structured-v1',
        model_call_id: 'call-1',
        created_at: '2026-09-24T00:00:00Z',
      },
    ],
  }
  vi.mocked(api.listAssistantThreads).mockResolvedValue([tracedThread])
  vi.mocked(api.createNote).mockResolvedValue({} as never)
  vi.mocked(api.createRisk).mockResolvedValue({ risk_number: 'RISK-009' } as RiskRecord)
  vi.spyOn(window, 'confirm').mockReturnValue(true)

  render(
    <AssistantPanel
      project={project}
      currentDocument={null}
      selectedEvidence={[]}
      strictOffline
      onOpenCitation={vi.fn()}
      onRiskCreated={onRiskCreated}
    />,
  )
  await user.click(screen.getByRole('button', { name: /AI 审计助手/ }))
  await screen.findByText('建议核对期后回款和合同履约节点。')

  await user.click(screen.getByRole('button', { name: '添加到备忘录' }))
  await waitFor(() => expect(api.createNote).toHaveBeenCalledWith('project-1', expect.objectContaining({
    title: 'AI 对话草稿：这项收入确认是否异常？',
    model_readable: false,
    pages: [{ document_id: 'document-1', page_number: 3 }],
  })))

  await user.click(screen.getByRole('button', { name: '创建风险草稿' }))
  await waitFor(() => expect(api.createRisk).toHaveBeenCalledWith('project-1', expect.objectContaining({
    risk_type: 'AI 对话线索',
    evidence: [expect.objectContaining({
      document_id: 'document-1',
      page_number: 3,
      block_number: 2,
      quote: '验收后确认收入',
    })],
  })))
  expect(onRiskCreated).toHaveBeenCalledWith(expect.objectContaining({ risk_number: 'RISK-009' }))
  expect(window.confirm).toHaveBeenCalledTimes(2)
})
