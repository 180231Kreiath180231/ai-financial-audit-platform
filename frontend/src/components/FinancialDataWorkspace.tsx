import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type DragEvent } from 'react'
import {
  Archive,
  CheckCircle,
  Files,
  Play,
  UploadSimple,
  Warning,
  X,
} from '@phosphor-icons/react'
import { api } from '../api'
import type {
  FinancialDataset,
  FinancialEvidenceTarget,
  FinancialPreview,
  FinancialResultRows,
  FinancialRuleResult,
  Project,
  TaskRecord,
} from '../types'

interface Props {
  project: Project | null
  tasks: TaskRecord[]
  focusTarget: FinancialEvidenceTarget | null
  onRefreshProject: () => Promise<void>
}

const statusLabel = {
  pass: '通过',
  fail: '失败',
  unavailable: '无法计算',
}

function formatBytes(size: number) {
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function displayObject(value: Record<string, unknown>) {
  return Object.entries(value)
    .map(([key, item]) => `${key}：${String(item)}`)
    .join(' · ')
}

export function FinancialDataWorkspace({ project, tasks, focusTarget, onRefreshProject }: Props) {
  const [datasets, setDatasets] = useState<FinancialDataset[]>([])
  const [selectedDatasetId, setSelectedDatasetId] = useState('')
  const [detail, setDetail] = useState<FinancialDataset | null>(null)
  const [selectedResultId, setSelectedResultId] = useState('')
  const [resultRows, setResultRows] = useState<FinancialResultRows | null>(null)
  const [preview, setPreview] = useState<FinancialPreview | null>(null)
  const [busy, setBusy] = useState<'preview' | 'confirm' | 'rows' | 'archive' | 'rerun' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const [archiveConfirmId, setArchiveConfirmId] = useState<string | null>(null)
  const uploadRef = useRef<HTMLInputElement>(null)
  const errorRef = useRef<HTMLDivElement>(null)

  const financialTasks = useMemo(
    () => tasks.filter((task) => task.task_type === 'trial_balance_import'),
    [tasks],
  )
  const taskSignature = financialTasks.map((task) => `${task.id}:${task.status}:${task.progress}`).join('|')

  const loadDatasets = useCallback(async (preferredId?: string) => {
    if (!project) {
      setDatasets([])
      setSelectedDatasetId('')
      setDetail(null)
      return
    }
    try {
      const next = await api.listFinancialDatasets(project.id)
      setDatasets(next)
      setSelectedDatasetId((current) => {
        const preferred = preferredId || focusTarget?.datasetId
        if (preferred && next.some((item) => item.id === preferred)) return preferred
        if (next.some((item) => item.id === current)) return current
        return next.find((item) => item.status === 'active')?.id || next[0]?.id || ''
      })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '财务数据集加载失败')
    }
  }, [focusTarget?.datasetId, project])

  useEffect(() => {
    setPreview(null)
    setNotice(null)
    setError(null)
    void loadDatasets()
  }, [loadDatasets, project?.id])

  useEffect(() => {
    if (taskSignature) void loadDatasets()
  }, [loadDatasets, taskSignature])

  useEffect(() => {
    if (!project || !selectedDatasetId) {
      setDetail(null)
      return
    }
    let active = true
    api.getFinancialDataset(project.id, selectedDatasetId)
      .then((next) => {
        if (!active) return
        setDetail(next)
        setSelectedResultId((current) => {
          if (next.rule_results.some((result) => result.id === current)) return current
          const focused = focusTarget?.datasetId === next.id
            ? next.rule_results.find((result) => (
              result.status === 'fail'
              && (!focusTarget.periodKey || result.period_key === focusTarget.periodKey)
              && (!focusTarget.lineStart || !result.line_end || result.line_end >= focusTarget.lineStart)
              && (!focusTarget.lineEnd || !result.line_start || result.line_start <= focusTarget.lineEnd)
            ))
            : null
          return focused?.id || next.rule_results.find((result) => result.status === 'fail')?.id || next.rule_results[0]?.id || ''
        })
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : '规则结果加载失败')
      })
    return () => { active = false }
  }, [focusTarget, project, selectedDatasetId, taskSignature])

  const selectedResult = detail?.rule_results.find((result) => result.id === selectedResultId) ?? null

  const loadResultRows = useCallback(async (result: FinancialRuleResult, offset = 0) => {
    if (!project || !detail || result.affected_count === 0) {
      setResultRows(null)
      return
    }
    setBusy('rows')
    setError(null)
    try {
      const rows = await api.financialResultRows(project.id, detail.id, result.id, offset, 100)
      setResultRows(rows)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '规则明细加载失败')
      setResultRows(null)
    } finally {
      setBusy(null)
    }
  }, [detail, project])

  useEffect(() => {
    if (selectedResult) void loadResultRows(selectedResult)
    else setResultRows(null)
  }, [loadResultRows, selectedResult])

  useEffect(() => {
    if (error) errorRef.current?.focus()
  }, [error])

  async function previewFile(file: File) {
    if (!project) return
    setBusy('preview')
    setError(null)
    setNotice(null)
    setPreview(null)
    try {
      const next = await api.previewFinancialData(project.id, file)
      setPreview(next)
      if (!next.valid) setError(`发现 ${next.errors.length} 个结构问题，尚未导入。`)
      if (next.duplicate_dataset_id) {
        setNotice('文件内容与已有数据集完全一致，将复用现有版本。')
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'CSV 预览失败')
    } finally {
      setBusy(null)
    }
  }

  function inputChanged(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (file) void previewFile(file)
  }

  function dropped(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setDragging(false)
    const file = event.dataTransfer.files[0]
    if (file) void previewFile(file)
  }

  async function confirmImport() {
    if (!project || !preview?.preview_id || !preview.valid) return
    setBusy('confirm')
    setError(null)
    try {
      const result = await api.confirmFinancialData(project.id, preview.preview_id)
      if (result.reused_dataset_id) {
        setNotice('已复用相同 SHA-256 的数据集与规则结果。')
        await loadDatasets(result.reused_dataset_id)
      } else {
        setNotice('CSV 已进入本地单工作器，完成后将自动生成规则结果和待评估风险草稿。')
        await onRefreshProject()
      }
      setPreview(null)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '确认导入失败')
    } finally {
      setBusy(null)
    }
  }

  async function reuseRuleRun() {
    if (!project || !detail) return
    setBusy('rerun')
    setError(null)
    try {
      const result = await api.reuseFinancialRuleRun(project.id, detail.id)
      setNotice(`${result.message}（${result.rule_set_version}）`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '规则运行失败')
    } finally {
      setBusy(null)
    }
  }

  async function archiveDataset(datasetId: string) {
    if (!project) return
    if (archiveConfirmId !== datasetId) {
      setArchiveConfirmId(datasetId)
      return
    }
    setBusy('archive')
    setError(null)
    try {
      await api.archiveFinancialDataset(project.id, datasetId)
      setArchiveConfirmId(null)
      setNotice('数据集已归档；原文件、规则结果、风险和证据链均已保留。')
      await loadDatasets(datasetId)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '数据集归档失败')
    } finally {
      setBusy(null)
    }
  }

  if (!project) {
    return <section className="financial-empty"><Files aria-hidden="true" /><h1>财务数据</h1><p>先创建或选择一个项目，再导入科目余额表。</p></section>
  }

  return (
    <section className="financial-page" aria-labelledby="financial-title">
      <header className="financial-head">
        <div>
          <span className="section-kicker">本地确定性计算</span>
          <h1 id="financial-title">财务数据</h1>
          <p>导入末级科目余额表，保留不可变版本，并在本机复算借贷平衡与跨期衔接。</p>
        </div>
        <div className="financial-head-actions">
          <a className="button secondary" href="/api/v1/financial-data/template" download>下载模板</a>
          <a className="button secondary" href="/api/v1/financial-data/synthetic-demo" download>合成演示数据</a>
          <button className="button primary" type="button" disabled={project.storage_available === false || busy !== null} onClick={() => uploadRef.current?.click()}>
            <UploadSimple aria-hidden="true" />选择 CSV
          </button>
          <input ref={uploadRef} className="sr-only" aria-label="选择科目余额表 CSV" type="file" accept="text/csv,.csv" onChange={inputChanged} />
        </div>
      </header>

      {error && <div ref={errorRef} className="notice error financial-notice" role="alert" tabIndex={-1}><Warning aria-hidden="true" /><span>{error}</span><button aria-label="关闭错误" onClick={() => setError(null)}><X aria-hidden="true" /></button></div>}
      {notice && <div className="notice success financial-notice" role="status"><CheckCircle aria-hidden="true" /><span>{notice}</span></div>}

      <div
        className={`financial-drop ${dragging ? 'dragging' : ''}`}
        onDragEnter={(event) => { event.preventDefault(); setDragging(true) }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={() => setDragging(false)}
        onDrop={dropped}
      >
        <UploadSimple aria-hidden="true" />
        <div><strong>{busy === 'preview' ? '正在校验 CSV…' : '拖放科目余额表到这里'}</strong><span>最大 100 MB / 50 万行 · UTF-8、UTF-8 BOM 或 GB18030 · 金额单位固定为元</span></div>
      </div>

      {preview && <PreviewPanel preview={preview} busy={busy === 'confirm'} onConfirm={confirmImport} onClose={() => setPreview(null)} />}

      {financialTasks.length > 0 && <section className="financial-task-strip" aria-label="财务数据任务">
        {financialTasks.slice(0, 4).map((task) => <div key={task.id}>
          <span className={`rule-dot ${task.status}`} aria-hidden="true" />
          <strong>{task.filename}</strong>
          <small>{task.current_step} · {task.progress}%</small>
        </div>)}
      </section>}

      <div className="financial-layout">
        <aside className="dataset-list" aria-label="数据集版本">
          <div className="list-heading"><span>数据集版本</span><b>{datasets.length}</b></div>
          {datasets.length === 0 ? <div className="compact-empty"><Files aria-hidden="true" /><p>尚未导入财务数据</p><span>先下载模板，确认预览后再入库。</span></div> : datasets.map((dataset) => (
            <button key={dataset.id} className={selectedDatasetId === dataset.id ? 'active' : ''} type="button" onClick={() => setSelectedDatasetId(dataset.id)}>
              <span><strong>{dataset.filename}</strong><small>{dataset.period_start} → {dataset.period_end} · {dataset.row_count.toLocaleString()} 行</small></span>
              <em className={dataset.status}>{dataset.status === 'active' ? '活动' : '已归档'}</em>
              <code>{dataset.sha256.slice(0, 8)}</code>
            </button>
          ))}
        </aside>

        <div className="financial-detail">
          {!detail ? <div className="financial-detail-empty"><Files aria-hidden="true" /><h2>等待数据集</h2><p>完成一次 CSV 导入后，这里显示规则结果与行级证据。</p></div> : <>
            <header className="dataset-head">
              <div><span className="section-kicker">不可变数据集</span><h2>{detail.filename}</h2><p>{detail.sha256} · {formatBytes(detail.size_bytes)} · {detail.encoding}</p></div>
              <div className="dataset-actions">
                <button className="button secondary" type="button" disabled={busy !== null} onClick={() => void reuseRuleRun()}><Play aria-hidden="true" />重新运行</button>
                {detail.status === 'active' && <button className={`button ${archiveConfirmId === detail.id ? 'danger' : 'secondary'}`} type="button" disabled={busy !== null} onClick={() => void archiveDataset(detail.id)}><Archive aria-hidden="true" />{archiveConfirmId === detail.id ? '再次点击确认归档' : '归档'}</button>}
              </div>
            </header>

            <section className="financial-metrics" aria-label="数据集摘要">
              <div><span>期间</span><strong>{detail.period_start}</strong><small>至 {detail.period_end}</small></div>
              <div><span>明细行</span><strong>{detail.row_count.toLocaleString()}</strong><small>{detail.currency} · {detail.amount_unit}</small></div>
              <div><span>规则失败</span><strong>{detail.failed_count ?? 0}</strong><small>仅生成待评估草稿</small></div>
              <div><span>无法计算</span><strong>{detail.unavailable_count ?? 0}</strong><small>缺少比较基准</small></div>
            </section>
            {detail.import_warnings.length > 0 && <div className="dataset-warning" role="note"><Warning aria-hidden="true" /><span><b>导入提示</b>{detail.import_warnings.map((item) => item.message).join('；')}</span></div>}

            <div className="rule-workspace">
              <section className="rule-list" aria-label="规则结果">
                <div className="list-heading"><span>{detail.rule_set_version ?? '规则结果'}</span><b>{detail.rule_results.length}</b></div>
                {detail.rule_results.map((result) => <button key={result.id} className={selectedResultId === result.id ? 'active' : ''} type="button" onClick={() => setSelectedResultId(result.id)}>
                  <span className={`rule-status ${result.status}`}>{statusLabel[result.status]}</span>
                  <span><strong>{result.summary}</strong><small>{result.rule_id} / {result.rule_version} · {result.affected_count} 行</small></span>
                </button>)}
              </section>

              <section className="rule-detail" aria-live="polite">
                {selectedResult ? <>
                  <header><div><span className={`rule-status ${selectedResult.status}`}>{statusLabel[selectedResult.status]}</span><h3>{selectedResult.summary}</h3></div><code>{selectedResult.rule_id} / {selectedResult.rule_version}</code></header>
                  <dl className="rule-calculation">
                    <div><dt>输入值</dt><dd>{displayObject(selectedResult.input_values) || '无'}</dd></div>
                    <div><dt>比较基准</dt><dd>{displayObject(selectedResult.baseline_values) || '无'}</dd></div>
                    <div><dt>计算结果</dt><dd>{displayObject(selectedResult.calculation_result) || '无'}</dd></div>
                  </dl>
                  <div className="result-row-head"><div><strong>CSV 行级证据</strong><span>{resultRows ? `${resultRows.offset + 1}–${Math.min(resultRows.offset + resultRows.rows.length, resultRows.total)} / ${resultRows.total}` : selectedResult.affected_count ? '正在加载' : '无异常行'}</span></div>{resultRows && resultRows.total > resultRows.limit && <div><button type="button" disabled={resultRows.offset === 0 || busy === 'rows'} onClick={() => void loadResultRows(selectedResult, Math.max(0, resultRows.offset - resultRows.limit))}>上一页</button><button type="button" disabled={resultRows.offset + resultRows.limit >= resultRows.total || busy === 'rows'} onClick={() => void loadResultRows(selectedResult, resultRows.offset + resultRows.limit)}>下一页</button></div>}</div>
                  {resultRows && resultRows.rows.length > 0 ? <ResultTable rows={resultRows.rows} /> : <div className="result-empty"><CheckCircle aria-hidden="true" /><span>{selectedResult.status === 'pass' ? '规则已通过，没有异常行。' : selectedResult.status === 'unavailable' ? '缺少相邻期间，未把未知结果标记为通过。' : '没有可显示的行。'}</span></div>}
                </> : <div className="financial-detail-empty"><Files aria-hidden="true" /><h3>选择一条规则结果</h3></div>}
              </section>
            </div>
          </>}
        </div>
      </div>
    </section>
  )
}

