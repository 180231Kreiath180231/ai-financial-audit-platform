import { useEffect, useMemo, useState } from 'react'
import { ChartLine, CheckCircle, Warning } from '@phosphor-icons/react'
import { api } from '../api'
import type { FinancialTrendAccount, FinancialTrendAnalysis } from '../types'

interface Props {
  projectId: string
  datasetId: string
}

const qualityLabel = {
  insufficient: '样本不足',
  limited: '小样本',
  expanded: '扩展样本',
}

const directionLabel = {
  up: '连续上升',
  down: '连续下降',
  flat: '持平',
}

function formatNumber(value: string | null, suffix = '') {
  if (value === null) return '—'
  return `${Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}${suffix}`
}

export function FinancialTrendPanel({ projectId, datasetId }: Props) {
  const [accounts, setAccounts] = useState<FinancialTrendAccount[]>([])
  const [accountCode, setAccountCode] = useState('')
  const [denominatorCode, setDenominatorCode] = useState('')
  const [analysis, setAnalysis] = useState<FinancialTrendAnalysis | null>(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    setBusy(true)
    setError(null)
    void api.financialTrendAccounts(projectId, datasetId).then((items) => {
      if (!active) return
      setAccounts(items)
      setAccountCode((current) => items.some((item) => item.account_code === current) ? current : items[0]?.account_code ?? '')
      setDenominatorCode((current) => items.some((item) => item.account_code === current) ? current : '')
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : '趋势科目加载失败')
    }).finally(() => {
      if (active) setBusy(false)
    })
    return () => { active = false }
  }, [datasetId, projectId])

  useEffect(() => {
    if (!accountCode) {
      setAnalysis(null)
      return
    }
    let active = true
    setBusy(true)
    setError(null)
    setAnalysis(null)
    void api.financialTrendAnalysis(projectId, datasetId, accountCode, denominatorCode).then((next) => {
      if (active) setAnalysis(next)
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : '趋势统计加载失败')
    }).finally(() => {
      if (active) setBusy(false)
    })
    return () => { active = false }
  }, [accountCode, datasetId, denominatorCode, projectId])

  const signalCount = useMemo(
    () => analysis?.points.filter((point) => point.signals.length > 0).length ?? 0,
    [analysis],
  )

  return <section className="trend-panel" aria-labelledby="trend-panel-title">
    <header className="trend-panel-head">
      <div><ChartLine aria-hidden="true" /><div><h3 id="trend-panel-title">趋势与稳健统计</h3><p>所有金额由本地代码按期末借方减期末贷方计算；统计信号不直接确定风险等级。</p>{analysis && <code>{analysis.analysis_version}</code>}</div></div>
      <div className="trend-selectors">
        <label><span>分析科目</span><select aria-label="趋势分析科目" value={accountCode} onChange={(event) => setAccountCode(event.target.value)}>{accounts.map((account) => <option key={account.account_code} value={account.account_code}>{account.account_code} · {account.account_name}（{account.period_count} 期）</option>)}</select></label>
        <label><span>结构占比基准</span><select aria-label="结构占比基准" value={denominatorCode} onChange={(event) => setDenominatorCode(event.target.value)}><option value="">不计算结构占比</option>{accounts.map((account) => <option key={account.account_code} value={account.account_code}>{account.account_code} · {account.account_name}</option>)}</select><small>请选择资产、收入或费用总计科目；系统不自动推断会计口径。</small></label>
      </div>
    </header>

    {error && <div className="notice error trend-notice" role="alert"><Warning aria-hidden="true" /><span>{error}</span></div>}
    {busy && !analysis && <div className="trend-loading" role="status"><span className="skeleton-line wide" /><span className="skeleton-line" />正在执行本地统计…</div>}
    {!busy && accounts.length === 0 && <div className="trend-empty"><ChartLine aria-hidden="true" /><h3>没有可分析科目</h3><p>当前数据集尚无已入库的科目期间数据。</p></div>}

    {analysis && <>
      <div className="trend-guard" role="note"><Warning aria-hidden="true" /><span><b>{qualityLabel[analysis.sample_quality]} · {analysis.sample_count} 期</b>{analysis.uncertainty}{analysis.missing_periods.length > 0 && ` 缺失期间：${analysis.missing_periods.join('、')}。`}</span></div>
      <section className="trend-metrics" aria-label="稳健统计摘要">
        <div><span>中位数</span><strong>{formatNumber(analysis.median)}</strong><small>{analysis.currency} · 期末净额</small></div>
        <div><span>MAD</span><strong>{formatNumber(analysis.mad)}</strong><small>绝对偏差中位数</small></div>
        <div><span>均值</span><strong>{formatNumber(analysis.mean)}</strong><small>仅用于标准 Z-score</small></div>
        <div><span>标准差</span><strong>{formatNumber(analysis.standard_deviation)}</strong><small>{signalCount} 期存在辅助信号</small></div>
      </section>
      <TrendChart analysis={analysis} />
      <div className="trend-table-wrap">
        <table>
          <caption>趋势精确值；{analysis.value_basis}</caption>
          <thead><tr><th scope="col">期间</th><th scope="col">期末净额</th><th scope="col">同比增减</th><th scope="col">同比</th><th scope="col">连续趋势</th><th scope="col">MAD 稳健 Z</th><th scope="col">标准 Z</th><th scope="col">结构占比</th><th scope="col">辅助信号</th></tr></thead>
          <tbody>{analysis.points.map((point) => <tr key={point.period_key} className={point.signals.length ? 'has-signal' : ''}><th scope="row">{point.period_key}</th><td>{formatNumber(point.closing_net)}</td><td>{formatNumber(point.yoy_change)}</td><td>{formatNumber(point.yoy_percent, '%')}</td><td>{point.direction ? `${directionLabel[point.direction]}${point.trend_run > 0 ? ` ${point.trend_run} 期` : ''}` : '无连续基准'}</td><td>{formatNumber(point.robust_z_score)}</td><td>{formatNumber(point.z_score)}</td><td>{formatNumber(point.structure_ratio, '%')}</td><td>{point.signals.join('；') || '—'}</td></tr>)}</tbody>
        </table>
      </div>
      {analysis.denominator && <div className="trend-denominator"><CheckCircle aria-hidden="true" /><span><b>结构占比分母：</b>{analysis.denominator.account_code} · {analysis.denominator.account_name}；{analysis.denominator.basis}。分母为零或当期缺失时显示“—”。</span></div>}
    </>}
  </section>
}

