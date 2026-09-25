import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { ProjectOverview } from './ProjectOverview'
import type { Project, ResourceSnapshot } from '../types'

const project: Project = {
  id: 'project-1',
  name: '合成年度审计',
  entity_name: '合成测试主体',
  year_start: 2024,
  year_end: 2025,
  storage_path: 'C:/synthetic/project-1',
  model_profile: 'fake-local',
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

const resources: ResourceSnapshot = {
  cpu_percent: 1,
  memory_percent: 20,
  disk_free_gb: 120,
  worker_limit: 1,
  external_api_enabled: false,
}

test('separates project overview from the document workspace', async () => {
  const user = userEvent.setup()
  const onOpenDocuments = vi.fn()

  render(
    <ProjectOverview
      project={project}
      documents={[]}
      tasks={[]}
      risks={[]}
      resources={resources}
      strictOffline
      onCreateProject={vi.fn()}
      onOpenDocuments={onOpenDocuments}
      onOpenDocument={vi.fn()}
      onOpenTask={vi.fn()}
      onOpenAnalysis={vi.fn()}
      onOpenRisks={vi.fn()}
      onOpenOutputs={vi.fn()}
    />,
  )

  expect(screen.getByRole('heading', { name: '项目概览' })).toBeVisible()
  expect(screen.getByText('从资料到工作成果')).toBeVisible()
  expect(screen.queryByRole('heading', { name: '资料队列' })).not.toBeInTheDocument()
  expect(screen.getAllByText('严格离线', { exact: true })).not.toHaveLength(0)

  await user.click(screen.getByRole('button', { name: /进入资料工作区/ }))
  expect(onOpenDocuments).toHaveBeenCalledOnce()
})
