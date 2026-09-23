import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api'
import type { SearchHit } from '../types'
import { ProjectSearch } from './ProjectSearch'

const hit: SearchHit = {
  document_id: 'doc-1',
  document_name: '合成年度报告.pdf',
  page_number: 7,
  block_number: 1,
  parse_method: 'native_pdf',
  parse_version: 'test-v1',
  snippet: '这是可固化的合成审计证据。',
  match_kind: 'content',
}

afterEach(() => vi.restoreAllMocks())

describe('ProjectSearch', () => {
  it('opens a project-wide hit and can mark it as supporting evidence', async () => {
    const user = userEvent.setup()
    const onOpen = vi.fn()
    const onSelectEvidence = vi.fn()
    vi.spyOn(api, 'searchProject').mockResolvedValue([hit])
    render(
      <ProjectSearch
        projectId="project-1"
        onOpen={onOpen}
        onSelectEvidence={onSelectEvidence}
      />,
    )

    await user.type(screen.getByRole('searchbox', { name: '搜索全部本地文档' }), '审计证据')
    await user.click(screen.getByRole('button', { name: '检索' }))

    expect(await screen.findByText('1 条命中 · 未调用外部服务')).toBeVisible()
    await user.click(screen.getByRole('button', { name: /合成年度报告\.pdf/ }))
    expect(onOpen).toHaveBeenCalledWith(hit, '审计证据')

    await user.click(screen.getByRole('button', { name: '支持证据' }))
    expect(onSelectEvidence).toHaveBeenCalledWith({ ...hit, direction: 'support' })
  })

  it('shows a useful empty result instead of a blank list', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'searchProject').mockResolvedValue([])
    render(
      <ProjectSearch
        projectId="project-1"
        onOpen={vi.fn()}
        onSelectEvidence={vi.fn()}
      />,
    )

    await user.type(screen.getByRole('searchbox', { name: '搜索全部本地文档' }), '不存在的词')
    await user.click(screen.getByRole('button', { name: '检索' }))

    expect(await screen.findByRole('status')).toHaveTextContent('可尝试完整科目名、连续金额或文件名')
  })
})
