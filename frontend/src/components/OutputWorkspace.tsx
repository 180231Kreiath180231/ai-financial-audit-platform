import {
  Archive,
  ArrowDown,
  ArrowUp,
  CheckCircle,
  ClockCounterClockwise,
  DownloadSimple,
  FileLock,
  FileText,
  FloppyDisk,
  ShieldCheck,
  Warning,
} from '@phosphor-icons/react'
import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type {
  OutputDraftPayload,
  OutputDraftRecord,
  OutputExportRecord,
  OutputSnapshotDetail,
  OutputSnapshotSummary,
  Project,
  RiskRecord,
} from '../types'

interface Props {
  project: Project | null
  risks: RiskRecord[]
  onOpenRisks: () => void
}

function payloadFromDraft(draft: OutputDraftRecord): OutputDraftPayload {
  return {
    title: draft.title,
    notes: draft.notes,
    items: draft.items.map(({ risk_id, heading, body }) => ({ risk_id, heading, body })),
  }
}

function formatBytes(value: number) {
  return value < 1024 * 1024
    ? `${Math.max(1, Math.round(value / 1024))} KB`
    : `${(value / 1024 / 1024).toFixed(1)} MB`
}

export function OutputWorkspace({ project, risks, onOpenRisks }: Props) {
  const [snapshots, setSnapshots] = useState<OutputSnapshotSummary[]>([])
  const [selected, setSelected] = useState<OutputSnapshotDetail | null>(null)
  const [draft, setDraft] = useState<OutputDraftRecord | null>(null)
  const [editor, setEditor] = useState<OutputDraftPayload | null>(null)
  const [exports, setExports] = useState<OutputExportRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [confirmFinalize, setConfirmFinalize] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const projectId = project?.id ?? null
  const storageAvailable = project?.storage_available !== false
  const confirmedCount = useMemo(
    () => risks.filter((risk) => risk.status === '已核实' || risk.status === '已关闭').length,
    [risks],
  )
  const evidenceCount = useMemo(
    () => risks
      .filter((risk) => risk.status === '已核实' || risk.status === '已关闭')
      .reduce((total, risk) => total + risk.evidence.length, 0),
    [risks],
  )
  const dirty = Boolean(
    draft && editor && JSON.stringify(editor) !== JSON.stringify(payloadFromDraft(draft)),
  )

  useEffect(() => {
    let active = true
    setSnapshots([])
    setSelected(null)
    setDraft(null)
    setEditor(null)
    setExports([])
    setError(null)
    setNotice(null)
    setLoading(false)
    if (!projectId || !storageAvailable) return () => { active = false }
    setLoading(true)
    api.listOutputSnapshots(projectId)
      .then(async (items) => {
        if (!active) return
        setSnapshots(items)
        if (!items[0]) return
        const [detail, drafts] = await Promise.all([
          api.getOutputSnapshot(projectId, items[0].id),
          api.listOutputDrafts(projectId, items[0].id),
        ])
        if (!active) return
        setSelected(detail)
        const latest = drafts[0] ?? null
        setDraft(latest)
        setEditor(latest ? payloadFromDraft(latest) : null)
        if (latest) setExports(await api.listOutputExports(projectId, latest.id))
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : '输出工作区加载失败')
      })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [projectId, storageAvailable])

  async function createSnapshot() {
    if (!project) return
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const created = await api.createRiskRegisterSnapshot(project.id)
      setSnapshots((current) => [created, ...current])
      setSelected(created)
      setDraft(null)
      setEditor(null)
      setExports([])
      setNotice(`已固化 ${created.risk_count} 项风险及其证据引用；历史快照不会被覆盖。`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '风险清单快照生成失败')
    } finally {
      setBusy(false)
    }
  }

  async function openSnapshot(item: OutputSnapshotSummary) {
    if (!project || selected?.id === item.id) return
    setLoading(true)
    setError(null)
    setNotice(null)
    setConfirmFinalize(false)
    try {
      const [detail, drafts] = await Promise.all([
        api.getOutputSnapshot(project.id, item.id),
        api.listOutputDrafts(project.id, item.id),
      ])
      const latest = drafts[0] ?? null
      setSelected(detail)
      setDraft(latest)
      setEditor(latest ? payloadFromDraft(latest) : null)
      setExports(latest ? await api.listOutputExports(project.id, latest.id) : [])
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '快照详情加载失败')
    } finally {
      setLoading(false)
    }
  }

  async function createDraft() {
    if (!project || !selected) return
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const created = await api.createOutputDraft(project.id, selected.id)
      setDraft(created)
      setEditor(payloadFromDraft(created))
      setExports([])
      setNotice('已从不可变快照创建可编辑草稿；证据与规则计算仍保持锁定。')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '输出草稿创建失败')
    } finally {
      setBusy(false)
    }
  }

  async function saveDraft() {
    if (!project || !draft || !editor) return
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const updated = await api.updateOutputDraft(project.id, draft.id, editor)
      setDraft(updated)
      setEditor(payloadFromDraft(updated))
      setNotice(`草稿已保存为 v${updated.version}，上一版本仍可追溯。`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '草稿保存失败')
    } finally {
      setBusy(false)
    }
  }

  async function finalizeDraft() {
    if (!project || !draft || dirty) return
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const finalized = await api.finalizeOutputDraft(project.id, draft.id)
      setDraft(finalized)
      setEditor(payloadFromDraft(finalized))
      setConfirmFinalize(false)
      setNotice(`草稿已最终固化为 v${finalized.version}；现在可以生成 Excel 文件。`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '草稿最终固化失败')
    } finally {
      setBusy(false)
    }
  }

  async function createExcel() {
    if (!project || !draft || draft.status !== 'finalized') return
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const created = await api.createExcelExport(project.id, draft.id)
      setExports((current) => [created, ...current])
      setNotice(`Excel 已生成：${created.filename}。历史导出未被覆盖。`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Excel 生成失败')
    } finally {
      setBusy(false)
    }
  }

  function moveItem(index: number, offset: number) {
    if (!editor || draft?.status !== 'editing') return
    const destination = index + offset
    if (destination < 0 || destination >= editor.items.length) return
    const items = [...editor.items]
    ;[items[index], items[destination]] = [items[destination], items[index]]
    setEditor({ ...editor, items })
  }

  return (
    <section className="output-page" aria-labelledby="output-page-title">
      <header className="output-page-head">
        <div>
          <span className="section-kicker">迭代五 · 草稿与 Excel 导出</span>
          <h1 id="output-page-title">审计输出</h1>
          <p>从已确认风险固化不可变快照，再编辑草稿、最终固化并生成版本化 Excel。证据、规则计算和历史文件始终保留。</p>
        </div>
        <button className="button primary" type="button" disabled={!project || !storageAvailable || confirmedCount === 0 || busy} aria-busy={busy} onClick={() => void createSnapshot()}>
          <FileText aria-hidden="true" />{busy ? '正在处理…' : '生成风险清单快照'}
        </button>
      </header>

      <div className="output-metrics" aria-label="输出准备状态">
        <div><span>可固化风险</span><strong>{confirmedCount}</strong><small>已核实 / 已关闭</small></div>
        <div><span>证据引用</span><strong>{evidenceCount}</strong><small>服务端锁定来源</small></div>
        <div><span>历史快照</span><strong>{snapshots.length}</strong><small>只增不覆盖</small></div>
        <div><span>可用格式</span><strong>Excel</strong><small>Word / PDF 后续接入</small></div>
      </div>

      {error && <div className="notice error output-notice" role="alert"><Warning aria-hidden="true" /><span>{error}</span></div>}
      {notice && <div className="notice success output-notice" role="status" aria-atomic="true"><CheckCircle aria-hidden="true" /><span>{notice}</span></div>}

      {loading && snapshots.length === 0 ? (
        <div className="output-empty" role="status"><span className="skeleton-line wide" /><span className="skeleton-line" />正在读取本地输出历史…</div>
      ) : snapshots.length === 0 ? (
        <div className="output-empty">
          <Archive aria-hidden="true" />
          <h2>{confirmedCount > 0 ? '可以生成第一份风险清单快照' : '尚无可固化风险'}</h2>
          <p>{confirmedCount > 0 ? '系统将重新校验证据完整性，并在项目数据库中保存不可变快照。' : '先在风险台账完成证据复核并将风险转为“已核实”。待复核和已排除风险不会进入输出。'}</p>
          {confirmedCount === 0 && <button className="button secondary" type="button" onClick={onOpenRisks}>前往风险台账</button>}
        </div>
      ) : (
        <div className="output-layout">
          <aside className="output-history" aria-label="输出快照历史">
            <div className="list-heading"><span>历史快照</span><b>{snapshots.length}</b></div>
            {snapshots.map((item) => (
              <button key={item.id} className={selected?.id === item.id ? 'active' : ''} type="button" aria-pressed={selected?.id === item.id} onClick={() => void openSnapshot(item)}>
                <ClockCounterClockwise aria-hidden="true" />
                <span><strong>{new Date(item.created_at).toLocaleString('zh-CN')}</strong><small>{item.risk_count} 项风险 · {item.content_sha256.slice(0, 12)}</small></span>
              </button>
            ))}
          </aside>
          <article className="output-detail" aria-live="polite">
            {selected ? <>
              <header className="output-detail-head">
                <div><span className="section-kicker">风险清单 · {selected.template_version}</span><h2>{selected.snapshot.project.name}</h2><p>{selected.snapshot.project.entity_name} · {selected.snapshot.project.year_start}—{selected.snapshot.project.year_end}</p></div>
                <code title={selected.content_sha256}>SHA-256 {selected.content_sha256.slice(0, 12)}</code>
              </header>

              {!draft || !editor ? (
                <section className="output-format-guard" aria-label="输出草稿状态">
                  <FileLock aria-hidden="true" />
                  <div><strong>快照已锁定，尚未创建草稿</strong><span>创建草稿后可以编辑标题、正文、排序和备注；证据与计算不会进入可编辑区。</span></div>
                  <button className="button secondary" type="button" disabled={busy} onClick={() => void createDraft()}>创建可编辑草稿</button>
                </section>
              ) : (
                <>
                  <section className={`output-format-guard ${draft.status === 'finalized' ? 'ready' : ''}`} aria-label="输出草稿状态">
                    {draft.status === 'finalized' ? <ShieldCheck aria-hidden="true" /> : <FileLock aria-hidden="true" />}
                    <div><strong>{draft.status === 'finalized' ? `最终草稿 v${draft.version}` : `编辑草稿 v${draft.version}${dirty ? ' · 有未保存修改' : ''}`}</strong><span>{draft.status === 'finalized' ? '内容已锁定，可以反复生成互不覆盖的 Excel 文件。' : '先保存修改，再执行最终固化；最终固化后不可继续编辑。'}</span></div>
                    <div className="output-format-actions">
                      {draft.status === 'editing' ? <>
                        <button type="button" disabled={!dirty || busy} onClick={() => void saveDraft()}><FloppyDisk aria-hidden="true" />保存</button>
                        <button type="button" disabled={dirty || busy} onClick={() => setConfirmFinalize(true)}>最终固化</button>
                      </> : <>
                        <button type="button" disabled={busy} onClick={() => void createExcel()}>生成 Excel</button>
                        <button type="button" disabled={busy} onClick={() => void createDraft()}>从快照新建草稿</button>
                        <button type="button" disabled title="将在后续迭代接入">Word</button>
                        <button type="button" disabled title="将在后续迭代接入">PDF</button>
                      </>}
                    </div>
                  </section>

                  {confirmFinalize && draft.status === 'editing' && (
                    <div className="output-finalize-confirm" role="alert">
                      <div><strong>确认最终固化草稿 v{draft.version}？</strong><span>固化后不能修改；如需调整，可从原始快照新建草稿。</span></div>
                      <button className="button secondary" type="button" onClick={() => setConfirmFinalize(false)}>取消</button>
                      <button className="button primary" type="button" disabled={busy} onClick={() => void finalizeDraft()}>确认最终固化</button>
                    </div>
                  )}

                  <section className="output-draft-editor" aria-label="风险清单草稿编辑">
                    <label>成果标题<input value={editor.title} disabled={draft.status === 'finalized'} onChange={(event) => setEditor({ ...editor, title: event.target.value })} /></label>
                    <label>编制备注<textarea value={editor.notes} disabled={draft.status === 'finalized'} rows={2} placeholder="可记录编制范围、复核提示或交付说明" onChange={(event) => setEditor({ ...editor, notes: event.target.value })} /></label>
                  </section>

                  <div className="output-risk-list">
                    {editor.items.map((item, index) => {
                      const risk = selected.snapshot.risks.find((candidate) => candidate.risk_id === item.risk_id)
                      if (!risk) return null
                      return <article key={item.risk_id}>
                        <header>
                          <span>{risk.risk_number}</span>
                          <div className="output-risk-edit-fields">
                            <label>风险标题<input value={item.heading} disabled={draft.status === 'finalized'} onChange={(event) => setEditor({ ...editor, items: editor.items.map((current) => current.risk_id === item.risk_id ? { ...current, heading: event.target.value } : current) })} /></label>
                            <label>人工编辑正文<textarea value={item.body} disabled={draft.status === 'finalized'} rows={3} onChange={(event) => setEditor({ ...editor, items: editor.items.map((current) => current.risk_id === item.risk_id ? { ...current, body: event.target.value } : current) })} /></label>
                          </div>
                          <div className="output-order-actions" aria-label={`${risk.risk_number} 排序`}>
                            <button type="button" aria-label={`${risk.risk_number} 上移`} disabled={draft.status === 'finalized' || index === 0} onClick={() => moveItem(index, -1)}><ArrowUp aria-hidden="true" /></button>
                            <button type="button" aria-label={`${risk.risk_number} 下移`} disabled={draft.status === 'finalized' || index === editor.items.length - 1} onClick={() => moveItem(index, 1)}><ArrowDown aria-hidden="true" /></button>
                          </div>
                        </header>
                        <dl><div><dt>锁定规则</dt><dd>{risk.trigger_rule_id}/{risk.trigger_rule_version} · 风险版本 v{risk.risk_version}</dd></div><div><dt>不确定性</dt><dd>{risk.uncertainty}</dd></div></dl>
                        <div className="output-evidence-index"><strong>锁定证据索引</strong>{risk.evidence.map((evidence) => <div key={evidence.citation}><code>{evidence.citation}</code><span><b>{evidence.direction === 'support' ? '支持' : '反证'} · {evidence.source_reference}</b><q>{evidence.quote}</q></span></div>)}</div>
                      </article>
                    })}
                  </div>

                  {draft.status === 'finalized' && (
                    <section className="output-export-history" aria-label="Excel 导出历史">
                      <div className="list-heading"><span>Excel 导出历史</span><b>{exports.length}</b></div>
                      {exports.length === 0 ? <p>尚未生成文件。生成后会记录模板版本、文件哈希与草稿版本。</p> : exports.map((item) => <div key={item.id}>
                        <span><strong>{item.filename}</strong><small>草稿 v{item.draft_version} · {formatBytes(item.size_bytes)} · SHA-256 {item.file_sha256.slice(0, 12)}</small></span>
                        <a className="button secondary" href={item.download_url} download={item.filename}><DownloadSimple aria-hidden="true" />下载</a>
                      </div>)}
                    </section>
                  )}
                  <section className="output-draft-versions" aria-label="草稿版本历史">
                    <div className="list-heading"><span>草稿版本历史</span><b>{draft.versions.length}</b></div>
                    {draft.versions.map((version) => <div key={version.version}>
                      <strong>v{version.version}</strong>
                      <span>{version.change_reason}</span>
                      <time dateTime={version.created_at}>{new Date(version.created_at).toLocaleString('zh-CN')}</time>
                    </div>)}
                  </section>
                </>
              )}
              <footer className="output-integrity"><ShieldCheck aria-hidden="true" /><span>风险快照、草稿版本与导出哈希均保存在本地审计轨迹中；生成过程不调用外部模型。</span></footer>
            </> : <div className="output-empty"><Archive aria-hidden="true" /><h2>选择历史快照</h2></div>}
          </article>
        </div>
      )}
    </section>
  )
}
