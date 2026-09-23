import { useEffect, useState } from 'react'
import { ArrowClockwise, Brain, CaretDown, FilePdf, Funnel, MagnifyingGlass, PencilSimple, TextAlignLeft, Warning, X } from '@phosphor-icons/react'
import { api } from '../api'
import type {
  DocumentMetadataPayload,
  DocumentRecord,
  EvidenceDirection,
  EvidenceSelection,
  ProjectSearchFilters,
  RetrievalStatus,
  SearchHit,
} from '../types'

interface Props {
  projectId: string
  documents: DocumentRecord[]
  yearStart: number
  yearEnd: number
  disabled?: boolean
  onOpen: (hit: SearchHit, query: string) => void
  onSelectEvidence: (evidence: EvidenceSelection) => void
  onDocumentUpdated: (document: DocumentRecord) => void
}

interface FilterDraft {
  documentId: string
  fiscalYear: string
  entityName: string
  accountName: string
  documentType: string
  parseMethod: string
}

const emptyFilters: FilterDraft = {
  documentId: '',
  fiscalYear: '',
  entityName: '',
  accountName: '',
  documentType: '',
  parseMethod: '',
}

function unique(values: Array<string | null>): string[] {
  return [...new Set(values.filter((value): value is string => Boolean(value)))].sort(
    (a, b) => a.localeCompare(b, 'zh-CN'),
  )
}

function toSearchFilters(filters: FilterDraft): ProjectSearchFilters {
  return {
    document_id: filters.documentId || undefined,
    fiscal_year: filters.fiscalYear ? Number(filters.fiscalYear) : undefined,
    entity_name: filters.entityName || undefined,
    account_name: filters.accountName || undefined,
    document_type: filters.documentType || undefined,
    parse_method: filters.parseMethod || undefined,
  }
}

function metadataFor(document: DocumentRecord): DocumentMetadataPayload {
  return {
    fiscal_year: document.fiscal_year,
    entity_name: document.entity_name,
    document_type: document.document_type,
    account_names: document.account_names,
  }
}

