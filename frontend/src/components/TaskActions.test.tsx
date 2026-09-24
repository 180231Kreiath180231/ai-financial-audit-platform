import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { TaskRecord } from '../types'
import { TaskActions } from './TaskActions'

const baseTask: TaskRecord = {
  id: 'task-resource',
  task_type: 'pdf_import',
  filename: 'resource.pdf',
  status: 'paused',
  pause_reason: 'resource',
  progress: 35,
  current_step: '因整机 CPU 负载自动暂停，低于 30% 持续 10 秒后恢复',
  error_code: null,
  error_message: null,
  next_action: null,
  result_kind: null,
  document_id: null,
  dataset_id: null,
  created_at: '2026-09-23T00:00:00Z',
  updated_at: '2026-09-23T00:00:10Z',
}

describe('TaskActions', () => {
  it('shows resource pauses as an automatic read-only recovery state', () => {
    render(<TaskActions task={baseTask} onChange={vi.fn()} />)

    expect(screen.getByRole('status')).toHaveTextContent('低于 30% 持续 10 秒后自动继续')
    expect(screen.queryByRole('button', { name: '继续处理' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '取消任务' })).toBeVisible()
  })

  it('keeps manual resume available for a user pause', () => {
    const onChange = vi.fn()
    const task = { ...baseTask, id: 'task-user', pause_reason: 'user' as const }
    render(<TaskActions task={task} onChange={onChange} />)

    fireEvent.click(screen.getByRole('button', { name: '继续处理' }))
    expect(onChange).toHaveBeenCalledWith(task, 'resume')
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })
})