function PreviewPanel({ preview, busy, onConfirm, onClose }: { preview: FinancialPreview; busy: boolean; onConfirm: () => void; onClose: () => void }) {
  return <section className="preview-panel" aria-labelledby="preview-title">
    <header><div><span className="section-kicker">导入预览</span><h2 id="preview-title">{preview.valid ? '结构校验完成' : '结构校验未通过'}</h2></div><button className="icon-button" type="button" aria-label="关闭导入预览" onClick={onClose}><X aria-hidden="true" /></button></header>
    <div className="preview-metrics"><span><b>{preview.row_count.toLocaleString()}</b> 行</span><span><b>{preview.period_start || '—'}</b> 至 {preview.period_end || '—'}</span><span><b>{preview.currency || '—'}</b> / {preview.amount_unit}</span><span><b>{preview.encoding}</b> 编码</span></div>
    {preview.errors.length > 0 && <div className="preview-issues error" role="alert"><strong>必须修正</strong>{preview.errors.slice(0, 20).map((issue, index) => <div key={`${issue.code}-${index}`}><b>{issue.code}</b><span>{issue.message}</span><small>{issue.action}</small></div>)}</div>}
    {preview.warnings.length > 0 && <div className="preview-issues warning"><strong>需要确认</strong>{preview.warnings.map((issue, index) => <div key={`${issue.code}-${index}`}><b>{issue.code}</b><span>{issue.message}</span><small>{issue.action}</small></div>)}</div>}
    {preview.sample_rows.length > 0 && <div className="preview-table-wrap"><table><caption>前 {preview.sample_rows.length} 行预览</caption><thead><tr>{Object.keys(preview.sample_rows[0]).map((key) => <th key={key} scope="col">{key}</th>)}</tr></thead><tbody>{preview.sample_rows.map((row, index) => <tr key={index}>{Object.keys(preview.sample_rows[0]).map((key) => <td key={key}>{row[key]}</td>)}</tr>)}</tbody></table></div>}
    <footer><span>{preview.duplicate_dataset_id ? '相同文件不会重复计算。' : '确认后才会写入不可变数据集并运行规则。'}</span><button className="button primary" type="button" disabled={!preview.valid || !preview.preview_id || Boolean(preview.duplicate_dataset_id) || busy} onClick={onConfirm}>{busy ? '正在提交…' : preview.duplicate_dataset_id ? '已存在相同版本' : '确认导入并运行规则'}</button></footer>
  </section>
}

function ResultTable({ rows }: { rows: FinancialResultRows['rows'] }) {
  return <div className="result-table-wrap"><table><caption className="sr-only">规则影响的 CSV 行</caption><thead><tr><th scope="col">行号</th><th scope="col">期间</th><th scope="col">科目</th><th scope="col">期初借</th><th scope="col">期初贷</th><th scope="col">本期借</th><th scope="col">本期贷</th><th scope="col">期末借</th><th scope="col">期末贷</th><th scope="col">原因</th></tr></thead><tbody>{rows.map((row) => <tr key={row.line_number}><td>{row.line_number}</td><td>{row.year}-{row.period}</td><td><strong>{row.account_code}</strong><small>{row.account_name}</small></td><td>{row.opening_debit}</td><td>{row.opening_credit}</td><td>{row.period_debit}</td><td>{row.period_credit}</td><td>{row.closing_debit}</td><td>{row.closing_credit}</td><td>{row.reason}</td></tr>)}</tbody></table></div>
}