function TrendChart({ analysis }: { analysis: FinancialTrendAnalysis }) {
  const values = analysis.points.map((point) => Number(point.closing_net))
  const minimum = Math.min(...values)
  const maximum = Math.max(...values)
  const range = maximum - minimum || 1
  const left = 54
  const top = 22
  const plotWidth = 672
  const plotHeight = 142
  const coordinates = analysis.points.map((point, index) => ({
    point,
    x: left + (analysis.points.length === 1 ? plotWidth / 2 : index * plotWidth / (analysis.points.length - 1)),
    y: top + (maximum - Number(point.closing_net)) / range * plotHeight,
  }))
  const summary = `${analysis.account.account_code} ${analysis.account.account_name}，${analysis.points.length} 个期间，期末净额从 ${formatNumber(analysis.points[0]?.closing_net ?? null)} 变为 ${formatNumber(analysis.points.at(-1)?.closing_net ?? null)}，${analysis.points.filter((point) => point.signals.length).length} 期存在辅助信号。`
  const tickStep = Math.max(1, Math.ceil(coordinates.length / 6))

  return <figure className="trend-chart">
    <figcaption><strong>{analysis.account.account_code} · {analysis.account.account_name}</strong><span>{summary}</span></figcaption>
    <svg viewBox="0 0 780 205" role="img" aria-label={summary}>
      {[0, 0.5, 1].map((ratio) => <line key={ratio} x1={left} x2={left + plotWidth} y1={top + plotHeight * ratio} y2={top + plotHeight * ratio} className="trend-gridline" />)}
      <text x="4" y={top + 4}>{formatNumber(String(maximum))}</text>
      <text x="4" y={top + plotHeight + 4}>{formatNumber(String(minimum))}</text>
      {coordinates.length > 1 && <polyline points={coordinates.map(({ x, y }) => `${x},${y}`).join(' ')} className="trend-line" />}
      {coordinates.map(({ point, x, y }, index) => <g key={point.period_key}><circle cx={x} cy={y} r={point.signals.length ? 6 : 4} className={point.signals.length ? 'trend-point signal' : 'trend-point'}><title>{point.period_key}：{formatNumber(point.closing_net)}{point.signals.length ? `；${point.signals.join('；')}` : ''}</title></circle>{(index % tickStep === 0 || index === coordinates.length - 1) && <text x={x} y="191" textAnchor="middle">{point.period_key}</text>}</g>)}
    </svg>
  </figure>
}
