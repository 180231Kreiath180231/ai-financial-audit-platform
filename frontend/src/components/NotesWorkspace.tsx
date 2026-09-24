import { useEffect, useMemo, useRef, useState } from 'react'
import {
  ArrowLeft,
  CheckCircle,
  FloppyDisk,
  LinkSimple,
  Notebook,
  Plus,
  Robot,
  Trash,
  Warning,
  X,
} from '@phosphor-icons/react'
import { api } from '../api'
import type {
  AuditNotePage,
  AuditNotePayload,
  AuditNoteRecord,
  DocumentRecord,
  Project,
  RiskRecord,
} from '../types'

interface Props {
  project: Project | null
  risks: RiskRecord[]
  documents: DocumentRecord[]
  onBack: () => void
  onOpenRisk: (riskId: string) => void
  onOpenPage: (documentId: string, pageNumber: number) => void
}

interface Draft {
  title: string
  body: string
  tags: string
  modelReadable: boolean
  riskIds: string[]
  pages: AuditNotePage[]
}

const emptyDraft: Draft = {
  title: '',
  body: '',
  tags: '',
  modelReadable: false,
  riskIds: [],
  pages: [],
}

function toDraft(note: AuditNoteRecord): Draft {
  return {
    title: note.title,
    body: note.body,
    tags: note.tags.join(', '),
    modelReadable: note.model_readable,
    riskIds: note.risks.map((risk) => risk.risk_id),
    pages: note.pages,
  }
}

function toPayload(draft: Draft): AuditNotePayload {
  return {
    title: draft.title.trim(),
    body: draft.body.trim(),
    tags: draft.tags.split(/[,，]/).map((tag) => tag.trim()).filter(Boolean),
    model_readable: draft.modelReadable,
    risk_ids: draft.riskIds,
    pages: draft.pages.map(({ document_id, page_number }) => ({ document_id, page_number })),
  }
}

