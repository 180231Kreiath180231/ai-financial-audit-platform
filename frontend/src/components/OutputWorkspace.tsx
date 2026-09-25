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
import { useEffect, useMemo, useState, type KeyboardEvent } from 'react'
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
    materials_title: draft.materials_title,
    materials: draft.materials.map(({ id, risk_id, title, purpose, requested_scope, priority, status, responsible_party, notes }) => ({ id, risk_id, title, purpose, requested_scope, priority, status, responsible_party, notes })),
    interview_title: draft.interview_title,
    interviews: draft.interviews.map(({ id, risk_id, audience, question, objective }) => ({ id, risk_id, audience, question, objective })),
    management_title: draft.management_title,
    management: draft.management.map(({ id, risk_id, heading, summary, response_request }) => ({ id, risk_id, heading, summary, response_request })),
  }
}

function formatBytes(value: number) {
  return value < 1024 * 1024
    ? `${Math.max(1, Math.round(value / 1024))} KB`
    : `${(value / 1024 / 1024).toFixed(1)} MB`
}

function exportLabel(item: OutputExportRecord) {
  if (item.artifact_kind === 'evidence_package') return '证据包 EXCEL'
  if (item.export_format === 'docx') return 'WORD'
  if (item.export_format === 'pdf') return 'PDF'
  return '风险清单 EXCEL'
}

