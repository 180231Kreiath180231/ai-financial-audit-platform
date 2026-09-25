import { useEffect, useRef, useState } from 'react'
import {
  CaretDown,
  CheckCircle,
  ClockCounterClockwise,
  PencilSimple,
  Table,
  Warning,
} from '@phosphor-icons/react'
import { api } from '../api'
import type { PageContentRecord } from '../types'

interface Props {
  projectId: string
  documentId: string
  pageNumber: number
  onCorrected?: () => void
}

export function PageCorrectionPanel({ projectId, documentId, pageNumber, onCorrected }: Props) {
  const [expanded, setExpanded] = useState(false)
  const [content, setContent] = useState<PageContentRecord | null>(null)
  const [selectedBlock, setSelectedBlock] = useState(1)
  const [draft, setDraft] = useState('')
  const [reason, setReason] = useState('对照来源页人工校正')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const errorRef = useRef<HTMLDivElement>(null)

  async function load(preferredBlock?: number) {
    setLoading(true)
    setError(null)
    try {
      const next = await api.getPageContent(projectId, documentId, pageNumber)
      setContent(next)
      const requested = preferredBlock ?? selectedBlock
      const block = next.blocks.find((item) => item.block_number === requested) ?? next.blocks[0]
      setSelectedBlock(block?.block_number ?? 1)
      setDraft(block?.current_text ?? '')
    } catch (reasonValue) {
      setError(reasonValue instanceof Error ? reasonValue.message : '页面解析内容加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    setContent(null)
    setSelectedBlock(1)
    setDraft('')
    setNotice(null)
    setError(null)
    if (expanded) void load(1)
    // Loading is intentionally tied to the selected document page and disclosure state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentId, expanded, pageNumber, projectId])

  const activeBlock = content?.blocks.find((block) => block.block_number === selectedBlock)
  const tableCandidateCount = content?.blocks.filter((block) => block.block_kind === 'table_candidate').length ?? 0

  function chooseBlock(blockNumber: number) {
    const block = content?.blocks.find((item) => item.block_number === blockNumber)
    setSelectedBlock(blockNumber)
    setDraft(block?.current_text ?? '')
    setError(null)
    setNotice(null)
  }

  async function save() {
    const normalizedReason = reason.trim()
    if (normalizedReason.length < 2) {
      setError('请填写至少 2 个字符的校正原因。')
      queueMicrotask(() => errorRef.current?.focus())
      return
    }
    if (!activeBlock || draft === activeBlock.current_text) {
      setError('请先修改当前有效文本，再保存校正。')
      queueMicrotask(() => errorRef.current?.focus())
      return
    }
    setSaving(true)
    setError(null)
    setNotice(null)
    try {
      const correction = await api.correctPageText(projectId, documentId, pageNumber, {
        block_number: selectedBlock,
        corrected_text: draft,
        change_reason: normalizedReason,
      })
      await load(selectedBlock)
      onCorrected?.()
      setNotice(`文本块 ${selectedBlock} 已保存为版本 ${correction.version}；全文索引已同步，语义索引已标记待重建。`)
    } catch (reasonValue) {
      setError(reasonValue instanceof Error ? reasonValue.message : '人工校正保存失败')
      queueMicrotask(() => errorRef.current?.focus())
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className={`page-correction${expanded ? ' expanded' : ''}`} aria-labelledby="page-correction-title">
      <button
        className="page-correction-toggle"
        type="button"
        aria-expanded={expanded}
        aria-controls="page-correction-body"
        onClick={() => setExpanded((value) => !value)}
      >
        <PencilSimple aria-hidden="true" />
        <span><b id="page-correction-title">版面与人工校正</b><small>保留来源文本、坐标和全部版本</small></span>
        <CaretDown aria-hidden="true" />
      </button>

      {expanded && <div id="page-correction-body" className="page-correction-body">
        {loading && !content && <div className="page-correction-loading" role="status">正在读取第 {pageNumber} 页版面…</div>}
        {error && <div ref={errorRef} className="page-correction-error" role="alert" tabIndex={-1}><Warning aria-hidden="true" /><span>{error}</span></div>}
        {notice && <div className="page-correction-notice" role="status"><CheckCircle aria-hidden="true" /><span>{notice}</span></div>}

        {content && <>
          <div className="page-layout-summary" aria-label="页面版面摘要">
            <span>{content.blocks.length} 个文本块</span>
            <span><Table aria-hidden="true" />{tableCandidateCount} 个表格候选</span>
            <span>第 {pageNumber} 页</span>
          </div>
          <p className="page-layout-help">表格候选只表示本地版面线索，不会自动成为审计结论；坐标不可用时仍保留准确页码。</p>

          <form onSubmit={(event) => { event.preventDefault(); void save() }}>
            {content.blocks.length > 1 && <label>
              <span>文本块</span>
              <select value={selectedBlock} onChange={(event) => chooseBlock(Number(event.target.value))}>
                {content.blocks.map((block) => <option key={block.block_number} value={block.block_number}>
                  块 {block.block_number} · {block.block_kind === 'table_candidate' ? '表格候选' : '正文'} · v{block.text_version}
                </option>)}
              </select>
            </label>}
            <label className="page-correction-text">
              <span>当前有效文本</span>
              <textarea value={draft} onChange={(event) => setDraft(event.target.value)} rows={5} maxLength={100000} disabled={saving} />
              <small>{draft.length}/100000 · 保存后会更新本地全文检索与分块，不改写来源文本。</small>
            </label>
            <label>
              <span>校正原因</span>
              <input value={reason} onChange={(event) => setReason(event.target.value)} maxLength={200} disabled={saving} aria-describedby="page-correction-reason-help" />
              <small id="page-correction-reason-help">例如：对照盖章原件、放大来源页后核实。</small>
            </label>
            {activeBlock && activeBlock.source_text !== activeBlock.current_text && <div className="page-source-text">
              <span>不可变来源文本</span>
              <p>{activeBlock.source_text || '（来源识别为空）'}</p>
            </div>}
            <div className="page-correction-actions">
              <span>{activeBlock?.bbox && Object.keys(activeBlock.bbox).length > 0 ? '已保存区域坐标' : '仅页码定位'}</span>
              <button className="button primary" type="submit" disabled={saving || loading || !activeBlock}>{saving ? '正在保存…' : '保存人工校正'}</button>
            </div>
          </form>

          <section className="page-correction-history" aria-labelledby="page-correction-history-title">
            <h3 id="page-correction-history-title"><ClockCounterClockwise aria-hidden="true" />校正历史</h3>
            {content.corrections.length === 0 ? <p>当前页面尚无人工校正。</p> : <ol>
              {content.corrections.map((correction) => <li key={correction.id}>
                <div><b>块 {correction.block_number} · v{correction.version}</b><time dateTime={correction.created_at}>{new Date(correction.created_at).toLocaleString('zh-CN')}</time></div>
                <p>{correction.change_reason}</p>
                <small>人工来源 · 修改前 {correction.before_text.length} 字符 · 修改后 {correction.after_text.length} 字符</small>
              </li>)}
            </ol>}
          </section>
        </>}
      </div>}
    </section>
  )
}