export function NotesWorkspace({ project, risks, documents, onBack, onOpenRisk, onOpenPage }: Props) {
  const [notes, setNotes] = useState<AuditNoteRecord[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [draft, setDraft] = useState<Draft>(emptyDraft)
  const [linkDocumentId, setLinkDocumentId] = useState('')
  const [linkPage, setLinkPage] = useState(1)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<AuditNoteRecord | null>(null)
  const dialogRef = useRef<HTMLDialogElement>(null)
  const cancelRef = useRef<HTMLButtonElement>(null)

  const selected = notes.find((note) => note.id === selectedId) ?? null
  const linkDocument = documents.find((document) => document.id === linkDocumentId) ?? null
  const canSave = draft.title.trim().length > 0 && draft.body.trim().length > 0 && !busy

  useEffect(() => {
    if (!project) {
      setNotes([])
      setSelectedId(null)
      setDraft(emptyDraft)
      setLoading(false)
      return
    }
    let active = true
    setLoading(true)
    setError(null)
    void api.listNotes(project.id).then((items) => {
      if (!active) return
      setNotes(items)
      setSelectedId(items[0]?.id ?? null)
      setDraft(items[0] ? toDraft(items[0]) : emptyDraft)
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : '审计备忘录加载失败')
    }).finally(() => {
      if (active) setLoading(false)
    })
    return () => { active = false }
  }, [project])

  useEffect(() => {
    if (deleteTarget && !dialogRef.current?.open) {
      dialogRef.current?.showModal()
      window.setTimeout(() => cancelRef.current?.focus(), 0)
    } else if (!deleteTarget && dialogRef.current?.open) {
      dialogRef.current.close()
    }
  }, [deleteTarget])

  useEffect(() => {
    if (!linkDocumentId && documents[0]) setLinkDocumentId(documents[0].id)
  }, [documents, linkDocumentId])

  const linkedRiskCount = useMemo(
    () => draft.riskIds.filter((id) => risks.some((risk) => risk.id === id)).length,
    [draft.riskIds, risks],
  )

  function selectNote(note: AuditNoteRecord) {
    setSelectedId(note.id)
    setDraft(toDraft(note))
    setError(null)
    setNotice(null)
  }

  function newNote() {
    setSelectedId(null)
    setDraft(emptyDraft)
    setError(null)
    setNotice(null)
  }

  function toggleRisk(riskId: string) {
    setDraft((current) => ({
      ...current,
      riskIds: current.riskIds.includes(riskId)
        ? current.riskIds.filter((id) => id !== riskId)
        : [...current.riskIds, riskId],
    }))
  }

  function addPage() {
    if (!linkDocument || linkPage < 1 || linkPage > linkDocument.page_count) return
    if (draft.pages.some((page) => page.document_id === linkDocument.id && page.page_number === linkPage)) return
    setDraft((current) => ({
      ...current,
      pages: [...current.pages, {
        document_id: linkDocument.id,
        document_name: linkDocument.filename,
        page_number: linkPage,
      }],
    }))
  }

  async function save() {
    if (!project || !canSave) return
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const saved = selected
        ? await api.updateNote(project.id, selected.id, toPayload(draft))
        : await api.createNote(project.id, toPayload(draft))
      setNotes((current) => [saved, ...current.filter((note) => note.id !== saved.id)])
      setSelectedId(saved.id)
      setDraft(toDraft(saved))
      setNotice(selected ? '备忘录已更新。' : '备忘录已创建。')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '备忘录保存失败')
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    if (!project || !deleteTarget) return
    setBusy(true)
    setError(null)
    try {
      await api.deleteNote(project.id, deleteTarget.id)
      const remaining = notes.filter((note) => note.id !== deleteTarget.id)
      setNotes(remaining)
      setSelectedId(remaining[0]?.id ?? null)
      setDraft(remaining[0] ? toDraft(remaining[0]) : emptyDraft)
      setDeleteTarget(null)
      setNotice('备忘录已删除。')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '备忘录删除失败')
    } finally {
      setBusy(false)
    }
  }

  if (!project) return <section className="notes-page"><div className="risk-empty"><Notebook aria-hidden="true" /><h1>请先选择项目</h1></div></section>

  return (
    <section className="notes-page" aria-labelledby="notes-title">
      <header className="notes-head">
        <div>
          <button className="text-action" type="button" onClick={onBack}><ArrowLeft aria-hidden="true" />返回风险台账</button>
          <span className="section-kicker">项目工作底稿 · 人工记录</span>
          <h1 id="notes-title">审计备忘录</h1>
          <p>记录复核思路并关联风险与原始页码。模型读取默认关闭，开启仅表示允许在本项目策略范围内使用。</p>
        </div>
        <button className="button primary" type="button" disabled={loading} onClick={newNote}><Plus aria-hidden="true" />新建备忘录</button>
      </header>
      {error && <div className="notice error notes-notice" role="alert"><Warning aria-hidden="true" /><span>{error}</span></div>}
      {notice && <div className="notice success notes-notice" role="status"><CheckCircle aria-hidden="true" /><span>{notice}</span></div>}

      <div className="notes-layout">
        <aside className="notes-list" aria-label="审计备忘录列表">
          <div className="list-heading"><span>按最近更新</span><b>{notes.length}</b></div>
          {notes.length === 0 ? <div className="notes-empty"><Notebook aria-hidden="true" /><p>尚无备忘录</p><small>新建一条，记录当前复核判断。</small></div> : notes.map((note) => (
            <button key={note.id} className={`note-row ${selectedId === note.id ? 'active' : ''}`} type="button" aria-pressed={selectedId === note.id} onClick={() => selectNote(note)}>
              <span><strong>{note.title}</strong><small>{new Date(note.updated_at).toLocaleString('zh-CN')} · {note.risks.length + note.pages.length} 个关联</small></span>
              <em>{note.model_readable ? '模型可读' : '仅人工'}</em>
            </button>
          ))}
        </aside>

        {loading ? <div className="notes-loading" role="status"><span className="skeleton-line wide" /><span className="skeleton-line" />正在加载审计备忘录…</div> : <form className="note-editor" onSubmit={(event) => { event.preventDefault(); void save() }}>
          <header><div><span className="section-kicker">{selected ? '编辑备忘录' : '新建备忘录'}</span><h2>{draft.title.trim() || '未命名备忘录'}</h2></div>{selected && <button className="button danger" type="button" disabled={busy} onClick={() => setDeleteTarget(selected)}><Trash aria-hidden="true" />删除</button>}</header>
          <div className="note-fields">
            <label className="field"><span>标题</span><input aria-label="备忘录标题" maxLength={120} value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} /></label>
            <label className="field"><span>正文</span><textarea aria-label="备忘录正文" rows={8} maxLength={10000} value={draft.body} onChange={(event) => setDraft({ ...draft, body: event.target.value })} /><small>{draft.body.length}/10000</small></label>
            <label className="field"><span>标签</span><input aria-label="备忘录标签" maxLength={620} placeholder="例如：收入确认, 待访谈" value={draft.tags} onChange={(event) => setDraft({ ...draft, tags: event.target.value })} /><small>使用逗号分隔，最多 20 个标签。</small></label>
            <label className="note-model-toggle"><input type="checkbox" checked={draft.modelReadable} onChange={(event) => setDraft({ ...draft, modelReadable: event.target.checked })} /><Robot aria-hidden="true" /><span><b>允许模型读取这条备忘录</b><small>默认关闭；开启不等于外发，严格离线和项目授权仍然优先。</small></span></label>
          </div>

          <section className="note-links" aria-labelledby="note-risk-links">
            <header><LinkSimple aria-hidden="true" /><div><h3 id="note-risk-links">关联风险</h3><p>已选择 {linkedRiskCount} 项</p></div></header>
            {risks.length === 0 ? <p className="note-link-empty">当前项目尚无风险记录。</p> : <div className="note-risk-options">{risks.map((risk) => <div className="note-risk-option" key={risk.id}><label><input type="checkbox" checked={draft.riskIds.includes(risk.id)} onChange={() => toggleRisk(risk.id)} /><span><b>{risk.risk_number}</b>{risk.summary}</span></label><button type="button" onClick={() => onOpenRisk(risk.id)}>查看</button></div>)}</div>}
          </section>

          <section className="note-links" aria-labelledby="note-page-links">
            <header><LinkSimple aria-hidden="true" /><div><h3 id="note-page-links">关联文档页</h3><p>精确定位到原始页码</p></div></header>
            {documents.length === 0 ? <p className="note-link-empty">当前项目尚无可关联文档。</p> : <div className="note-page-adder"><label><span>文档</span><select aria-label="关联文档" value={linkDocumentId} onChange={(event) => { setLinkDocumentId(event.target.value); setLinkPage(1) }}>{documents.map((document) => <option key={document.id} value={document.id}>{document.filename}</option>)}</select></label><label><span>页码</span><input aria-label="关联页码" type="number" min={1} max={linkDocument?.page_count ?? 1} value={linkPage} onChange={(event) => setLinkPage(Number(event.target.value))} /></label><button className="button secondary compact" type="button" onClick={addPage}>添加页码</button></div>}
            {draft.pages.length > 0 && <div className="note-page-chips">{draft.pages.map((page) => <span key={`${page.document_id}-${page.page_number}`}><button type="button" onClick={() => onOpenPage(page.document_id, page.page_number)}>{page.document_name} · 第 {page.page_number} 页</button><button type="button" aria-label={`移除 ${page.document_name} 第 ${page.page_number} 页`} onClick={() => setDraft((current) => ({ ...current, pages: current.pages.filter((item) => item !== page) }))}><X aria-hidden="true" /></button></span>)}</div>}
          </section>

          <footer><span>{selected ? `更新于 ${new Date(selected.updated_at).toLocaleString('zh-CN')}` : '尚未保存'}</span><button className="button primary" type="submit" disabled={!canSave}><FloppyDisk aria-hidden="true" />{busy ? '保存中…' : '保存备忘录'}</button></footer>
        </form>}
      </div>

      <dialog ref={dialogRef} className="dialog confirm-dialog" onCancel={(event) => { if (busy) event.preventDefault(); else setDeleteTarget(null) }} onClose={() => { if (!busy) setDeleteTarget(null) }}>
        <div className="dialog-head"><div><span className="section-kicker">不可撤销操作</span><h2>删除备忘录？</h2></div></div>
        <div className="confirm-body"><Warning aria-hidden="true" /><p>将永久删除“{deleteTarget?.title}”及其风险、页码关联。风险和原始文档不会被删除。</p></div>
        <div className="dialog-actions"><button ref={cancelRef} className="button secondary" type="button" disabled={busy} onClick={() => setDeleteTarget(null)}>取消</button><button className="button danger" type="button" disabled={busy} onClick={() => void remove()}>{busy ? '删除中…' : '确认删除'}</button></div>
      </dialog>
    </section>
  )
}