export function OutputWorkspace({ project, risks, onOpenRisks }: Props) {
  const [snapshots, setSnapshots] = useState<OutputSnapshotSummary[]>([])
  const [selected, setSelected] = useState<OutputSnapshotDetail | null>(null)
  const [draft, setDraft] = useState<OutputDraftRecord | null>(null)
  const [editor, setEditor] = useState<OutputDraftPayload | null>(null)
  const [exports, setExports] = useState<OutputExportRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [exportingFormat, setExportingFormat] = useState<'xlsx' | 'docx' | 'pdf' | 'evidence' | null>(null)
  const [confirmFinalize, setConfirmFinalize] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [activeSection, setActiveSection] = useState<'risks' | 'management' | 'materials' | 'interviews'>('risks')
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
  const hasGeneratedSections = Boolean(
    draft && draft.materials.length && draft.interviews.length && draft.management.length,
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
    setActiveSection('risks')
    setLoading(false)
    setExportingFormat(null)
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
      setActiveSection('risks')
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
    setActiveSection('risks')
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
      setActiveSection('risks')
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
      setNotice(`草稿已最终固化为 v${finalized.version}；现在可以生成工作成果和独立证据包。`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '草稿最终固化失败')
    } finally {
      setBusy(false)
    }
  }

  async function createExcel() {
    if (!project || !draft || draft.status !== 'finalized') return
    setBusy(true)
    setExportingFormat('xlsx')
    setError(null)
    setNotice(null)
    try {
      const created = await api.createExcelExport(project.id, draft.id)
      setExports((current) => [created, ...current])
      setNotice(`Excel 已生成：${created.filename}。历史导出未被覆盖。`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Excel 生成失败')
    } finally {
      setExportingFormat(null)
      setBusy(false)
    }
  }

  async function createWord() {
    if (!project || !draft || draft.status !== 'finalized' || !hasGeneratedSections) return
    setBusy(true)
    setExportingFormat('docx')
    setError(null)
    setNotice(null)
    try {
      const created = await api.createWordExport(project.id, draft.id)
      setExports((current) => [created, ...current])
      setNotice(`Word 已生成：${created.filename}。历史导出未被覆盖。`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Word 生成失败')
    } finally {
      setExportingFormat(null)
      setBusy(false)
    }
  }

  async function createPdf() {
    if (!project || !draft || draft.status !== 'finalized' || !hasGeneratedSections) return
    setBusy(true)
    setExportingFormat('pdf')
    setError(null)
    setNotice(null)
    try {
      const created = await api.createPdfExport(project.id, draft.id)
      setExports((current) => [created, ...current])
      setNotice(`PDF 已生成：${created.filename}。历史导出未被覆盖。`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'PDF 生成失败')
    } finally {
      setExportingFormat(null)
      setBusy(false)
    }
  }

  async function createEvidencePackage() {
    if (!project || !draft || draft.status !== 'finalized') return
    setBusy(true)
    setExportingFormat('evidence')
    setError(null)
    setNotice(null)
    try {
      const created = await api.createEvidencePackageExport(project.id, draft.id)
      setExports((current) => [created, ...current])
      setNotice(`证据包索引已生成：${created.filename}。历史导出未被覆盖。`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '证据包索引生成失败')
    } finally {
      setExportingFormat(null)
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

  function moveMaterial(index: number, offset: number) {
    if (!editor || draft?.status !== 'editing') return
    const destination = index + offset
    if (destination < 0 || destination >= editor.materials.length) return
    const materials = [...editor.materials]
    ;[materials[index], materials[destination]] = [materials[destination], materials[index]]
    setEditor({ ...editor, materials })
  }

  function moveInterview(index: number, offset: number) {
    if (!editor || draft?.status !== 'editing') return
    const destination = index + offset
    if (destination < 0 || destination >= editor.interviews.length) return
    const interviews = [...editor.interviews]
    ;[interviews[index], interviews[destination]] = [interviews[destination], interviews[index]]
    setEditor({ ...editor, interviews })
  }

  function moveManagement(index: number, offset: number) {
    if (!editor || draft?.status !== 'editing') return
    const destination = index + offset
    if (destination < 0 || destination >= editor.management.length) return
    const management = [...editor.management]
    ;[management[index], management[destination]] = [management[destination], management[index]]
    setEditor({ ...editor, management })
  }

  function moveTabFocus(event: KeyboardEvent<HTMLButtonElement>) {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
    const tabs = Array.from(
      event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]') ?? [],
    )
    const current = tabs.indexOf(event.currentTarget)
    if (current < 0) return
    event.preventDefault()
    const next = event.key === 'Home'
      ? 0
      : event.key === 'End'
        ? tabs.length - 1
        : (current + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length
    tabs[next]?.focus()
    tabs[next]?.click()
  }

  return (
    <section className="output-page" aria-labelledby="output-page-title">
      <header className="output-page-head">
        <div>
          <span className="section-kicker">管理层材料与证据包</span>
          <h1 id="output-page-title">审计输出</h1>
          <p>从已确认风险本地生成管理层沟通材料、风险清单、资料清单与访谈提纲，并从同一固化版本生成独立证据包索引。</p>
        </div>
        <button className="button primary" type="button" disabled={!project || !storageAvailable || confirmedCount === 0 || busy} aria-busy={busy} onClick={() => void createSnapshot()}>
          <FileText aria-hidden="true" />{busy ? '正在处理…' : '生成风险清单快照'}
        </button>
      </header>

      <div className="output-metrics" aria-label="输出准备状态">
        <div><span>可固化风险</span><strong>{confirmedCount}</strong><small>已核实 / 已关闭</small></div>
        <div><span>证据引用</span><strong>{evidenceCount}</strong><small>服务端锁定来源</small></div>
        <div><span>历史快照</span><strong>{snapshots.length}</strong><small>只增不覆盖</small></div>
        <div><span>草稿内容</span><strong>4 类</strong><small>管理层 / 风险 / 资料 / 访谈</small></div>
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
                  <div><strong>快照已锁定，尚未创建草稿</strong><span>创建后会本地生成管理层沟通材料、风险清单、资料清单与访谈提纲；可编辑文案和排序，证据与计算保持锁定。</span></div>
                  <button className="button secondary" type="button" disabled={busy} onClick={() => void createDraft()}>创建可编辑草稿</button>
                </section>
              ) : (
                <>
                  <section className={`output-format-guard ${draft.status === 'finalized' ? 'ready' : ''}`} aria-label="输出草稿状态">
                    {draft.status === 'finalized' ? <ShieldCheck aria-hidden="true" /> : <FileLock aria-hidden="true" />}
                    <div><strong>{draft.status === 'finalized' ? `最终草稿 v${draft.version}` : `编辑草稿 v${draft.version}${dirty ? ' · 有未保存修改' : ''}`}</strong><span>{!hasGeneratedSections ? '此草稿创建于完整成果接入前；历史内容保持不变，可从快照新建完整草稿。' : draft.status === 'finalized' ? '四类草稿内容均已锁定；当前可反复生成互不覆盖的工作成果与证据包。' : '四类内容共用保存和固化状态；先保存修改，再执行最终固化。'}</span></div>
                    <div className="output-format-actions">
                      {draft.status === 'editing' ? <>
                        <button type="button" disabled={!dirty || busy} onClick={() => void saveDraft()}><FloppyDisk aria-hidden="true" />保存</button>
                        <button type="button" disabled={dirty || busy} onClick={() => setConfirmFinalize(true)}>最终固化</button>
                      </> : <>
                        <button type="button" aria-busy={exportingFormat === 'xlsx'} disabled={busy} onClick={() => void createExcel()}>{exportingFormat === 'xlsx' ? '正在生成 Excel…' : '生成 Excel'}</button>
                        <button type="button" aria-busy={exportingFormat === 'docx'} disabled={busy || !hasGeneratedSections} title={!hasGeneratedSections ? '请从快照新建包含四类成果的草稿' : undefined} onClick={() => void createWord()}>{exportingFormat === 'docx' ? '正在生成 Word…' : '生成 Word'}</button>
                        <button type="button" aria-busy={exportingFormat === 'pdf'} disabled={busy || !hasGeneratedSections} title={!hasGeneratedSections ? '请从快照新建包含四类成果的草稿' : undefined} onClick={() => void createPdf()}>{exportingFormat === 'pdf' ? '正在生成 PDF…' : '生成 PDF'}</button>
                        <button type="button" aria-busy={exportingFormat === 'evidence'} disabled={busy} onClick={() => void createEvidencePackage()}>{exportingFormat === 'evidence' ? '正在生成证据包…' : '生成证据包'}</button>
                        <button type="button" disabled={busy} onClick={() => void createDraft()}>从快照新建草稿</button>
                      </>}
                    </div>
                  </section>

                  {confirmFinalize && draft.status === 'editing' && (
                    <div className="output-finalize-confirm" role="alert">
                      <div><strong>确认最终固化草稿 v{draft.version}？</strong><span>管理层沟通材料、风险清单、资料清单和访谈提纲将同时锁定；如需调整，可从原始快照新建草稿。</span></div>
                      <button className="button secondary" type="button" onClick={() => setConfirmFinalize(false)}>取消</button>
                      <button className="button primary" type="button" disabled={busy} onClick={() => void finalizeDraft()}>确认最终固化</button>
                    </div>
                  )}

                  <section className="output-draft-editor" aria-label="成果包基本信息">
                    <label>成果包标题<input value={editor.title} disabled={draft.status === 'finalized'} onChange={(event) => setEditor({ ...editor, title: event.target.value })} /></label>
                    <label>编制备注<textarea value={editor.notes} disabled={draft.status === 'finalized'} rows={2} placeholder="可记录编制范围、复核提示或交付说明" onChange={(event) => setEditor({ ...editor, notes: event.target.value })} /></label>
                  </section>

                  <div className="output-section-tabs" role="tablist" aria-label="成果类型">
                    <button id="output-tab-risks" type="button" role="tab" tabIndex={activeSection === 'risks' ? 0 : -1} aria-selected={activeSection === 'risks'} aria-controls="output-panel-risks" onKeyDown={moveTabFocus} onClick={() => setActiveSection('risks')}><span>风险清单</span><b>{editor.items.length}</b></button>
                    <button id="output-tab-management" type="button" role="tab" tabIndex={activeSection === 'management' ? 0 : -1} aria-selected={activeSection === 'management'} aria-controls="output-panel-management" onKeyDown={moveTabFocus} onClick={() => setActiveSection('management')}><span>管理层材料</span><b>{editor.management.length}</b></button>
                    <button id="output-tab-materials" type="button" role="tab" tabIndex={activeSection === 'materials' ? 0 : -1} aria-selected={activeSection === 'materials'} aria-controls="output-panel-materials" onKeyDown={moveTabFocus} onClick={() => setActiveSection('materials')}><span>资料清单</span><b>{editor.materials.length}</b></button>
                    <button id="output-tab-interviews" type="button" role="tab" tabIndex={activeSection === 'interviews' ? 0 : -1} aria-selected={activeSection === 'interviews'} aria-controls="output-panel-interviews" onKeyDown={moveTabFocus} onClick={() => setActiveSection('interviews')}><span>访谈提纲</span><b>{editor.interviews.length}</b></button>
                  </div>

                  <div id="output-panel-risks" role="tabpanel" aria-labelledby="output-tab-risks" hidden={activeSection !== 'risks'} className="output-risk-list">
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

                  <section id="output-panel-management" role="tabpanel" aria-labelledby="output-tab-management" hidden={activeSection !== 'management'} className="output-section-panel">
                    <header className="output-section-heading">
                      <label>材料标题<input value={editor.management_title} disabled={draft.status === 'finalized'} onChange={(event) => setEditor({ ...editor, management_title: event.target.value })} /></label>
                      <p>每项风险生成一条沟通事项。可以编辑事项摘要、需管理层回复的内容和顺序；风险等级、状态和证据编号保持锁定。</p>
                    </header>
                    {editor.management.length === 0 && <p className="output-legacy-empty">这份历史草稿不含管理层沟通材料。请从同一快照新建草稿，以生成完整内容。</p>}
                    <div className="output-generated-list">
                      {editor.management.map((item, index) => <article key={item.id}>
                        <header>
                          <code>{item.id}</code><span>{draft.management.find((source) => source.id === item.id)?.risk_number}</span>
                          <div className="output-order-actions" aria-label={`${item.id} 排序`}><button type="button" aria-label={`${item.id} 上移`} disabled={draft.status === 'finalized' || index === 0} onClick={() => moveManagement(index, -1)}><ArrowUp aria-hidden="true" /></button><button type="button" aria-label={`${item.id} 下移`} disabled={draft.status === 'finalized' || index === editor.management.length - 1} onClick={() => moveManagement(index, 1)}><ArrowDown aria-hidden="true" /></button></div>
                        </header>
                        <div className="output-generated-fields">
                          <label className="span-two">沟通事项<input value={item.heading} disabled={draft.status === 'finalized'} onChange={(event) => setEditor({ ...editor, management: editor.management.map((current) => current.id === item.id ? { ...current, heading: event.target.value } : current) })} /></label>
                          <label className="span-two">事项摘要<textarea rows={3} value={item.summary} disabled={draft.status === 'finalized'} onChange={(event) => setEditor({ ...editor, management: editor.management.map((current) => current.id === item.id ? { ...current, summary: event.target.value } : current) })} /></label>
                          <label className="span-two">需管理层回复<textarea rows={2} value={item.response_request} disabled={draft.status === 'finalized'} onChange={(event) => setEditor({ ...editor, management: editor.management.map((current) => current.id === item.id ? { ...current, response_request: event.target.value } : current) })} /></label>
                        </div>
                      </article>)}
                    </div>
                  </section>

                  <section id="output-panel-materials" role="tabpanel" aria-labelledby="output-tab-materials" hidden={activeSection !== 'materials'} className="output-section-panel">
                    <header className="output-section-heading">
                      <label>清单标题<input value={editor.materials_title} disabled={draft.status === 'finalized'} onChange={(event) => setEditor({ ...editor, materials_title: event.target.value })} /></label>
                      <p>系统按快照风险生成固定项目；可以修改用途、范围、优先级和顺序，不能新增、删除或改绑风险。</p>
                    </header>
                    {editor.materials.length === 0 && <p className="output-legacy-empty">这份历史草稿不含资料清单。请从同一快照新建草稿，以生成完整内容。</p>}
                    <div className="output-generated-list">
                      {editor.materials.map((item, index) => <article key={item.id}>
                        <header>
                          <code>{item.id}</code><span>{draft.materials.find((source) => source.id === item.id)?.risk_number}</span>
                          <div className="output-order-actions" aria-label={`${item.id} 排序`}><button type="button" aria-label={`${item.id} 上移`} disabled={draft.status === 'finalized' || index === 0} onClick={() => moveMaterial(index, -1)}><ArrowUp aria-hidden="true" /></button><button type="button" aria-label={`${item.id} 下移`} disabled={draft.status === 'finalized' || index === editor.materials.length - 1} onClick={() => moveMaterial(index, 1)}><ArrowDown aria-hidden="true" /></button></div>
                        </header>
                        <div className="output-generated-fields">
                          <label className="span-two">资料名称<input value={item.title} disabled={draft.status === 'finalized'} onChange={(event) => setEditor({ ...editor, materials: editor.materials.map((current) => current.id === item.id ? { ...current, title: event.target.value } : current) })} /></label>
                          <label className="span-two">取证用途<textarea rows={2} value={item.purpose} disabled={draft.status === 'finalized'} onChange={(event) => setEditor({ ...editor, materials: editor.materials.map((current) => current.id === item.id ? { ...current, purpose: event.target.value } : current) })} /></label>
                          <label>索取范围<input value={item.requested_scope} disabled={draft.status === 'finalized'} onChange={(event) => setEditor({ ...editor, materials: editor.materials.map((current) => current.id === item.id ? { ...current, requested_scope: event.target.value } : current) })} /></label>
                          <label>优先级<select aria-label={`${item.id} 优先级`} value={item.priority} disabled={draft.status === 'finalized'} onChange={(event) => setEditor({ ...editor, materials: editor.materials.map((current) => current.id === item.id ? { ...current, priority: event.target.value as typeof item.priority } : current) })}><option>高</option><option>中</option><option>低</option><option>待评估</option></select></label>
                          <label>状态<input value={item.status} disabled={draft.status === 'finalized'} onChange={(event) => setEditor({ ...editor, materials: editor.materials.map((current) => current.id === item.id ? { ...current, status: event.target.value } : current) })} /></label>
                          <label>责任对象<input value={item.responsible_party} disabled={draft.status === 'finalized'} onChange={(event) => setEditor({ ...editor, materials: editor.materials.map((current) => current.id === item.id ? { ...current, responsible_party: event.target.value } : current) })} /></label>
                          <label className="span-two">备注<textarea rows={2} value={item.notes} disabled={draft.status === 'finalized'} onChange={(event) => setEditor({ ...editor, materials: editor.materials.map((current) => current.id === item.id ? { ...current, notes: event.target.value } : current) })} /></label>
                        </div>
                      </article>)}
                    </div>
                  </section>

                  <section id="output-panel-interviews" role="tabpanel" aria-labelledby="output-tab-interviews" hidden={activeSection !== 'interviews'} className="output-section-panel">
                    <header className="output-section-heading">
                      <label>提纲标题<input value={editor.interview_title} disabled={draft.status === 'finalized'} onChange={(event) => setEditor({ ...editor, interview_title: event.target.value })} /></label>
                      <p>每项风险生成事实背景与证据控制两类问题；问题只作访谈准备，不构成审计结论。</p>
                    </header>
                    {editor.interviews.length === 0 && <p className="output-legacy-empty">这份历史草稿不含访谈提纲。请从同一快照新建草稿，以生成完整内容。</p>}
                    <div className="output-generated-list">
                      {editor.interviews.map((item, index) => <article key={item.id}>
                        <header>
                          <code>{item.id}</code><span>{draft.interviews.find((source) => source.id === item.id)?.risk_number}</span>
                          <div className="output-order-actions" aria-label={`${item.id} 排序`}><button type="button" aria-label={`${item.id} 上移`} disabled={draft.status === 'finalized' || index === 0} onClick={() => moveInterview(index, -1)}><ArrowUp aria-hidden="true" /></button><button type="button" aria-label={`${item.id} 下移`} disabled={draft.status === 'finalized' || index === editor.interviews.length - 1} onClick={() => moveInterview(index, 1)}><ArrowDown aria-hidden="true" /></button></div>
                        </header>
                        <div className="output-generated-fields">
                          <label>建议访谈对象<input value={item.audience} disabled={draft.status === 'finalized'} onChange={(event) => setEditor({ ...editor, interviews: editor.interviews.map((current) => current.id === item.id ? { ...current, audience: event.target.value } : current) })} /></label>
                          <label>访谈目的<input value={item.objective} disabled={draft.status === 'finalized'} onChange={(event) => setEditor({ ...editor, interviews: editor.interviews.map((current) => current.id === item.id ? { ...current, objective: event.target.value } : current) })} /></label>
                          <label className="span-two">访谈问题<textarea rows={3} value={item.question} disabled={draft.status === 'finalized'} onChange={(event) => setEditor({ ...editor, interviews: editor.interviews.map((current) => current.id === item.id ? { ...current, question: event.target.value } : current) })} /></label>
                        </div>
                      </article>)}
                    </div>
                  </section>

                  {draft.status === 'finalized' && (
                    <section className="output-export-history" aria-label="文件导出历史">
                      <div className="list-heading"><span>文件导出历史</span><b>{exports.length}</b></div>
                      {exports.length === 0 ? <p>尚未生成文件。生成后会记录模板版本、文件哈希与草稿版本。</p> : exports.map((item) => <div key={item.id}>
                        <span><strong>{item.filename}</strong><small>{exportLabel(item)} · 草稿 v{item.draft_version} · {formatBytes(item.size_bytes)} · SHA-256 {item.file_sha256.slice(0, 12)}</small></span>
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
              <footer className="output-integrity"><ShieldCheck aria-hidden="true" /><span>四类草稿与证据包索引均由风险快照本地确定性生成；版本和导出哈希保存在本地审计轨迹中，不调用外部模型。</span></footer>
            </> : <div className="output-empty"><Archive aria-hidden="true" /><h2>选择历史快照</h2></div>}
          </article>
        </div>
      )}
    </section>
  )
}
