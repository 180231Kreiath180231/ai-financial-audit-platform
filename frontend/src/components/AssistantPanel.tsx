import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import {
  ArrowSquareOut,
  ChatCircleDots,
  FileText,
  NotePencil,
  PaperPlaneRight,
  SidebarSimple,
  ShieldCheck,
  Sparkle,
  Trash,
  X,
} from '@phosphor-icons/react'
import { api } from '../api'
import { AssistantHistory } from './AssistantHistory'
import type {
  AssistantCitation,
  AssistantMessage,
  AssistantPreset,
  AssistantScope,
  AssistantThread,
  DocumentRecord,
  EvidenceSelection,
  Project,
  RiskRecord,
} from '../types'

interface Props {
  project: Project | null
  currentDocument: DocumentRecord | null
  selectedEvidence: EvidenceSelection[]
  strictOffline: boolean
  onOpenCitation: (citation: AssistantCitation) => void
  onRiskCreated: (risk: RiskRecord) => void
}

const scopes: Array<{ value: AssistantScope; label: string; help: string }> = [
  { value: 'smart', label: '智能组合', help: '项目证据优先，可补充通用知识' },
  { value: 'selected', label: '已选证据', help: '严格限制在人工选择的证据' },
  { value: 'document', label: '当前文档', help: '检索正在阅读的整份文档' },
  { value: 'project', label: '当前项目', help: '检索当前项目内允许读取的资料' },
  { value: 'general', label: '通用知识', help: '不读取项目资料，可询问范围外内容' },
]

const presets: Array<{ value: AssistantPreset; label: string; prompt: string }> = [
  { value: 'free', label: '自由提问', prompt: '' },
  { value: 'explain', label: '解释内容', prompt: '请解释当前内容的审计含义，并指出需要人工核对的部分。' },
  { value: 'evidence', label: '支持与反证', prompt: '请分别查找支持当前判断的证据和可能的反证。' },
  { value: 'gap', label: '资料缺口', prompt: '请识别当前判断仍缺少哪些资料，并说明用途。' },
  { value: 'procedure', label: '审计程序', prompt: '请基于当前线索提出可执行、可复核的审计程序建议。' },
  { value: 'interview', label: '访谈问题', prompt: '请生成针对当前事项的访谈问题，并说明每个问题的核查目的。' },
  { value: 'knowledge', label: '专业问答', prompt: '请回答这个会计或审计知识问题，并标明通用知识边界：' },
  { value: 'compare', label: '比较分析', prompt: '请比较当前资料中的差异、共同点和需要进一步核实的事项。' },
  { value: 'polish', label: '润色草稿', prompt: '请在不改变事实和结论的前提下，润色以下文字：' },
]

const sourceLabels = {
  project_evidence: '项目证据',
  general_knowledge: '通用知识',
  local_simulation: '本地模拟',
} as const