export function ProjectSearch({
  projectId,
  documents,
  yearStart,
  yearEnd,
  disabled = false,
  onOpen,
  onSelectEvidence,
  onDocumentUpdated,
}: Props) {
  const [query, setQuery] = useState('')
  const [submittedQuery, setSubmittedQuery] = useState('')
  const [filters, setFilters] = useState<FilterDraft>(emptyFilters)
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [submittedFilterCount, setSubmittedFilterCount] = useState(0)
  const [hits, setHits] = useState<SearchHit[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [editingDocumentId, setEditingDocumentId] = useState<string | null>(null)
  const [metadata, setMetadata] = useState<DocumentMetadataPayload | null>(null)
  const [metadataBusy, setMetadataBusy] = useState(false)
  const [metadataMessage, setMetadataMessage] = useState<string | null>(null)
  const [metadataError, setMetadataError] = useState(false)
  const [retrieval, setRetrieval] = useState<RetrievalStatus | null>(null)
  const [retrievalError, setRetrievalError] = useState<string | null>(null)
  const [retrievalLoading, setRetrievalLoading] = useState(true)
  const [retrievalRetry, setRetrievalRetry] = useState(0)

  useEffect(() => {
    setQuery('')
    setSubmittedQuery('')
    setFilters(emptyFilters)
    setFiltersOpen(false)
    setSubmittedFilterCount(0)
    setHits([])
    setError(null)
    setEditingDocumentId(null)
    setMetadata(null)
    setMetadataMessage(null)
    setMetadataError(false)
  }, [projectId])

  useEffect(() => {
    let active = true
    setRetrievalLoading(true)
    setRetrievalError(null)
    void api.retrievalStatus(projectId)
      .then((status) => {
        if (active) setRetrieval(status)
      })
      .catch((reason: unknown) => {
        if (!active) return
        setRetrieval(null)
        setRetrievalError(reason instanceof Error ? reason.message : '检索索引状态读取失败')
      })
      .finally(() => {
        if (active) setRetrievalLoading(false)
      })
    return () => { active = false }
  }, [projectId, documents.length, retrievalRetry])

  const activeFilterCount = Object.values(filters).filter(Boolean).length
  const selectedFilterDocument = documents.find((document) => document.id === filters.documentId)
  const entityOptions = unique(documents.map((document) => document.entity_name))
  const typeOptions = unique(documents.map((document) => document.document_type))
  const accountOptions = unique(documents.flatMap((document) => document.account_names))
  const parseOptions = unique(documents.map((document) => document.parse_method))

  async function search() {
    const term = query.trim()
    if ((!term && activeFilterCount === 0) || busy || disabled) return
    setBusy(true)
    setError(null)
    try {
      const nextHits = await api.searchProject(projectId, term, toSearchFilters(filters))
      setHits(nextHits)
      setSubmittedQuery(term)
      setSubmittedFilterCount(activeFilterCount)
      setFiltersOpen(false)
    } catch (reason) {
      setHits([])
      setSubmittedQuery(term)
      setSubmittedFilterCount(activeFilterCount)
      setError(reason instanceof Error ? reason.message : '项目检索失败，请重试')
    } finally {
      setBusy(false)
    }
  }

  function clearFilters() {
    setFilters(emptyFilters)
    setEditingDocumentId(null)
    setMetadata(null)
    setMetadataMessage(null)
    setMetadataError(false)
  }

  function beginMetadataEdit(document: DocumentRecord) {
    setFiltersOpen(true)
    setEditingDocumentId(document.id)
    setMetadata(metadataFor(document))
    setMetadataMessage(null)
    setMetadataError(false)
  }

  async function saveMetadata() {
    if (!editingDocumentId || !metadata || metadataBusy) return
    setMetadataBusy(true)
    setMetadataMessage(null)
    setMetadataError(false)
    try {
      const updated = await api.updateDocumentMetadata(projectId, editingDocumentId, metadata)
      onDocumentUpdated(updated)
      setMetadata(metadataFor(updated))
      setMetadataMessage(`标注已保存为版本 ${updated.metadata_version}，未调用外部服务。`)
    } catch (reason) {
      setMetadataError(true)
      setMetadataMessage(reason instanceof Error ? reason.message : '文档标注保存失败，请重试')
    } finally {
      setMetadataBusy(false)
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
      <div className="retrieval-readiness" aria-live="polite">
        {retrievalLoading && <span className="retrieval-readiness-loading">正在检查本地索引…</span>}
        {!retrievalLoading && retrieval && (
          <>
            <span className={retrieval.chunk_state === 'ready' ? 'ready' : ''} title={retrieval.message}>
              <TextAlignLeft aria-hidden="true" />全文 {retrieval.chunk_count} 段
            </span>
            <span className={retrieval.vector_state === 'ready' ? 'ready' : 'pending'} title={retrieval.action}>
              <Brain aria-hidden="true" />语义检索 · {retrieval.vector_state === 'ready' ? '就绪' : retrieval.vector_state === 'building' ? '构建中' : retrieval.vector_state === 'failed' ? '失败' : retrieval.vector_state === 'stale' ? '待重建' : '待配置'}
            </span>
            <small>{retrieval.external_request ? '已使用外部服务' : '未发送数据'}</small>
          </>
        )}
        {!retrievalLoading && retrievalError && (
          <div className="retrieval-readiness-error" role="alert">
            <span><Warning aria-hidden="true" />{retrievalError}</span>
            <button type="button" onClick={() => setRetrievalRetry((value) => value + 1)}><ArrowClockwise aria-hidden="true" />重试</button>
          </div>
        )}
      </div>
      <form className="project-search-bar" onSubmit={(event) => { event.preventDefault(); void search() }}>
        <MagnifyingGlass aria-hidden="true" />
        <label className="sr-only" htmlFor="project-search-input">搜索全部本地文档</label>
        <input id="project-search-input" type="search" maxLength={200} placeholder="原文、金额或文件名" value={query} disabled={disabled} onChange={(event) => setQuery(event.target.value)} />
        <button type="submit" disabled={disabled || busy || (query.trim().length === 0 && activeFilterCount === 0)}>{busy ? '检索中…' : '检索'}</button>
      </form>

      <details className="project-search-filters" open={filtersOpen} onToggle={(event) => setFiltersOpen(event.currentTarget.open)}>
        <summary><Funnel aria-hidden="true" /><span>结构化筛选</span>{activeFilterCount > 0 && <b>{activeFilterCount}</b>}<CaretDown aria-hidden="true" /></summary>
        <div className="project-search-filter-grid">
          <label><span>文档</span><select value={filters.documentId} onChange={(event) => setFilters({ ...filters, documentId: event.target.value })}><option value="">全部文档</option>{documents.map((document) => <option key={document.id} value={document.id}>{document.filename}</option>)}</select></label>
          <label><span>年度</span><input type="number" min={yearStart} max={yearEnd} placeholder={`${yearStart}–${yearEnd}`} value={filters.fiscalYear} onChange={(event) => setFilters({ ...filters, fiscalYear: event.target.value })} /></label>
          <label><span>主体</span><input list="project-search-entities" value={filters.entityName} onChange={(event) => setFilters({ ...filters, entityName: event.target.value })} /><datalist id="project-search-entities">{entityOptions.map((value) => <option key={value} value={value} />)}</datalist></label>
          <label><span>科目</span><input list="project-search-accounts" value={filters.accountName} onChange={(event) => setFilters({ ...filters, accountName: event.target.value })} /><datalist id="project-search-accounts">{accountOptions.map((value) => <option key={value} value={value} />)}</datalist></label>
          <label><span>文档类型</span><input list="project-search-types" value={filters.documentType} onChange={(event) => setFilters({ ...filters, documentType: event.target.value })} /><datalist id="project-search-types">{typeOptions.map((value) => <option key={value} value={value} />)}</datalist></label>
          <label><span>解析方式</span><select value={filters.parseMethod} onChange={(event) => setFilters({ ...filters, parseMethod: event.target.value })}><option value="">全部方式</option>{parseOptions.map((value) => <option key={value} value={value}>{value === 'native_pdf' ? '原生 PDF' : value}</option>)}</select></label>
        </div>
        <div className="project-search-filter-actions">
          <button type="button" onClick={clearFilters} disabled={activeFilterCount === 0}><X aria-hidden="true" />清除筛选</button>
          {selectedFilterDocument && <button type="button" onClick={() => beginMetadataEdit(selectedFilterDocument)}><PencilSimple aria-hidden="true" />编辑所选文档标注</button>}
        </div>

        {editingDocumentId && metadata && (
          <div className="document-metadata-editor" aria-label="文档标注编辑器">
            <div><strong>{documents.find((document) => document.id === editingDocumentId)?.filename}</strong><small>空白字段表示未标注，不会自动推断。</small></div>
            <label><span>年度</span><input type="number" min={yearStart} max={yearEnd} value={metadata.fiscal_year ?? ''} onChange={(event) => setMetadata({ ...metadata, fiscal_year: event.target.value ? Number(event.target.value) : null })} /></label>
            <label><span>主体</span><input maxLength={120} value={metadata.entity_name ?? ''} onChange={(event) => setMetadata({ ...metadata, entity_name: event.target.value || null })} /></label>
            <label><span>文档类型</span><input maxLength={80} value={metadata.document_type ?? ''} onChange={(event) => setMetadata({ ...metadata, document_type: event.target.value || null })} /></label>
            <label className="metadata-accounts"><span>科目标签</span><input maxLength={400} placeholder="多个科目用逗号分隔" value={metadata.account_names.join('，')} onChange={(event) => setMetadata({ ...metadata, account_names: event.target.value.split(/[，,]/).map((value) => value.trim()).filter(Boolean) })} /></label>
            <div className="document-metadata-actions"><button type="button" onClick={() => { setEditingDocumentId(null); setMetadata(null); setMetadataMessage(null); setMetadataError(false) }}>取消</button><button type="button" disabled={metadataBusy} onClick={() => void saveMetadata()}>{metadataBusy ? '保存中…' : '保存标注'}</button></div>
            {metadataMessage && <p className={metadataError ? 'error' : ''} role={metadataError ? 'alert' : 'status'}>{metadataMessage}</p>}
          </div>
        )}
      </details>

      {error && <div className="project-search-message error" role="alert"><Warning aria-hidden="true" />{error}</div>}
      {!error && (submittedQuery || submittedFilterCount > 0) && hits.length === 0 && <div className="project-search-message" role="status">未找到匹配资料。可清除部分筛选，或尝试完整科目名、连续金额和文件名。</div>}
      {hits.length > 0 && (
        <div className="project-search-results" aria-live="polite" aria-label={`${hits.length} 条本地检索结果`}>
          <p>{hits.length} 条命中{submittedFilterCount > 0 ? ` · ${submittedFilterCount} 项筛选` : ''} · 未调用外部服务</p>
          {hits.map((hit) => (
            <article key={`${hit.document_id}-${hit.page_number}-${hit.block_number}`}>
              <button className="project-search-open" type="button" onClick={() => onOpen(hit, submittedQuery)}><FilePdf aria-hidden="true" /><span><strong>{hit.document_name}</strong><small>第 {hit.page_number} 页 · {hit.match_kind === 'filename' ? '文件名命中' : hit.match_kind === 'metadata' ? '标注筛选' : '原文命中'}</small></span></button>
              {(hit.fiscal_year || hit.entity_name || hit.document_type || hit.account_names.length > 0) && <div className="search-hit-metadata">{hit.fiscal_year && <span>{hit.fiscal_year}</span>}{hit.entity_name && <span>{hit.entity_name}</span>}{hit.document_type && <span>{hit.document_type}</span>}{hit.account_names.map((account) => <span key={account}>{account}</span>)}</div>}
              <p>{hit.snippet || '该页暂无可提取原文，可打开 PDF 查看。'}</p>
              {hit.snippet && <div className="project-search-actions" aria-label={`${hit.document_name} 第 ${hit.page_number} 页证据方向`}><button type="button" onClick={() => selectEvidence(hit, 'support')}>支持证据</button><button type="button" onClick={() => selectEvidence(hit, 'counter')}>反证</button></div>}
            </article>
          ))}
        </div>
      )}
    </section>
  )
}
