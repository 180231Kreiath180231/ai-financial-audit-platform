import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api'
import { DemoDataLoader } from './DemoDataLoader'

vi.mock('../api', () => ({
  api: {
    loadDemoData: vi.fn(),
  },
}))

describe('DemoDataLoader', () => {
  beforeEach(() => vi.clearAllMocks())

  it('loads the checked-in fixtures and reports the offline outcome', async () => {
    const onLoaded = vi.fn().mockResolvedValue(undefined)
    vi.mocked(api.loadDemoData).mockResolvedValue({
      queued_task_ids: ['task-1', 'task-2', 'task-3', 'task-4'],
      queued_task_count: 4,
      reused_document_count: 0,
      reused_task_count: 0,
      reused_financial_dataset: false,
      message: '已将 4 项演示资料加入本地任务队列',
      external_request: false,
    })
    const user = userEvent.setup()
    render(<DemoDataLoader projectId="project-1" onLoaded={onLoaded} />)

    await user.click(screen.getByRole('button', { name: '一键载入' }))

    expect(api.loadDemoData).toHaveBeenCalledWith('project-1')
    expect(await screen.findByRole('status')).toHaveTextContent(
      '已将 4 项演示资料加入本地任务队列；外部请求 0 次。',
    )
    expect(onLoaded).toHaveBeenCalledOnce()
  })

  it('keeps a retry action available after a recoverable error', async () => {
    vi.mocked(api.loadDemoData).mockRejectedValue(new Error('mock资料 文件夹不可用'))
    const user = userEvent.setup()
    render(<DemoDataLoader projectId="project-1" onLoaded={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: '一键载入' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('mock资料 文件夹不可用')
    await waitFor(() => expect(screen.getByRole('button', { name: '一键载入' })).toBeEnabled())
  })
})
