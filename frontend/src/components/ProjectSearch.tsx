import { useEffect, useState } from 'react'
import { FilePdf, MagnifyingGlass, Warning } from '@phosphor-icons/react'
import { api } from '../api'
import type { EvidenceDirection, EvidenceSelection, SearchHit } from '../types'

interface Props {
  projectId: string
  disabled?: boolean
  onOpen: (hit: SearchHit, query: string) => void
  onSelectEvidence: (evidence: EvidenceSelection) => void
}

export function ProjectSearch({ projectId, disabled = false, onOpen, onSelectEvidence }: Props) {
  const [query, setQuery] = useState('')
  const [submittedQuery, setSubmittedQuery] = useState('')
  const [hits, setHits] = useState<SearchHit[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setQuery('')
    setSubmittedQuery('')
    setHits([])
    setError(null)
  }, [projectId])

  async function search() {
    const term = query.trim()
    if (!term || busy || disabled) return
    setBusy(true)
    setError(null)
    try {
      const nextHits = await api.searchProject(projectId, term)
      setHits(nextHits)
      setSubmittedQuery(term)
    } catch (reason) {
      setHits([])
      setSubmittedQuery(term)
      setError(reason instanceof Error ? reason.message : '项目检索失败，请重试')
    } finally {
      setBusy(false)
    }
  }

  function selectEvidence(hit: SearchHit, direction: EvidenceDirection) {
    onSelectEvidence({ ...hit, direction })
  }

  return (
    <section className="project-search" aria-labelledby="project-search-title">
      <div className="list-heading">
        <span id="project-search-title">项目全文检索</span>
        <b>本地</b>
      </div>
      <form onSubmit={(event) => { event.preventDefault(); void search() }}>
        <MagnifyingGlass aria-hidden="true" />
        <label className="sr-only" htmlFor="project-search-input">搜索全部本地文档</label>
        <input
          id="project-search-input"
          type="search"
          maxLength={200}
          placeholder="原文、金额或文件名"
          value={query}
          disabled={disabled}
          onChange={(event) => setQuery(event.target.value)}
        />
        <button type="submit" disabled={disabled || busy || query.trim().length === 0}>
          {busy ? '检索中…' : '检索'}
        </button>
      </form>
      {error && <div className="project-search-message error" role="alert"><Warning aria-hidden="true" />{error}</div>}
      {!error && submittedQuery && hits.length === 0 && (
        <div className="project-search-message" role="status">
          未找到“{submittedQuery}”。可尝试完整科目名、连续金额或文件名。
        </div>
      )}
      {hits.length > 0 && (
        <div className="project-search-results" aria-live="polite" aria-label={`${hits.length} 条本地检索结果`}>
          <p>{hits.length} 条命中 · 未调用外部服务</p>
          {hits.map((hit) => (
            <article key={`${hit.document_id}-${hit.page_number}-${hit.block_number}`}>
              <button className="project-search-open" type="button" onClick={() => onOpen(hit, submittedQuery)}>
                <FilePdf aria-hidden="true" />
                <span><strong>{hit.document_name}</strong><small>第 {hit.page_number} 页 · {hit.match_kind === 'filename' ? '文件名命中' : '原文命中'}</small></span>
              </button>
              <p>{hit.snippet}</p>
              <div className="project-search-actions" aria-label={`${hit.document_name} 第 ${hit.page_number} 页证据方向`}>
                <button type="button" onClick={() => selectEvidence(hit, 'support')}>支持证据</button>
                <button type="button" onClick={() => selectEvidence(hit, 'counter')}>反证</button>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  )
}
