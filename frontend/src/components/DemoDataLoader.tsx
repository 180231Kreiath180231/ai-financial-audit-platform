import { CheckCircle, Play, Warning } from '@phosphor-icons/react'
import { useEffect, useState } from 'react'
import { api } from '../api'
import type { DemoLoadResult } from '../types'

interface DemoDataLoaderProps {
  projectId: string
  disabled?: boolean
  onLoaded: () => Promise<void>
}

export function DemoDataLoader({ projectId, disabled = false, onLoaded }: DemoDataLoaderProps) {
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<DemoLoadResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setResult(null)
    setError(null)
  }, [projectId])

  async function loadDemoData() {
    setBusy(true)
    setResult(null)
    setError(null)
    try {
      const loaded = await api.loadDemoData(projectId)
      setResult(loaded)
      await onLoaded()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '演示资料载入失败，请重试')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="demo-loader" aria-labelledby="demo-loader-title">
      <div className="demo-loader-copy">
        <span className="section-kicker">合成数据快捷入口</span>
        <strong id="demo-loader-title">载入完整演示资料</strong>
        <small>3 份 PDF + 1 份科目余额表，全程本地处理，可重复执行。</small>
      </div>
      <button
        className="button compact demo-loader-action"
        type="button"
        disabled={disabled || busy}
        aria-busy={busy}
        onClick={() => void loadDemoData()}
      >
        <Play aria-hidden="true" />
        {busy ? '正在加入任务…' : result ? '再次检查资料' : '一键载入'}
      </button>
      {result && (
        <p className="demo-loader-message success" role="status">
          <CheckCircle aria-hidden="true" />
          <span>{result.message}；外部请求 0 次。</span>
        </p>
      )}
      {error && (
        <p className="demo-loader-message error" role="alert">
          <Warning aria-hidden="true" />
          <span>{error}</span>
        </p>
      )}
    </section>
  )
}
