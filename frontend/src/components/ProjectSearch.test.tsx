import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api'
import type { DocumentRecord, SearchHit } from '../types'
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
  fiscal_year: 2025,
  entity_name: '合成测试主体',
  document_type: '年度报告',
  account_names: ['营业收入'],
}

const document: DocumentRecord = {
  id: 'doc-1', filename: '合成年度报告.pdf', sha256: 'a'.repeat(64), size_bytes: 128,
  page_count: 7, parse_method: 'native_pdf', parse_version: 'test-v1', created_at: '2026-09-22T00:00:00Z',
  native_page_count: 7, scan_page_count: 0, vision_page_count: 0, external_vision_page_count: 0,
  vision_status: 'not_required', fiscal_year: 2025, entity_name: '合成测试主体', document_type: '年度报告',
  account_names: ['营业收入'], metadata_version: 1, metadata_updated_at: '2026-09-22T00:00:00Z',
}

const baseProps = {
  projectId: 'project-1', documents: [document], yearStart: 2024, yearEnd: 2025,
  onOpen: vi.fn(), onSelectEvidence: vi.fn(), onDocumentUpdated: vi.fn(),
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
        {...baseProps}
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
        {...baseProps}
      />,
    )

    await user.type(screen.getByRole('searchbox', { name: '搜索全部本地文档' }), '不存在的词')
    await user.click(screen.getByRole('button', { name: '检索' }))

    expect(await screen.findByRole('status')).toHaveTextContent('可清除部分筛选，或尝试完整科目名')
  })

  it('submits structured filters without requiring a keyword and can clear them', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'searchProject').mockResolvedValue([{ ...hit, match_kind: 'metadata' }])
    render(<ProjectSearch {...baseProps} />)

    await user.click(screen.getByText('结构化筛选'))
    await user.selectOptions(screen.getByLabelText('文档'), 'doc-1')
    await user.click(screen.getByRole('button', { name: '检索' }))

    expect(api.searchProject).toHaveBeenCalledWith('project-1', '', expect.objectContaining({ document_id: 'doc-1' }))
    expect(await screen.findByText('1 条命中 · 1 项筛选 · 未调用外部服务')).toBeVisible()
    await user.click(screen.getByText('结构化筛选'))
    await user.click(screen.getByRole('button', { name: '清除筛选' }))
    expect(screen.getByRole('button', { name: '检索' })).toBeDisabled()
  })

  it('saves explicit document metadata and reports the new version', async () => {
    const user = userEvent.setup()
    const onDocumentUpdated = vi.fn()
    vi.spyOn(api, 'updateDocumentMetadata').mockResolvedValue({ ...document, metadata_version: 2, document_type: '专项报告' })
    render(<ProjectSearch {...baseProps} onDocumentUpdated={onDocumentUpdated} />)

    await user.click(screen.getByText('结构化筛选'))
    await user.selectOptions(screen.getByLabelText('文档'), 'doc-1')
    await user.click(screen.getByRole('button', { name: '编辑所选文档标注' }))
    const typeInput = screen.getByLabelText('文档类型', { selector: '.document-metadata-editor input' })
    await user.clear(typeInput)
    await user.type(typeInput, '专项报告')
    await user.click(screen.getByRole('button', { name: '保存标注' }))

    expect(await screen.findByRole('status')).toHaveTextContent('版本 2')
    expect(onDocumentUpdated).toHaveBeenCalledWith(expect.objectContaining({ document_type: '专项报告' }))
  })
})
