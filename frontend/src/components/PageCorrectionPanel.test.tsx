import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api'
import type { PageContentRecord } from '../types'
import { PageCorrectionPanel } from './PageCorrectionPanel'

const content: PageContentRecord = {
  document_id: 'document-1',
  document_name: '扫描凭证.pdf',
  page_number: 1,
  page_width: 612,
  page_height: 792,
  blocks: [{
    block_number: 1,
    source_text: '金额 100',
    current_text: '金额 100',
    parse_method: 'fake_vision',
    parse_version: 'v1',
    bbox: { normalized_top_left: { x: 0.1, y: 0.1, width: 0.5, height: 0.1 } },
    page_width: 612,
    page_height: 792,
    block_kind: 'table_candidate',
    table_candidate: { confirmed: false },
    text_version: 1,
    corrected_at: null,
  }],
  corrections: [],
}

afterEach(() => vi.restoreAllMocks())

describe('PageCorrectionPanel', () => {
  it('discloses layout provenance and saves a versioned human correction', async () => {
    const user = userEvent.setup()
    const onCorrected = vi.fn()
    const updated: PageContentRecord = {
      ...content,
      blocks: [{
        ...content.blocks[0],
        current_text: '金额 1,000',
        text_version: 2,
        corrected_at: '2026-09-25T00:00:00Z',
      }],
      corrections: [{
        id: 'correction-1',
        document_id: 'document-1',
        page_number: 1,
        block_number: 1,
        version: 2,
        before_text: '金额 100',
        after_text: '金额 1,000',
        change_reason: '对照来源页人工校正',
        source: 'human',
        created_at: '2026-09-25T00:00:00Z',
      }],
    }
    vi.spyOn(api, 'getPageContent')
      .mockResolvedValueOnce(content)
      .mockResolvedValueOnce(updated)
    vi.spyOn(api, 'correctPageText').mockResolvedValue(updated.corrections[0])

    render(<PageCorrectionPanel projectId="project-1" documentId="document-1" pageNumber={1} onCorrected={onCorrected} />)
    await user.click(screen.getByRole('button', { name: /版面与人工校正/ }))

    expect(await screen.findByText('1 个表格候选')).toBeVisible()
    const textarea = screen.getByRole('textbox', { name: /当前有效文本/ })
    await user.clear(textarea)
    await user.type(textarea, '金额 1,000')
    await user.click(screen.getByRole('button', { name: '保存人工校正' }))

    expect(api.correctPageText).toHaveBeenCalledWith('project-1', 'document-1', 1, {
      block_number: 1,
      corrected_text: '金额 1,000',
      change_reason: '对照来源页人工校正',
    })
    expect(await screen.findByRole('status')).toHaveTextContent('版本 2')
    expect(screen.getByText('块 1 · v2')).toBeVisible()
    expect(screen.getByText('不可变来源文本')).toBeVisible()
    expect(onCorrected).toHaveBeenCalledOnce()
  })
})
