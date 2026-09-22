import { useEffect, useRef, useState, type FormEvent } from 'react'
import { X } from '@phosphor-icons/react'
import type { ProjectPayload } from '../types'

interface Props {
  open: boolean
  busy: boolean
  error: string | null
  onClose: () => void
  onSubmit: (payload: ProjectPayload) => Promise<void>
}

const currentYear = new Date().getFullYear()

export function ProjectDialog({ open, busy, error, onClose, onSubmit }: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const [name, setName] = useState('')
  const [entity, setEntity] = useState('')
  const [yearStart, setYearStart] = useState(currentYear - 2)
  const [yearEnd, setYearEnd] = useState(currentYear)
  const [storagePath, setStoragePath] = useState('C:\\Users\\Public\\Documents\\HengjianProjects\\新项目')

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    const cancel = (event: Event) => {
      event.preventDefault()
      if (!busy) onClose()
    }
    dialog.addEventListener('cancel', cancel)
    return () => dialog.removeEventListener('cancel', cancel)
  }, [busy, onClose])

  async function submit(event: FormEvent) {
    event.preventDefault()
    await onSubmit({
      name,
      entity_name: entity,
      year_start: yearStart,
      year_end: yearEnd,
      storage_path: storagePath,
      model_profile: '严格离线 / Fake Provider',
    })
  }

  return (
    <dialog ref={dialogRef} className="dialog" aria-labelledby="project-dialog-title">
      <form onSubmit={submit}>
        <header className="dialog-head">
          <div>
            <span className="section-kicker">本地隔离项目</span>
            <h2 id="project-dialog-title">创建审计项目</h2>
          </div>
          <button className="icon-button" type="button" aria-label="关闭创建项目对话框" onClick={onClose} disabled={busy}>
            <X aria-hidden="true" />
          </button>
        </header>
        <div className="form-grid">
          <label className="field field-wide">
            <span>项目名称</span>
            <input value={name} onChange={(event) => setName(event.target.value)} minLength={2} required autoFocus />
          </label>
          <label className="field field-wide">
            <span>被审计主体</span>
            <input value={entity} onChange={(event) => setEntity(event.target.value)} minLength={2} required />
          </label>
          <label className="field">
            <span>开始年度</span>
            <input type="number" min="2000" max="2100" value={yearStart} onChange={(event) => setYearStart(Number(event.target.value))} required />
          </label>
          <label className="field">
            <span>结束年度</span>
            <input type="number" min={yearStart} max="2100" value={yearEnd} onChange={(event) => setYearEnd(Number(event.target.value))} required />
          </label>
          <label className="field field-wide">
            <span>本地存储位置</span>
            <input value={storagePath} onChange={(event) => setStoragePath(event.target.value)} required />
            <small>服务只在本机创建该目录；不可写时会阻止创建。</small>
          </label>
          <label className="field field-wide">
            <span>默认模型方案</span>
            <input value="严格离线 / Fake Provider" readOnly />
            <small>第一版不连接真实模型，也不会外发资料。</small>
          </label>
        </div>
        {error && <div className="inline-error" role="alert">{error}</div>}
        <footer className="dialog-actions">
          <button className="button secondary" type="button" onClick={onClose} disabled={busy}>取消</button>
          <button className="button primary" type="submit" disabled={busy}>{busy ? '正在创建…' : '创建并打开'}</button>
        </footer>
      </form>
    </dialog>
  )
}