export function AssistantPanel({
  project,
  currentDocument,
  selectedEvidence,
  strictOffline,
  onOpenCitation,
  onRiskCreated,
}: Props) {
  const [open, setOpen] = useState(false)
  const [threads, setThreads] = useState<AssistantThread[]>([])
  const [selectedThreadId, setSelectedThreadId] = useState('')
  const [scope, setScope] = useState<AssistantScope>('smart')
  const [preset, setPreset] = useState<AssistantPreset>('free')
  const [content, setContent] = useState('')
  const [includeHistory, setIncludeHistory] = useState(false)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [historyCollapsed, setHistoryCollapsed] = useState(() => {
    if (typeof window === 'undefined') return false
    if (typeof window.matchMedia === 'function' && window.matchMedia('(max-width: 1180px)').matches) return true
    const saved = window.localStorage.getItem('assistant-history-collapsed')
    if (saved !== null) return saved === 'true'
    return false
  })
  const launcherRef = useRef<HTMLButtonElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const messagesRef = useRef<HTMLDivElement>(null)
  const previousOpenRef = useRef(false)
  const projectId = project?.id

  const selectedThread = threads.find((thread) => thread.id === selectedThreadId) ?? threads[0] ?? null
  const currentScope = scopes.find((item) => item.value === scope) ?? scopes[0]

  useEffect(() => {
    setThreads([])
    setSelectedThreadId('')
    setError(null)
    if (!projectId) return
    setLoading(true)
    void api.listAssistantThreads(projectId)
      .then((items) => {
        setThreads(items)
        setSelectedThreadId(items[0]?.id ?? '')
        if (items[0]) setScope(items[0].default_scope)
      })
      .catch((caught: Error) => setError(caught.message))
      .finally(() => setLoading(false))
  }, [projectId])

  useEffect(() => {
    function shortcut(event: KeyboardEvent) {
      if (event.ctrlKey && event.key === '/') {
        event.preventDefault()
        setOpen((current) => !current)
      }
      if (event.key === 'Escape' && open) {
        setOpen(false)
        launcherRef.current?.focus()
      }
    }
    window.addEventListener('keydown', shortcut)
    return () => window.removeEventListener('keydown', shortcut)
  }, [open])

  useEffect(() => {
    window.localStorage.setItem('assistant-history-collapsed', String(historyCollapsed))
  }, [historyCollapsed])

  useEffect(() => {
    if (open) {
      inputRef.current?.focus()
    } else if (previousOpenRef.current) {
      launcherRef.current?.focus()
    }
    previousOpenRef.current = open
  }, [open])

  useEffect(() => {
    if (!open) return
    const container = messagesRef.current
    if (typeof container?.scrollTo === 'function') {
      container.scrollTo({ top: container.scrollHeight })
    }
  }, [open, selectedThread?.messages.length])

  const selectedReferences = useMemo(() => selectedEvidence.map((item) => ({
    document_id: item.document_id,
    page_number: item.page_number,
    block_number: item.block_number,
    quote: item.snippet,
  })), [selectedEvidence])

  async function createThread() {
    if (!project) return null
    setBusy(true)
    setError(null)
    try {
      const created = await api.createAssistantThread(project.id, '新对话', scope)
      setThreads((current) => [created, ...current])
      setSelectedThreadId(created.id)
      setContent('')
      setNotice('已创建新的本地对话')
      return created
    } catch (caught) {
      setError((caught as Error).message)
      return null
    } finally {
      setBusy(false)
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!project || !content.trim() || busy) return
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      let thread = selectedThread
      if (!thread) {
        thread = await api.createAssistantThread(project.id, '新对话', scope)
      }
      const updated = await api.sendAssistantMessage(project.id, thread.id, {
        content: content.trim(),
        scope,
        preset,
        include_history: includeHistory,
        current_document_id: currentDocument?.id ?? null,
        current_page: null,
        selected_evidence: selectedReferences,
      })
      setThreads((current) => [updated, ...current.filter((item) => item.id !== updated.id)])
      setSelectedThreadId(updated.id)
      setContent('')
    } catch (caught) {
      setError((caught as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function renameThread(thread: AssistantThread, title: string) {
    if (!project) return
    setBusy(true)
    setError(null)
    try {
      const updated = await api.renameAssistantThread(project.id, thread.id, title)
      setThreads((current) => [updated, ...current.filter((item) => item.id !== updated.id)])
      setNotice('对话名称已更新')
    } catch (caught) {
      setError((caught as Error).message)
      throw caught
    } finally {
      setBusy(false)
    }
  }

  async function deleteThread(thread: AssistantThread | null = selectedThread) {
    if (!project || !thread) return
    if (!window.confirm(`删除对话“${thread.title}”及其全部本地消息？此操作不可撤销。`)) return
    setBusy(true)
    setError(null)
    try {
      await api.deleteAssistantThread(project.id, thread.id)
      const remaining = threads.filter((item) => item.id !== thread.id)
      setThreads(remaining)
      if (selectedThreadId === thread.id) setSelectedThreadId(remaining[0]?.id ?? '')
      setNotice('对话历史已从当前项目删除')
    } catch (caught) {
      setError((caught as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function deleteMessage(message: AssistantMessage) {
    if (!project || !selectedThread) return
    if (!window.confirm('删除这条本地对话消息？此操作不会删除来源资料。')) return
    setBusy(true)
    try {
      await api.deleteAssistantMessage(project.id, selectedThread.id, message.id)
      setThreads((current) => current.map((thread) => thread.id === selectedThread.id
        ? { ...thread, messages: thread.messages.filter((item) => item.id !== message.id) }
        : thread))
      setNotice('消息已删除')
    } catch (caught) {
      setError((caught as Error).message)
    } finally {
      setBusy(false)
    }
  }

  function questionBefore(message: AssistantMessage) {
    if (!selectedThread) return 'AI 对话线索'
    const index = selectedThread.messages.findIndex((item) => item.id === message.id)
    return [...selectedThread.messages.slice(0, index)].reverse().find((item) => item.role === 'user')?.content ?? 'AI 对话线索'
  }

  async function addToNote(message: AssistantMessage) {
    if (!project) return
    if (!window.confirm('将这条回答作为人工可编辑草稿添加到当前项目备忘录？模型不会自动修改既有内容。')) return
    setBusy(true)
    setError(null)
    try {
      const pages = [...new Map(message.citations
        .filter((citation) => citation.document_id && citation.page_number)
        .map((citation) => [`${citation.document_id}:${citation.page_number}`, {
          document_id: citation.document_id as string,
          page_number: citation.page_number as number,
        }])).values()]
      await api.createNote(project.id, {
        title: `AI 对话草稿：${questionBefore(message).slice(0, 80)}`,
        body: message.content,
        tags: ['AI 对话草稿'],
        model_readable: false,
        risk_ids: [],
        pages,
      })
      setNotice('已添加到备忘录，默认不允许模型再次读取')
    } catch (caught) {
      setError((caught as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function createRiskDraft(message: AssistantMessage) {
    if (!project) return
    const citations = message.citations.filter((citation) => (
      citation.document_id && citation.page_number && citation.block_number
    ))
    if (citations.length === 0) return
    if (!window.confirm('依据回答中的项目证据创建“待复核”风险草稿？当前模拟回答不会成为审计结论。')) return
    setBusy(true)
    setError(null)
    try {
      const risk = await api.createRisk(project.id, {
        risk_type: 'AI 对话线索',
        summary: `AI 对话线索：${questionBefore(message)}`.slice(0, 500),
        evidence: citations.map((citation) => ({
          document_id: citation.document_id as string,
          page_number: citation.page_number as number,
          block_number: citation.block_number as number,
          quote: citation.quote,
          direction: 'support' as const,
        })),
      })
      onRiskCreated(risk)
      setNotice(`已创建 ${risk.risk_number}，等待人工复核`)
    } catch (caught) {
      setError((caught as Error).message)
    } finally {
      setBusy(false)
    }
  }

  function choosePreset(item: typeof presets[number]) {
    setPreset(item.value)
    if (item.prompt) setContent(item.prompt)
    inputRef.current?.focus()
  }

  return (
    <>
      {!open && (
        <button
          ref={launcherRef}
          className="assistant-dock"
          type="button"
          aria-expanded="false"
          aria-controls="assistant-panel"
          disabled={!project}
          onClick={() => setOpen(true)}
        >
          <Sparkle aria-hidden="true" />
          <span><b>AI 审计助手</b><small>{project ? `${currentScope.label} · 联网关闭` : '选择项目后使用'}</small></span>
          <kbd>Ctrl /</kbd>
        </button>
      )}

      {open && (
        <section id="assistant-panel" className="assistant-panel" role="dialog" aria-modal="false" aria-labelledby="assistant-title">
          <header className="assistant-head">
            <button
              className="icon-button"
              type="button"
              aria-label={historyCollapsed ? '展开对话历史' : '收起对话历史'}
              aria-expanded={!historyCollapsed}
              aria-controls="assistant-history"
              onClick={() => setHistoryCollapsed((current) => !current)}
            ><SidebarSimple aria-hidden="true" /></button>
            <div className="assistant-title-group">
              <span className="section-kicker">项目级本地对话</span>
              <h2 id="assistant-title"><ChatCircleDots aria-hidden="true" />AI 审计助手</h2>
              <small>{selectedThread?.title ?? '尚无对话'}</small>
            </div>
            <button className="icon-button" type="button" aria-label="关闭 AI 助手" onClick={() => setOpen(false)}><X aria-hidden="true" /></button>
          </header>

          <div className="assistant-shell">
            {!historyCollapsed && <button className="assistant-history-scrim" type="button" aria-label="关闭对话历史" onClick={() => setHistoryCollapsed(true)} />}
            <AssistantHistory
              threads={threads}
              selectedThreadId={selectedThread?.id ?? ''}
              collapsed={historyCollapsed}
              busy={busy}
              onCreate={() => void createThread()}
              onSelect={(threadId) => {
                setSelectedThreadId(threadId)
                const thread = threads.find((item) => item.id === threadId)
                if (thread) setScope(thread.default_scope)
              }}
              onRename={renameThread}
              onDelete={(thread) => void deleteThread(thread)}
            />

            <div className="assistant-main">
              <div className="assistant-boundary">
                <ShieldCheck aria-hidden="true" />
                <span><b>{strictOffline ? '严格离线 · 本地模拟服务' : '项目外发开关可能已开启'}</b><small>通用知识可询问；联网检索未启用，不会自动修改风险或备忘录。</small></span>
              </div>

              <div className="assistant-controls">
                <label><span>回答范围</span><select value={scope} onChange={(event) => setScope(event.target.value as AssistantScope)}>{scopes.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
                <span className="assistant-thread-count">{loading ? '正在读取对话…' : `${threads.length} 个本地对话`}</span>
              </div>
              <p className="assistant-scope-help">{currentScope.help}。{scope === 'selected' ? `当前已选 ${selectedEvidence.length} 条证据。` : scope === 'document' ? currentDocument ? `当前文档：${currentDocument.filename}` : '尚未打开文档。' : ''}</p>

              <div className="assistant-presets" aria-label="提问预设">
                {presets.map((item) => <button key={item.value} type="button" aria-pressed={preset === item.value} className={preset === item.value ? 'active' : ''} onClick={() => choosePreset(item)}>{item.label}</button>)}
              </div>

              <div ref={messagesRef} className="assistant-messages" role="log" aria-live="polite" aria-label="AI 对话消息">
                {!selectedThread || selectedThread.messages.length === 0 ? (
                  <div className="assistant-empty">
                    <ChatCircleDots aria-hidden="true" />
                    <h3>从项目证据或通用问题开始</h3>
                    <p>智能组合会优先使用当前项目证据，也允许明确标记的通用知识。历史消息默认不会自动带入下一次请求。</p>
                  </div>
                ) : selectedThread.messages.map((message) => (
                  <article key={message.id} className={`assistant-message ${message.role}`}>
                    <header><b>{message.role === 'user' ? '你' : 'AI 助手'}</b><button type="button" aria-label={`删除${message.role === 'user' ? '提问' : '回答'}`} disabled={busy} onClick={() => void deleteMessage(message)}><Trash aria-hidden="true" /></button></header>
                    {message.role === 'assistant' && <div className="assistant-source-kinds">{message.source_kinds.map((kind) => <span key={kind}>{sourceLabels[kind]}</span>)}</div>}
                    <p>{message.content}</p>
                    {message.citations.length > 0 && <div className="assistant-citations" aria-label="回答引用">{message.citations.map((citation, index) => <button key={`${citation.label}-${index}`} type="button" onClick={() => onOpenCitation(citation)}><FileText aria-hidden="true" /><span><b>{citation.label}</b><small>{citation.quote}</small></span><ArrowSquareOut aria-hidden="true" /></button>)}</div>}
                    {message.role === 'assistant' && <footer><button type="button" disabled={busy} onClick={() => void addToNote(message)}><NotePencil aria-hidden="true" />添加到备忘录</button><button type="button" disabled={busy || !message.citations.some((citation) => citation.document_id && citation.page_number && citation.block_number)} onClick={() => void createRiskDraft(message)}><ShieldCheck aria-hidden="true" />创建风险草稿</button></footer>}
                  </article>
                ))}
              </div>

              {error && <div className="assistant-error" role="alert">{error}</div>}
              {notice && <div className="assistant-notice" role="status">{notice}</div>}

              <form className="assistant-composer" onSubmit={submit}>
                <label htmlFor="assistant-question">向 AI 审计助手提问</label>
                <textarea ref={inputRef} id="assistant-question" rows={3} maxLength={4000} value={content} onChange={(event) => setContent(event.target.value)} placeholder="询问项目资料，也可以提出范围外的会计、审计或一般问题" />
                <div><label className="assistant-history-toggle"><input type="checkbox" checked={includeHistory} onChange={(event) => setIncludeHistory(event.target.checked)} />本次包含最近对话</label><span>{content.length}/4000</span><button className="button primary" type="submit" disabled={!project || !content.trim() || busy}>{busy ? '处理中…' : '发送'}<PaperPlaneRight aria-hidden="true" /></button></div>
              </form>
            </div>
          </div>
        </section>
      )}
    </>
  )
}
