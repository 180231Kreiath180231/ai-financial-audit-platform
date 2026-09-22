import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, MagnifyingGlass, Minus, Plus } from '@phosphor-icons/react'
import { GlobalWorkerOptions, getDocument, type PDFDocumentProxy, type RenderTask } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { api } from '../api'
import type { DocumentRecord, SearchHit } from '../types'

GlobalWorkerOptions.workerSrc = workerUrl

interface Props {
  projectId: string
  document: DocumentRecord
}

export function PdfViewer({ projectId, document }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const renderToken = useRef(0)
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null)
  const [page, setPage] = useState(1)
  const [scale, setScale] = useState(1.15)
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<SearchHit[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError(null)
    setPage(1)
    const task = getDocument({ url: api.documentUrl(projectId, document.id), withCredentials: true })
    task.promise
      .then((loaded) => {
        if (active) setPdf(loaded)
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : 'PDF 加载失败')
      })
      .finally(() => active && setLoading(false))
    return () => {
      active = false
      void task.destroy()
      setPdf(null)
    }
  }, [document.id, projectId])

  useEffect(() => {
    if (!pdf || !canvasRef.current) return
    const current = ++renderToken.current
    let renderTask: RenderTask | null = null
    pdf.getPage(page).then((pdfPage) => {
      if (current !== renderToken.current || !canvasRef.current) return
      const viewport = pdfPage.getViewport({ scale })
      const canvas = canvasRef.current
      const pixelRatio = Math.min(window.devicePixelRatio || 1, 2)
      canvas.width = Math.floor(viewport.width * pixelRatio)
      canvas.height = Math.floor(viewport.height * pixelRatio)
      canvas.style.width = `${viewport.width}px`
      canvas.style.height = `${viewport.height}px`
      renderTask = pdfPage.render({
        canvas,
        viewport,
        transform: pixelRatio === 1 ? undefined : [pixelRatio, 0, 0, pixelRatio, 0, 0],
      })
      return renderTask.promise
    }).catch((reason: unknown) => {
      if (reason instanceof Error && reason.name !== 'RenderingCancelledException') setError(reason.message)
    })
    return () => renderTask?.cancel()
  }, [page, pdf, scale])

  async function search() {
    const trimmed = query.trim()
    if (!trimmed) {
      setHits([])
      return
    }
    try {
      const nextHits = await api.searchDocument(projectId, document.id, trimmed)
      setHits(nextHits)
      if (nextHits[0]) setPage(nextHits[0].page_number)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '搜索失败')
    }
  }

  return (
    <section className="pdf-viewer" aria-label={`${document.filename} 阅读器`}>
      <div className="viewer-toolbar">
        <div className="viewer-file">
          <strong>{document.filename}</strong>
          <span>{document.page_count} 页 · 本地解析</span>
        </div>
        <div className="viewer-controls" aria-label="PDF 页面与缩放控制">
          <button className="icon-button" type="button" aria-label="上一页" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}><ArrowLeft aria-hidden="true" /></button>
          <label className="page-input"><span className="sr-only">页码</span><input type="number" min="1" max={pdf?.numPages ?? document.page_count} value={page} onChange={(event) => setPage(Math.max(1, Math.min(Number(event.target.value), pdf?.numPages ?? document.page_count)))} /><span>/ {pdf?.numPages ?? document.page_count}</span></label>
          <button className="icon-button" type="button" aria-label="下一页" disabled={page >= (pdf?.numPages ?? document.page_count)} onClick={() => setPage((value) => value + 1)}><ArrowRight aria-hidden="true" /></button>
          <span className="toolbar-divider" />
          <button className="icon-button" type="button" aria-label="缩小" disabled={scale <= 0.65} onClick={() => setScale((value) => Math.max(0.65, value - 0.15))}><Minus aria-hidden="true" /></button>
          <span className="zoom-value">{Math.round(scale * 100)}%</span>
          <button className="icon-button" type="button" aria-label="放大" disabled={scale >= 2} onClick={() => setScale((value) => Math.min(2, value + 0.15))}><Plus aria-hidden="true" /></button>
        </div>
      </div>
      <div className="document-search">
        <MagnifyingGlass aria-hidden="true" />
        <input aria-label="搜索文档原文" placeholder="搜索本地提取的原文" value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => event.key === 'Enter' && void search()} />
        <button type="button" onClick={() => void search()}>查找</button>
      </div>
      {hits.length > 0 && (
        <div className="search-hits" aria-live="polite">
          {hits.map((hit) => <button key={hit.page_number} type="button" onClick={() => setPage(hit.page_number)}>第 {hit.page_number} 页<span>{hit.snippet || '命中页'}</span></button>)}
        </div>
      )}
      <div className="canvas-stage">
        {loading && <div className="viewer-state"><span className="skeleton-line wide" /><span className="skeleton-line" />正在加载 PDF…</div>}
        {error && <div className="viewer-state error" role="alert">{error}</div>}
        <canvas ref={canvasRef} aria-label={`第 ${page} 页`} />
      </div>
    </section>
  )
}
