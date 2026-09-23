import {
  Archive,
  CheckCircle,
  ClockCounterClockwise,
  FileLock,
  FileText,
  ShieldCheck,
  Warning,
} from '@phosphor-icons/react'
import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type {
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

export function OutputWorkspace({ project, risks, onOpenRisks }: Props) {
  const [snapshots, setSnapshots] = useState<OutputSnapshotSummary[]>([])
  const [selected, setSelected] = useState<OutputSnapshotDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
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

  useEffect(() => {
    let active = true
    setSnapshots([])
    setSelected(null)
    setError(null)
    setNotice(null)
    setLoading(false)
    if (!projectId || !storageAvailable) return () => { active = false }
    setLoading(true)
    api.listOutputSnapshots(projectId)
      .then(async (items) => {
        if (!active) return
        setSnapshots(items)
        if (items[0]) {
          const detail = await api.getOutputSnapshot(projectId, items[0].id)
          if (active) setSelected(detail)
        }
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : '输出快照加载失败')
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
    try {
      setSelected(await api.getOutputSnapshot(project.id, item.id))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '快照详情加载失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="output-page" aria-labelledby="output-page-title">
      <header className="output-page-head">
        <div>
          <span className="section-kicker">迭代五 · 不可变输出基础</span>
          <h1 id="output-page-title">输出快照</h1>
          <p>仅固化已核实或已关闭风险。快照保存风险版本、人工意见、规则计算、模型来源和证据编号，不随后续状态变化覆盖。</p>
        </div>
        <button
          className="button primary"
          type="button"
          disabled={!project || project.storage_available === false || confirmedCount === 0 || busy}
          aria-busy={busy}
          onClick={() => void createSnapshot()}
        >
          <FileText aria-hidden="true" />{busy ? '正在固化…' : '生成风险清单快照'}
        </button>
      </header>

      <div className="output-metrics" aria-label="输出准备状态">
        <div><span>可固化风险</span><strong>{confirmedCount}</strong><small>已核实 / 已关闭</small></div>
        <div><span>证据引用</span><strong>{evidenceCount}</strong><small>服务端已固化来源</small></div>
        <div><span>历史快照</span><strong>{snapshots.length}</strong><small>只增不覆盖</small></div>
        <div><span>文件模板</span><strong>待定</strong><small>Word / Excel / PDF</small></div>
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
              <button
                key={item.id}
                className={selected?.id === item.id ? 'active' : ''}
                type="button"
                aria-pressed={selected?.id === item.id}
                onClick={() => void openSnapshot(item)}
              >
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
              <section className="output-format-guard" aria-label="文件格式状态">
                <FileLock aria-hidden="true" />
                <div><strong>文件格式尚未生成</strong><span>快照已经可追溯；固定模板和 Word、Excel、PDF 优先级确认后再开放下载。</span></div>
                <div className="output-format-actions" aria-label="待确认的导出格式">
                  {['Word', 'Excel', 'PDF'].map((format) => <button key={format} type="button" disabled>{format}</button>)}
                </div>
              </section>
              <div className="output-risk-list">
                {selected.snapshot.risks.map((risk) => (
                  <article key={risk.risk_id}>
                    <header><span>{risk.risk_number}</span><div><strong>{risk.summary}</strong><small>{risk.risk_type} · {risk.trigger_rule_id}/{risk.trigger_rule_version} · v{risk.risk_version}</small></div><em>{risk.status}</em></header>
                    <dl><div><dt>人工意见</dt><dd>{risk.human_opinion || '未填写'}</dd></div><div><dt>不确定性</dt><dd>{risk.uncertainty}</dd></div></dl>
                    <div className="output-evidence-index"><strong>证据索引</strong>{risk.evidence.map((item) => <div key={item.citation}><code>{item.citation}</code><span><b>{item.direction === 'support' ? '支持' : '反证'} · {item.source_reference}</b><q>{item.quote}</q></span></div>)}</div>
                  </article>
                ))}
              </div>
              <footer className="output-integrity"><ShieldCheck aria-hidden="true" /><span>内容摘要、风险版本与证据引用已在本地数据库固化；外部请求 0 次。</span></footer>
            </> : <div className="output-empty"><Archive aria-hidden="true" /><h2>选择历史快照</h2></div>}
          </article>
        </div>
      )}
    </section>
  )
}
