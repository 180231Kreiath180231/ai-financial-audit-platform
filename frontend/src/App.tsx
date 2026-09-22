import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type DragEvent } from 'react'
import {
  Archive,
  CaretDown,
  CheckCircle,
  FilePdf,
  Files,
  Gear,
  HardDrives,
  ListMagnifyingGlass,
  Moon,
  Pause,
  Play,
  Plus,
  ShieldCheck,
  Sun,
  UploadSimple,
  Warning,
  X,
} from '@phosphor-icons/react'
import { api } from './api'
import { ProjectDialog } from './components/ProjectDialog'
import { StatusMark } from './components/StatusMark'
import type { DocumentRecord, Project, ProjectPayload, ResourceSnapshot, TaskRecord } from './types'

type View = 'project' | 'documents' | 'analysis' | 'risks' | 'outputs' | 'settings'
type MobilePane = 'queue' | 'canvas' | 'decision'
type InspectorTab = 'basis' | 'explain' | 'action'

const navItems: { id: View; label: string }[] = [
  { id: 'project', label: '项目' },
  { id: 'documents', label: '资料' },
  { id: 'analysis', label: '分析' },
  { id: 'risks', label: '风险' },
  { id: 'outputs', label: '输出' },
  { id: 'settings', label: '设置' },
]

const PdfViewer = lazy(() =>
  import('./components/PdfViewer').then((module) => ({ default: module.PdfViewer })),
)

const laterViews: Record<Exclude<View, 'project' | 'documents'>, { title: string; phase: string; description: string }> = {
  analysis: { title: '分析', phase: '迭代四', description: '确定性财务规则、趋势、MAD 与结构占比将在规则口径确认后启用。' },
  risks: { title: '风险', phase: '迭代四', description: '风险卡片必须同时包含规则版本、支持证据、反证、不确定性与人工状态。' },
  outputs: { title: '输出', phase: '迭代五', description: '固定模板与 Word、Excel、PDF 优先级确认后接入历史快照导出。' },
  settings: { title: '设置', phase: '迭代二', description: '服务商、密钥引用、能力档案和外发审计将在模型政策确认后启用。' },
}

const emptyResources: ResourceSnapshot = {
  cpu_percent: 0,
  memory_percent: 0,
  disk_free_gb: 0,
  worker_limit: 1,
  external_api_enabled: false,
}

