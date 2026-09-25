import { useState, type FormEvent } from 'react'
import { Check, PencilSimple, Plus, Trash, X } from '@phosphor-icons/react'
import type { AssistantThread } from '../types'

interface Props {
  threads: AssistantThread[]
  selectedThreadId: string
  collapsed: boolean
  busy: boolean
  onCreate: () => void
  onSelect: (threadId: string) => void
  onRename: (thread: AssistantThread, title: string) => Promise<void>
  onDelete: (thread: AssistantThread) => void
}

function formatUpdatedAt(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

export function AssistantHistory({
  threads,
  selectedThreadId,
  collapsed,
  busy,
  onCreate,
  onSelect,
  onRename,
  onDelete,
}: Props) {
  const [editingId, setEditingId] = useState('')
  const [draftTitle, setDraftTitle] = useState('')
  const [renameError, setRenameError] = useState('')

  function startRename(thread: AssistantThread) {
    setEditingId(thread.id)
    setDraftTitle(thread.title)
    setRenameError('')
  }

  function cancelRename() {
    setEditingId('')
    setDraftTitle('')
    setRenameError('')
  }

  async function saveRename(event: FormEvent, thread: AssistantThread) {
    event.preventDefault()
    const title = draftTitle.trim()
    if (!title) {
      setRenameError('对话名称不能为空')
      return
    }
    try {
      await onRename(thread, title)
      cancelRename()
    } catch {
      setRenameError('重命名失败，请重试')
    }
  }

  return (
    <nav id="assistant-history" className={`assistant-history${collapsed ? ' collapsed' : ''}`} aria-label="AI 对话历史">
      <div className="assistant-history-head">
        {!collapsed && <><span className="section-kicker">当前项目</span><h3>对话历史</h3></>}
        <button type="button" className="assistant-history-create" disabled={busy} onClick={onCreate} aria-label="新建 AI 对话">
          <Plus aria-hidden="true" />
          {!collapsed && <span>新建对话</span>}
        </button>
      </div>

      {threads.length === 0 ? (
        !collapsed && <p className="assistant-history-empty">尚无历史对话。发送第一个问题后会保存在当前项目中。</p>
      ) : (
        <ul className="assistant-history-list">
          {threads.map((thread) => {
            const active = thread.id === selectedThreadId
            if (editingId === thread.id && !collapsed) {
              return (
                <li key={thread.id} className="assistant-history-editing">
                  <form onSubmit={(event) => void saveRename(event, thread)}>
                    <label htmlFor={`assistant-thread-title-${thread.id}`}>对话名称</label>
                    <input
                      id={`assistant-thread-title-${thread.id}`}
                      value={draftTitle}
                      maxLength={80}
                      autoFocus
                      aria-invalid={Boolean(renameError)}
                      aria-describedby={renameError ? `assistant-thread-error-${thread.id}` : undefined}
                      onChange={(event) => {
                        setDraftTitle(event.target.value)
                        if (renameError) setRenameError('')
                      }}
                      onKeyDown={(event) => {
                        if (event.key === 'Escape') {
                          event.preventDefault()
                          cancelRename()
                        }
                      }}
                    />
                    <div>
                      <button type="submit" aria-label="保存对话名称" disabled={busy}><Check aria-hidden="true" /></button>
                      <button type="button" aria-label="取消重命名" disabled={busy} onClick={cancelRename}><X aria-hidden="true" /></button>
                    </div>
                  </form>
                  {renameError && <p id={`assistant-thread-error-${thread.id}`} role="alert">{renameError}</p>}
                </li>
              )
            }
            return (
              <li key={thread.id} className={active ? 'active' : ''}>
                <button
                  type="button"
                  className="assistant-history-select"
                  aria-current={active ? 'page' : undefined}
                  aria-label={collapsed ? `打开对话 ${thread.title}` : undefined}
                  title={collapsed ? thread.title : undefined}
                  onClick={() => onSelect(thread.id)}
                >
                  {collapsed ? <b aria-hidden="true">{thread.title.slice(0, 1)}</b> : <><b>{thread.title}</b><time dateTime={thread.updated_at}>{formatUpdatedAt(thread.updated_at)}</time></>}
                </button>
                {!collapsed && (
                  <div className="assistant-history-actions">
                    <button type="button" aria-label={`重命名对话 ${thread.title}`} disabled={busy} onClick={() => startRename(thread)}><PencilSimple aria-hidden="true" /></button>
                    <button type="button" aria-label={`删除对话 ${thread.title}`} disabled={busy} onClick={() => onDelete(thread)}><Trash aria-hidden="true" /></button>
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </nav>
  )
}
