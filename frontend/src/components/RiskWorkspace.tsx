import { useEffect, useState } from 'react'
import {
  CheckCircle,
  ClockCounterClockwise,
  FileText,
  ListMagnifyingGlass,
  ShieldCheck,
  Sparkle,
  Warning,
} from '@phosphor-icons/react'
import type { RiskEvidence, RiskRecord, RiskStatus } from '../types'

const transitions: Record<RiskStatus, RiskStatus[]> = {
  待复核: ['已核实', '已排除', '待补证'],
  待补证: ['待复核'],
  已核实: ['已关闭'],
  已排除: [],
  已关闭: [],
}

const statusClass: Record<RiskStatus, string> = {
  待复核: 'warning',
  待补证: 'warning',
  已核实: 'success',
  已排除: 'neutral',
  已关闭: 'neutral',
}

interface Props {
  risks: RiskRecord[]
  selectedRisk: RiskRecord | null
  busy: string | null
  error: string | null
  notice: string | null
  onSelect: (riskId: string) => void
  onTransition: (risk: RiskRecord, status: RiskStatus, note: string) => Promise<boolean>
  onFakeExplanation: (risk: RiskRecord) => Promise<void>
  onOpenEvidence: (evidence: RiskEvidence) => void
}

export function RiskWorkspace({
  risks,
  selectedRisk,
  busy,
  error,
  notice,
  onSelect,
  onTransition,
  onFakeExplanation,
  onOpenEvidence,
}: Props) {
  const [note, setNote] = useState('')

  useEffect(() => setNote(''), [selectedRisk?.id, selectedRisk?.version])

  const support = selectedRisk?.evidence.filter((item) => item.direction === 'support') ?? []
  const counter = selectedRisk?.evidence.filter((item) => item.direction === 'counter') ?? []
  const allowed = selectedRisk ? transitions[selectedRisk.status] : []

  async function transition(status: RiskStatus) {
    if (!selectedRisk || note.trim().length < 2) return
    if (await onTransition(selectedRisk, status, note.trim())) setNote('')
  }

  return (
    <section className="risk-page" aria-labelledby="risk-page-title">
      <header className="risk-page-head">
        <div><span className="section-kicker">迭代四 · 人工最终决策</span><h1 id="risk-page-title">风险台账</h1><p>人工证据与确定性财务规则都只生成“待评估”草稿；最终风险判断和状态变更由复核人员完成。</p></div>
        <div className="risk-metrics" aria-label="风险状态统计">
          <span><b>{risks.length}</b>全部</span>
          <span><b>{risks.filter((risk) => risk.status === '待复核').length}</b>待复核</span>
          <span><b>{risks.filter((risk) => risk.status === '已核实').length}</b>已核实</span>
        </div>
      </header>
      {error && <div className="notice error risk-notice" role="alert"><Warning aria-hidden="true" /><span>{error}</span></div>}
      {notice && <div className="notice success risk-notice" role="status"><CheckCircle aria-hidden="true" /><span>{notice}</span></div>}

      {risks.length === 0 ? (
        <div className="risk-empty"><ListMagnifyingGlass aria-hidden="true" /><h2>尚无风险草稿</h2><p>在“资料”中搜索原文，将命中块标记为支持证据或反证，再从处置面板创建人工风险草稿。</p></div>
      ) : (
        <div className="risk-layout">
          <aside className="risk-list" aria-label="风险清单">
            <div className="list-heading"><span>按最近更新</span><b>{risks.length}</b></div>
            {risks.map((risk) => (
              <button key={risk.id} className={`risk-row ${selectedRisk?.id === risk.id ? 'active' : ''}`} type="button" aria-pressed={selectedRisk?.id === risk.id} onClick={() => onSelect(risk.id)}>
                <span className="risk-row-number">{risk.risk_number}</span>
                <span><strong>{risk.summary}</strong><small>{risk.risk_type} · {risk.evidence.length} 条证据 · v{risk.version}</small></span>
                <span className={`risk-status ${statusClass[risk.status]}`}>{risk.status}</span>
              </button>
            ))}
          </aside>

          <article className="risk-detail" aria-live="polite">
            {selectedRisk ? (
              <>
                <header className="risk-detail-head">
                  <div><span className="section-kicker">{selectedRisk.risk_number} · {selectedRisk.risk_type}</span><h2>{selectedRisk.summary}</h2></div>
                  <div className="risk-detail-state"><span className={`risk-status ${statusClass[selectedRisk.status]}`}>{selectedRisk.status}</span><span>{selectedRisk.risk_level}</span><span>版本 {selectedRisk.version}</span></div>
                </header>

                <section className="risk-detail-section" aria-labelledby="basis-heading">
                  <div className="risk-section-title"><FileText aria-hidden="true" /><div><h3 id="basis-heading">判断依据</h3><p>{selectedRisk.trigger_rule_id} / {selectedRisk.trigger_rule_version} · {selectedRisk.trigger_rule_id === 'MANUAL-DRAFT' ? '人工证据草稿' : '本地确定性规则草稿'}</p></div></div>
                  {selectedRisk.trigger_rule_id !== 'MANUAL-DRAFT' && <dl className="rule-calculation risk-rule-calculation">
                    <div><dt>输入值</dt><dd>{formatValues(selectedRisk.input_values)}</dd></div>
                    <div><dt>比较基准</dt><dd>{formatValues(selectedRisk.baseline_values)}</dd></div>
                    <div><dt>计算结果</dt><dd>{formatValues(selectedRisk.calculation_result)}</dd></div>
                  </dl>}
                  <div className="evidence-columns">
                    <EvidenceGroup title="支持证据" items={support} onOpen={onOpenEvidence} />
                    <EvidenceGroup title="反证" items={counter} onOpen={onOpenEvidence} />
                  </div>
                </section>

                <section className="risk-detail-section" aria-labelledby="explanation-heading">
                  <div className="risk-section-title"><Sparkle aria-hidden="true" /><div><h3 id="explanation-heading">AI 解释</h3><p>{selectedRisk.actual_model ? `${selectedRisk.model_provider} / ${selectedRisk.actual_model}` : '尚未生成 · 仅允许 Fake Provider'}</p></div></div>
                  {selectedRisk.model_explanation ? <div className="model-draft"><p>{selectedRisk.model_explanation}</p><small>{selectedRisk.uncertainty}</small></div> : selectedRisk.status === '待复核' ? <button className="button secondary" type="button" disabled={busy !== null} onClick={() => void onFakeExplanation(selectedRisk)}><Sparkle aria-hidden="true" />生成合成解释草稿</button> : <div className="completed-note" role="status"><ShieldCheck aria-hidden="true" /><span><b>当前状态不允许生成解释</b>{selectedRisk.status === '待补证' ? '完成补证并重新进入待复核后再生成。' : '人工确认后的风险不会被新的模型内容静默改变。'}</span></div>}
                </section>

                <section className="risk-detail-section" aria-labelledby="action-heading">
                  <div className="risk-section-title"><ShieldCheck aria-hidden="true" /><div><h3 id="action-heading">人工处置</h3><p>状态变更必须填写备注，并生成新的不可覆盖版本。</p></div></div>
                  {allowed.length > 0 ? <>
                    <label className="field"><span>复核备注</span><textarea aria-label="复核备注" rows={3} maxLength={500} value={note} onChange={(event) => setNote(event.target.value)} placeholder="记录核对过程、判断依据或待补资料" /><small>{note.length}/500 · 至少 2 个字符</small></label>
                    <div className="risk-actions">{allowed.map((status) => <button key={status} className={status === '已核实' ? 'button primary' : 'button secondary'} type="button" disabled={busy !== null || note.trim().length < 2} onClick={() => void transition(status)}>转为{status}</button>)}</div>
                  </> : <div className="completed-note"><CheckCircle aria-hidden="true" /><span><b>当前状态没有后续动作</b>历史版本仍可在下方查看。</span></div>}
                </section>

                <section className="risk-detail-section" aria-labelledby="history-heading">
                  <div className="risk-section-title"><ClockCounterClockwise aria-hidden="true" /><div><h3 id="history-heading">版本历史</h3><p>最新版本在前；历史快照不会被状态变更覆盖。</p></div></div>
                  <ol className="risk-history">{selectedRisk.versions.map((version) => <li key={version.version}><b>v{version.version}</b><span>{version.change_reason}</span><time dateTime={version.created_at}>{new Date(version.created_at).toLocaleString('zh-CN')}</time></li>)}</ol>
                </section>
              </>
            ) : <div className="risk-empty"><ListMagnifyingGlass aria-hidden="true" /><h2>选择一张风险卡</h2><p>查看证据链、合成解释、人工处置和版本历史。</p></div>}
          </article>
        </div>
      )}
    </section>
  )
}

function EvidenceGroup({ title, items, onOpen }: { title: string; items: RiskEvidence[]; onOpen: (evidence: RiskEvidence) => void }) {
  return (
    <div className="evidence-group">
      <div className="list-heading"><span>{title}</span><b>{items.length}</b></div>
      {items.length === 0 ? <p className="evidence-empty">未关联</p> : items.map((item) => (
        <button key={item.id} type="button" onClick={() => onOpen(item)}>
          <span>{item.kind === 'financial' ? `${item.document_name} · CSV 行 ${item.line_start}${item.line_end !== item.line_start ? `–${item.line_end}` : ''}` : `${item.document_name} · 第 ${item.page_number} 页`}</span>
          <q>{item.quote}</q>
          <small>{item.kind === 'financial' ? `${item.period_key} · 点击查看规则行级证据` : `${item.parse_method} / ${item.parse_version} · 块 ${item.block_number}`}</small>
        </button>
      ))}
    </div>
  )
}

function formatValues(values: Record<string, unknown>) {
  return Object.entries(values).map(([key, value]) => `${key}：${String(value)}`).join(' · ') || '无'
}