function formatBytes(size: number) {
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function AppShellError({ message, retry }: { message: string; retry: () => void }) {
  return (
    <main className="boot-screen">
      <div className="boot-mark">衡</div>
      <p className="section-kicker">本地服务连接失败</p>
      <h1>工作台暂时无法启动</h1>
      <p>{message}</p>
      <button className="button primary" onClick={retry}>重新连接</button>
    </main>
  )
}

export function App() {
  const [ready, setReady] = useState(false)
  const [bootError, setBootError] = useState<string | null>(null)
  const [projects, setProjects] = useState<Project[]>([])
  const [selectedProjectId, setSelectedProjectId] = useState<string>('')
  const [documents, setDocuments] = useState<DocumentRecord[]>([])
  const [tasks, setTasks] = useState<TaskRecord[]>([])
  const [selectedDocumentId, setSelectedDocumentId] = useState<string>('')
  const [selectedTaskId, setSelectedTaskId] = useState<string>('')
  const [resources, setResources] = useState<ResourceSnapshot>(emptyResources)
  const [view, setView] = useState<View>('project')
  const [mobilePane, setMobilePane] = useState<MobilePane>('canvas')
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>('basis')
  const [theme, setTheme] = useState<'dark' | 'light'>('dark')
  const [projectDialogOpen, setProjectDialogOpen] = useState(false)
  const [projectBusy, setProjectBusy] = useState(false)
  const [projectError, setProjectError] = useState<string | null>(null)
  const [uploadNotice, setUploadNotice] = useState<string | null>(null)
  const [operationError, setOperationError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const uploadRef = useRef<HTMLInputElement>(null)

  const selectedProject = projects.find((project) => project.id === selectedProjectId) ?? null
  const selectedDocument = documents.find((document) => document.id === selectedDocumentId) ?? null
  const selectedTask = tasks.find((task) => task.id === selectedTaskId) ?? tasks[0] ?? null
  const activeTaskCount = tasks.filter((task) => ['queued', 'running', 'pausing'].includes(task.status)).length

  const bootstrap = useCallback(async () => {
    setBootError(null)
    try {
      await api.createSession()
      const nextProjects = await api.listProjects()
      setProjects(nextProjects)
      setSelectedProjectId((current) => current || nextProjects[0]?.id || '')
      setReady(true)
    } catch (reason) {
      setBootError(reason instanceof Error ? reason.message : '无法连接本地服务')
    }
  }, [])

  useEffect(() => {
    void bootstrap()
  }, [bootstrap])

  const refreshProjectData = useCallback(async (projectId: string) => {
    try {
      const [nextProjects, nextDocuments, nextTasks, snapshot] = await Promise.all([
        api.listProjects(),
        api.listDocuments(projectId),
        api.listTasks(projectId),
        api.resources(),
      ])
      setProjects(nextProjects)
      setDocuments(nextDocuments)
      setTasks(nextTasks)
      setResources(snapshot)
      setSelectedDocumentId((current) =>
        nextDocuments.some((document) => document.id === current) ? current : nextDocuments[0]?.id || '',
      )
      setSelectedTaskId((current) =>
        nextTasks.some((task) => task.id === current) ? current : nextTasks[0]?.id || '',
      )
    } catch (reason) {
      setOperationError(reason instanceof Error ? reason.message : '项目状态刷新失败')
    }
  }, [])

  useEffect(() => {
    if (!selectedProjectId) {
      setDocuments([])
      setTasks([])
      return
    }
    if (selectedProject?.storage_available === false) {
      setDocuments([])
      setTasks([])
      setSelectedDocumentId('')
      setSelectedTaskId('')
      setOperationError('项目目录不可用或项目数据库已移动；请恢复原项目目录后重试。')
      return
    }
    void refreshProjectData(selectedProjectId)
    const timer = window.setInterval(() => void refreshProjectData(selectedProjectId), activeTaskCount > 0 ? 1000 : 4000)
    return () => window.clearInterval(timer)
  }, [activeTaskCount, refreshProjectData, selectedProject?.storage_available, selectedProjectId])

  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])

  useEffect(() => {
    function shortcut(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        document.getElementById('project-selector')?.focus()
      }
    }
    window.addEventListener('keydown', shortcut)
    return () => window.removeEventListener('keydown', shortcut)
  }, [])

  const taskCounts = useMemo(() => ({
    queued: tasks.filter((task) => task.status === 'queued').length,
    running: tasks.filter((task) => ['running', 'pausing'].includes(task.status)).length,
    failed: tasks.filter((task) => task.status === 'failed').length,
    completed: tasks.filter((task) => task.status === 'completed').length,
  }), [tasks])

  async function createProject(payload: ProjectPayload) {
    setProjectBusy(true)
    setProjectError(null)
    try {
      const created = await api.createProject(payload)
      const nextProjects = await api.listProjects()
      setProjects(nextProjects)
      setSelectedProjectId(created.id)
      setProjectDialogOpen(false)
      setView('project')
    } catch (reason) {
      setProjectError(reason instanceof Error ? reason.message : '项目创建失败')
    } finally {
      setProjectBusy(false)
    }
  }

  async function uploadFiles(files: File[]) {
    if (!selectedProject || files.length === 0) return
    if (selectedProject.storage_available === false) {
      setOperationError('项目目录不可用，无法导入 PDF。')
      return
    }
    setOperationError(null)
    setUploadNotice(null)
    try {
      const result = await api.uploadDocuments(selectedProject.id, files)
      const pieces: string[] = []
      if (result.accepted.length) pieces.push(`${result.accepted.length} 个 PDF 已进入本地任务队列`)
      if (result.rejected.length) pieces.push(`${result.rejected.length} 个文件未接收：${result.rejected[0].message}`)
      setUploadNotice(pieces.join('；'))
      await refreshProjectData(selectedProject.id)
    } catch (reason) {
      setOperationError(reason instanceof Error ? reason.message : '文件上传失败')
    }
  }

  function fileInputChanged(event: ChangeEvent<HTMLInputElement>) {
    void uploadFiles(Array.from(event.target.files ?? []))
    event.target.value = ''
  }

  function dropped(event: DragEvent) {
    event.preventDefault()
    setDragging(false)
    void uploadFiles(Array.from(event.dataTransfer.files))
  }

  async function changeTask(task: TaskRecord, action: string) {
    if (!selectedProject) return
    setOperationError(null)
    try {
      await api.changeTask(selectedProject.id, task.id, action)
      await refreshProjectData(selectedProject.id)
    } catch (reason) {
      setOperationError(reason instanceof Error ? reason.message : '任务操作失败')
    }
  }

  if (bootError) return <AppShellError message={bootError} retry={() => void bootstrap()} />
  if (!ready) return <main className="boot-screen" aria-live="polite"><div className="boot-mark">衡</div><div className="skeleton-line wide" /><div className="skeleton-line" /><p>正在连接本地工作台…</p></main>

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand-block">
          <div className="brand-mark" aria-hidden="true">衡</div>
          <div><strong>衡鉴审计工作台</strong><span>本地优先 · 第一版</span></div>
        </div>
        <div className="project-title">
          <strong>{selectedProject?.name ?? '尚未创建项目'}</strong>
          <span>{selectedProject ? `${selectedProject.entity_name} · ${selectedProject.year_start}—${selectedProject.year_end}` : '创建隔离项目后开始'}</span>
        </div>
        <div className="header-tools">
          <span className="local-status"><i />本机负载 <b>{resources.cpu_percent}%</b></span>
          <button className="quick-button" type="button" onClick={() => document.getElementById('project-selector')?.focus()}>快速定位 <kbd>Ctrl K</kbd></button>
          <span className="offline-badge"><ShieldCheck aria-hidden="true" />严格离线</span>
          <button className="icon-button theme-button" type="button" aria-label={theme === 'dark' ? '切换为浅色主题' : '切换为深色主题'} onClick={() => setTheme((value) => value === 'dark' ? 'light' : 'dark')}>
            {theme === 'dark' ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}
          </button>
        </div>
      </header>

      <nav className="top-nav" aria-label="主功能">
        {navItems.map((item) => (
          <button key={item.id} className={view === item.id ? 'active' : ''} type="button" onClick={() => setView(item.id)}>
            {item.label}
            {item.id === 'documents' && documents.length > 0 && <span>{documents.length}</span>}
            {item.id === 'risks' && <small>后续</small>}
          </button>
        ))}
      </nav>

      <main id="main-content" tabIndex={-1}>
        {(view === 'project' || view === 'documents') && (
          <>
            <nav className="mobile-workspace-switch" aria-label="项目工作区">
              {(['queue', 'canvas', 'decision'] as MobilePane[]).map((pane, index) => (
                <button key={pane} className={mobilePane === pane ? 'active' : ''} type="button" onClick={() => setMobilePane(pane)}>{['资料', '证据', '处置'][index]}</button>
              ))}
            </nav>
            <div className={`workspace mobile-${mobilePane}`}>
              <aside className="queue-pane pane" aria-label="资料与任务队列">
                <div className="pane-head queue-head">
                  <div><span className="section-kicker">文档工作区</span><h1>{view === 'project' ? '项目资料' : '资料队列'}</h1></div>
                  <button className="icon-button" type="button" aria-label="创建新项目" onClick={() => setProjectDialogOpen(true)}><Plus aria-hidden="true" /></button>
                </div>
                <label className="project-select-label" htmlFor="project-selector">当前项目</label>
                <div className="select-wrap">
                  <select id="project-selector" value={selectedProjectId} onChange={(event) => setSelectedProjectId(event.target.value)}>
                    {projects.map((project) => <option key={project.id} value={project.id}>{project.name}{project.storage_available === false ? '（目录不可用）' : ''}</option>)}
                  </select>
                  <CaretDown aria-hidden="true" />
                </div>
                {selectedProject?.is_synthetic && <div className="synthetic-note"><ShieldCheck aria-hidden="true" /><span><b>合成演示项目</b>不包含真实客户资料，也不会调用外部模型。</span></div>}
                {selectedProject?.storage_available === false && <div className="notice error" role="alert"><Warning aria-hidden="true" /><span>项目目录不可用或项目数据库已移动；恢复原目录后才能继续处理。</span></div>}
                <div
                  className={`drop-zone ${dragging ? 'dragging' : ''}`}
                  onDragEnter={(event) => { event.preventDefault(); setDragging(true) }}
                  onDragOver={(event) => event.preventDefault()}
                  onDragLeave={() => setDragging(false)}
                  onDrop={dropped}
                >
                  <UploadSimple aria-hidden="true" />
                  <strong>导入 PDF</strong>
                  <span>拖放到这里，或选择多个文件</span>
                  <button className="button compact" type="button" disabled={selectedProject?.storage_available === false} onClick={() => uploadRef.current?.click()}>选择 PDF</button>
                  <input ref={uploadRef} className="sr-only" type="file" accept="application/pdf,.pdf" multiple disabled={selectedProject?.storage_available === false} onChange={fileInputChanged} />
                </div>
                {uploadNotice && <div className="notice success" role="status"><CheckCircle aria-hidden="true" />{uploadNotice}</div>}
                {operationError && <div className="notice error" role="alert"><Warning aria-hidden="true" /><span>{operationError}</span><button aria-label="关闭错误" onClick={() => setOperationError(null)}><X aria-hidden="true" /></button></div>}
                <div className="queue-summary" aria-label="任务统计">
                  <span><b>{taskCounts.queued}</b>排队</span><span><b>{taskCounts.running}</b>运行</span><span><b>{taskCounts.failed}</b>失败</span><span><b>{taskCounts.completed}</b>完成</span>
                </div>
                <div className="document-list" aria-label="已导入文档">
                  <div className="list-heading"><span>本地文档</span><b>{documents.length}</b></div>
                  {documents.length === 0 ? (
                    <div className="compact-empty"><FilePdf aria-hidden="true" /><p>尚无可查看文档</p><span>导入原生 PDF 后，将在本机完成哈希与文本提取。</span></div>
                  ) : documents.map((document) => (
                    <button key={document.id} className={`document-row ${selectedDocumentId === document.id ? 'active' : ''}`} type="button" onClick={() => { setSelectedDocumentId(document.id); setMobilePane('canvas') }}>
                      <FilePdf aria-hidden="true" /><span><strong>{document.filename}</strong><small>{document.page_count} 页 · {formatBytes(document.size_bytes)}</small></span><b>{document.sha256.slice(0, 6)}</b>
                    </button>
                  ))}
                </div>
                {tasks.length > 0 && (
                  <div className="task-list" aria-label="处理任务">
                    <div className="list-heading"><span>最近任务</span><b>{tasks.length}</b></div>
                    {tasks.slice(0, 8).map((task) => (
                      <button key={task.id} className={`task-row ${selectedTask?.id === task.id ? 'active' : ''}`} type="button" onClick={() => { setSelectedTaskId(task.id); setMobilePane('decision') }}>
                        <span><strong>{task.filename}</strong><small>{task.current_step}</small></span><StatusMark status={task.status} />
                      </button>
                    ))}
                  </div>
                )}
              </aside>

              <section className="canvas-pane pane" aria-label="证据阅读画布">
                {selectedDocument && selectedProject ? (
                  <Suspense fallback={<div className="viewer-state"><span className="skeleton-line wide" /><span className="skeleton-line" />正在准备本地阅读器…</div>}>
                    <PdfViewer key={selectedDocument.id} projectId={selectedProject.id} document={selectedDocument} />
                  </Suspense>
                ) : (
                  <div className="overview-canvas">
                    <header className="canvas-head">
                      <div><span className="section-kicker">项目 / 资料 / 本地解析</span><h2>{selectedProject?.name ?? '开始第一个审计项目'}</h2></div>
                      <button className="button primary" type="button" disabled={selectedProject?.storage_available === false} onClick={() => selectedProject ? uploadRef.current?.click() : setProjectDialogOpen(true)}>{selectedProject ? '导入 PDF' : '创建项目'}</button>
                    </header>
                    <section className="metric-strip" aria-label="项目概览">
                      <div><span>本地文档</span><strong>{selectedProject?.document_count ?? 0}</strong><small>{selectedProject?.page_count ?? 0} 个可定位页面</small></div>
                      <div><span>处理任务</span><strong>{tasks.length}</strong><small>单工作器 · 并发固定为 1</small></div>
                      <div><span>失败隔离</span><strong>{taskCounts.failed}</strong><small>失败不会阻塞整批导入</small></div>
                      <div><span>本机存储</span><strong>{resources.disk_free_gb || '—'}<em>GB</em></strong><small>可用磁盘空间</small></div>
                    </section>
                    <section className="onboarding">
                      <div className="onboarding-copy"><span className="section-kicker">第一版可运行闭环</span><h3>从原始 PDF 到可复核页码</h3><p>文件先写入项目隔离目录，再由单工作器计算 SHA-256、检查 PDF 完整性、提取页级原文并保存解析版本。相同文件不会重复解析。</p></div>
                      <ol className="process-steps">
                        <li className="done"><span>01</span><div><b>创建隔离项目</b><small>独立目录与 SQLite 数据库</small></div></li>
                        <li className={tasks.length ? 'done' : ''}><span>02</span><div><b>导入并去重</b><small>损坏文件隔离，整批继续</small></div></li>
                        <li className={documents.length ? 'done' : ''}><span>03</span><div><b>本地解析与阅读</b><small>页码、原文、解析版本可追溯</small></div></li>
                        <li><span>04</span><div><b>风险取证</b><small>待规则口径确认后进入迭代四</small></div></li>
                      </ol>
                    </section>
                    <section className="security-ledger">
                      <div><ShieldCheck aria-hidden="true" /><span><b>严格离线已生效</b><small>当前版本不包含任何模型、OCR、Embedding 或遥测外发。</small></span></div>
                      <div><HardDrives aria-hidden="true" /><span><b>{selectedProject?.storage_path ?? '本地项目目录'}</b><small>原始文件、解析结果与任务轨迹均保存在本机。</small></span></div>
                    </section>
                  </div>
                )}
              </section>

              <aside className="decision-pane pane" aria-label="复核与处置面板">
                <div className="pane-head"><div><span className="section-kicker">复核与处置</span><h2>{selectedTask?.filename ?? '尚未选择任务'}</h2></div></div>
                <nav className="inspector-tabs" aria-label="处置面板内容">
                  {([['basis', '判断依据'], ['explain', 'AI 解释'], ['action', '人工处置']] as [InspectorTab, string][]).map(([id, label]) => <button key={id} className={inspectorTab === id ? 'active' : ''} type="button" onClick={() => setInspectorTab(id)}>{label}</button>)}
                </nav>
                {inspectorTab === 'basis' && (
                  <div className="inspector-content">
                    {selectedTask ? (
                      <>
                        <div className="task-hero"><StatusMark status={selectedTask.status} /><strong>{selectedTask.progress}%</strong><span>{selectedTask.current_step}</span></div>
                        <dl className="detail-list"><div><dt>任务编号</dt><dd>{selectedTask.id.slice(0, 8)}</dd></div><div><dt>处理方式</dt><dd>本地确定性任务</dd></div><div><dt>外部请求</dt><dd>0 次</dd></div><div><dt>结果</dt><dd>{selectedTask.result_kind === 'duplicate' ? '复用已有文档' : selectedTask.result_kind === 'imported' ? '已生成页级证据' : '等待完成'}</dd></div></dl>
                        {selectedTask.error_message && <div className="error-panel" role="alert"><b>{selectedTask.error_code}</b><p>{selectedTask.error_message}</p><span>{selectedTask.next_action}</span></div>}
                      </>
                    ) : <div className="inspector-empty"><ListMagnifyingGlass aria-hidden="true" /><h3>等待资料任务</h3><p>选择 PDF 后，这里显示真实进度、错误码和可执行的下一步。</p></div>}
                  </div>
                )}
                {inspectorTab === 'explain' && <div className="inspector-empty"><ShieldCheck aria-hidden="true" /><h3>AI 解释尚未启用</h3><p>第一版严格离线运行。模型服务商、外发范围和数据政策确认前，不会发送任何证据。</p><span className="future-label">迭代二后按能力接入</span></div>}
                {inspectorTab === 'action' && (
                  <div className="inspector-content">
                    <p className="panel-intro">只显示当前任务状态允许的动作；所有操作均写入本地状态库。</p>
                    {selectedTask && <div className="task-actions">
                      {selectedTask.status === 'running' && <button className="button secondary" type="button" onClick={() => void changeTask(selectedTask, 'pause')}><Pause aria-hidden="true" />安全暂停</button>}
                      {selectedTask.status === 'paused' && <button className="button primary" type="button" onClick={() => void changeTask(selectedTask, 'resume')}><Play aria-hidden="true" />继续处理</button>}
                      {selectedTask.status === 'failed' && <button className="button primary" type="button" onClick={() => void changeTask(selectedTask, 'retry')}><Play aria-hidden="true" />重新处理</button>}
                      {['queued', 'running', 'paused'].includes(selectedTask.status) && <button className="button danger" type="button" onClick={() => void changeTask(selectedTask, 'cancel')}><X aria-hidden="true" />取消任务</button>}
                      {selectedTask.status === 'completed' && <div className="completed-note"><CheckCircle aria-hidden="true" /><span><b>结果已提交</b>可从左侧选择对应文档查看页码与原文。</span></div>}
                    </div>}
                    {!selectedTask && <div className="inspector-empty"><Archive aria-hidden="true" /><h3>没有可处置任务</h3><p>导入 PDF 后可在这里暂停、继续、取消或重试。</p></div>}
                  </div>
                )}
              </aside>
            </div>
          </>
        )}

        {view !== 'project' && view !== 'documents' && (
          <section className="future-page">
            <div className="future-icon">{view === 'settings' ? <Gear aria-hidden="true" /> : view === 'outputs' ? <Files aria-hidden="true" /> : <ListMagnifyingGlass aria-hidden="true" />}</div>
            <span className="section-kicker">{laterViews[view].phase}</span><h1>{laterViews[view].title}</h1><p>{laterViews[view].description}</p>
            <div className="scope-guard"><ShieldCheck aria-hidden="true" /><span><b>范围保护</b>当前页面是禁用态，不伪造分析、风险或导出成功。已确认的文档链路仍可在“项目”和“资料”中使用。</span></div>
          </section>
        )}
      </main>

      <footer className="status-bar">
        <div><span>当前上下文</span><b>{selectedDocument?.filename ?? selectedProject?.name ?? '未选择项目'}</b></div>
        <div className="status-center"><ShieldCheck aria-hidden="true" /><span>仅使用本地资料 · 外部 API 已阻断</span></div>
        <div className="resource-brief"><span>CPU <b>{resources.cpu_percent}%</b></span><span>内存 <b>{resources.memory_percent}%</b></span><small>本地工作线程 {resources.worker_limit}</small></div>
      </footer>

      <nav className="mobile-nav" aria-label="移动端主功能">
        {navItems.slice(0, 4).map((item) => <button key={item.id} className={view === item.id ? 'active' : ''} type="button" onClick={() => setView(item.id)}>{item.label}</button>)}
        <button type="button" className={view === 'outputs' || view === 'settings' ? 'active' : ''} onClick={() => setView(view === 'outputs' ? 'settings' : 'outputs')}>更多</button>
      </nav>

      <ProjectDialog open={projectDialogOpen} busy={projectBusy} error={projectError} onClose={() => { setProjectDialogOpen(false); setProjectError(null) }} onSubmit={createProject} />
    </div>
  )
}
