import {
  ArrowRight,
  CheckCircle,
  FilePdf,
  HardDrives,
  ListMagnifyingGlass,
  Plus,
  ShieldCheck,
  Warning,
} from '@phosphor-icons/react'
import { StatusMark } from './StatusMark'
import type { DocumentRecord, Project, ResourceSnapshot, RiskRecord, TaskRecord } from '../types'

interface Props {
  project: Project | null
  documents: DocumentRecord[]
  tasks: TaskRecord[]
  risks: RiskRecord[]
  resources: ResourceSnapshot
  strictOffline: boolean
  onCreateProject: () => void
  onOpenDocuments: () => void
  onOpenDocument: (documentId: string) => void
  onOpenTask: (taskId: string) => void
  onOpenAnalysis: () => void
  onOpenRisks: () => void
  onOpenOutputs: () => void
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit' }).format(new Date(value))
}

export function ProjectOverview({
  project,
  documents,
  tasks,
  risks,
  resources,
  strictOffline,
  onCreateProject,
  onOpenDocuments,
  onOpenDocument,
  onOpenTask,
  onOpenAnalysis,
  onOpenRisks,
  onOpenOutputs,
}: Props) {
  if (!project) {
    return (
      <section className="project-overview project-overview-empty" aria-labelledby="project-overview-title">
        <div className="overview-empty-mark"><HardDrives aria-hidden="true" /></div>
        <p className="section-kicker">本地审计项目</p>
        <h1 id="project-overview-title">创建第一个项目</h1>
        <p>项目会使用独立目录和数据库保存原始资料、证据、风险与输出历史。</p>
        <button className="button primary" type="button" onClick={onCreateProject}><Plus aria-hidden="true" />新建项目</button>
      </section>
    )
  }

  const activeTasks = tasks.filter((task) => ['queued', 'running', 'pausing', 'retry_wait'].includes(task.status))
  const failedTasks = tasks.filter((task) => task.status === 'failed')
  const pendingRisks = risks.filter((risk) => ['待复核', '待补证'].includes(risk.status))
  const confirmedRisks = risks.filter((risk) => ['已核实', '已关闭'].includes(risk.status))
  const recentDocuments = [...documents].sort((left, right) => right.created_at.localeCompare(left.created_at)).slice(0, 4)
  const recentTasks = tasks.slice(0, 5)

  const nextAction = failedTasks.length > 0
    ? { title: `处理 ${failedTasks.length} 项失败任务`, body: '失败文件已隔离，不影响同批其他资料。查看错误原因并选择重试或跳过。', action: '查看任务', run: onOpenDocuments, tone: 'warning' }
    : activeTasks.length > 0
      ? { title: `${activeTasks.length} 项任务正在处理`, body: '可以继续查看已有资料，后台任务会在安全点持续更新进度。', action: '查看进度', run: onOpenDocuments, tone: 'active' }
      : documents.length === 0
        ? { title: '导入第一批审计资料', body: '从 PDF 开始建立可检索、可定位、可追溯的项目证据。', action: '进入资料', run: onOpenDocuments, tone: 'active' }
        : pendingRisks.length > 0
          ? { title: `复核 ${pendingRisks.length} 项风险`, body: '核对支持证据、反证与计算依据，再由人工更新风险状态。', action: '进入风险', run: onOpenRisks, tone: 'active' }
          : confirmedRisks.length > 0
            ? { title: '准备工作成果', body: `已有 ${confirmedRisks.length} 项已确认风险，可以创建资料清单、访谈提纲和管理层材料。`, action: '进入输出', run: onOpenOutputs, tone: 'ready' }
            : { title: '从资料中识别审计线索', body: '运行确定性分析，或从项目检索结果中选择证据创建风险草稿。', action: '进入分析', run: onOpenAnalysis, tone: 'active' }

  return (
    <section className="project-overview" aria-labelledby="project-overview-title">
      <header className="project-overview-head">
        <div>
          <span className="section-kicker">项目控制台</span>
          <h1 id="project-overview-title">项目概览</h1>
          <p>{project.name}的范围、处理状态和下一步工作集中在这里。</p>
        </div>
        <div className="project-overview-actions">
          <button className="button secondary" type="button" onClick={onCreateProject}><Plus aria-hidden="true" />新建项目</button>
          <button className="button primary" type="button" disabled={!project.storage_available} onClick={onOpenDocuments}>进入资料工作区<ArrowRight aria-hidden="true" /></button>
        </div>
      </header>

      {project.storage_available === false && (
        <div className="project-alert" role="alert"><Warning aria-hidden="true" /><span><b>项目目录不可用</b>恢复原目录后才能继续导入、处理和输出。</span></div>
      )}

      <div className="project-scope" aria-label="项目范围">
        <div><span>被审计主体</span><strong>{project.entity_name}</strong></div>
        <div><span>审计年度</span><strong>{project.year_start}-{project.year_end}</strong></div>
        <div><span>项目存储</span><strong title={project.storage_path}>{project.storage_path}</strong></div>
        <div><span>外发状态</span><strong className={strictOffline ? 'safe' : 'warning'}>{strictOffline ? '严格离线' : project.external_access_enabled ? '项目已授权' : '等待项目授权'}</strong></div>
      </div>

      <section className="project-metrics" aria-label="项目统计">
        <div><span>本地文档</span><strong>{documents.length}</strong><small>{project.page_count} 个可定位页面</small></div>
        <div><span>处理中</span><strong>{activeTasks.length}</strong><small>本地单工作器</small></div>
        <div><span>风险事项</span><strong>{risks.length}</strong><small>{pendingRisks.length} 项待处理</small></div>
        <div><span>已确认风险</span><strong>{confirmedRisks.length}</strong><small>可进入成果草稿</small></div>
      </section>

      <div className="project-overview-grid">
        <div className="project-overview-primary">
          <section className={`project-next-action ${nextAction.tone}`} aria-labelledby="next-action-title">
            <div>
              <span>建议下一步</span>
              <h2 id="next-action-title">{nextAction.title}</h2>
              <p>{nextAction.body}</p>
            </div>
            <button className="button primary" type="button" onClick={nextAction.run}>{nextAction.action}<ArrowRight aria-hidden="true" /></button>
          </section>

          <section className="project-flow" aria-labelledby="project-flow-title">
            <div className="overview-section-head"><div><span>审计工作流</span><h2 id="project-flow-title">从资料到工作成果</h2></div><small>每一步保留来源和历史版本</small></div>
            <div className="project-flow-list">
              <button type="button" onClick={onOpenDocuments}><span className={documents.length > 0 ? 'complete' : ''}>{documents.length > 0 ? <CheckCircle aria-hidden="true" /> : '1'}</span><div><b>资料与证据</b><small>{documents.length > 0 ? `${documents.length} 份文档已进入项目` : '导入并建立页级证据'}</small></div><ArrowRight aria-hidden="true" /></button>
              <button type="button" onClick={onOpenAnalysis}><span>2</span><div><b>确定性分析</b><small>本地执行规则、趋势和稳健统计</small></div><ArrowRight aria-hidden="true" /></button>
              <button type="button" onClick={onOpenRisks}><span className={risks.length > 0 ? 'complete' : ''}>{risks.length > 0 ? <CheckCircle aria-hidden="true" /> : '3'}</span><div><b>风险复核</b><small>{risks.length > 0 ? `${risks.length} 项风险，${pendingRisks.length} 项待处理` : '人工核对证据并形成判断'}</small></div><ArrowRight aria-hidden="true" /></button>
              <button type="button" onClick={onOpenOutputs}><span className={confirmedRisks.length > 0 ? 'complete' : ''}>{confirmedRisks.length > 0 ? <CheckCircle aria-hidden="true" /> : '4'}</span><div><b>输出成果</b><small>{confirmedRisks.length > 0 ? `${confirmedRisks.length} 项风险可生成成果` : '已确认风险才能进入输出'}</small></div><ArrowRight aria-hidden="true" /></button>
            </div>
          </section>

          <section className="project-recent" aria-labelledby="recent-documents-title">
            <div className="overview-section-head"><div><span>最近资料</span><h2 id="recent-documents-title">本地文档</h2></div><button type="button" onClick={onOpenDocuments}>查看全部</button></div>
            {recentDocuments.length === 0 ? (
              <div className="overview-inline-empty"><FilePdf aria-hidden="true" /><span><b>尚未导入 PDF</b><small>进入资料工作区开始建立项目证据。</small></span></div>
            ) : (
              <div className="recent-document-list">
                {recentDocuments.map((document) => <button type="button" key={document.id} onClick={() => onOpenDocument(document.id)}><FilePdf aria-hidden="true" /><span><b>{document.filename}</b><small>{document.page_count} 页 · {formatDate(document.created_at)}</small></span><ArrowRight aria-hidden="true" /></button>)}
              </div>
            )}
          </section>
        </div>

        <aside className="project-overview-secondary" aria-label="项目运行状态">
          <section className="project-health">
            <div className="overview-section-head"><div><span>运行状态</span><h2>本地环境</h2></div><ShieldCheck aria-hidden="true" /></div>
            <dl>
              <div><dt>项目目录</dt><dd className={project.storage_available ? 'safe' : 'danger'}>{project.storage_available ? '可用' : '不可用'}</dd></div>
              <div><dt>严格离线</dt><dd className={strictOffline ? 'safe' : 'warning'}>{strictOffline ? '已开启' : '已关闭'}</dd></div>
              <div><dt>磁盘可用</dt><dd>{resources.disk_free_gb > 0 ? `${resources.disk_free_gb} GB` : '未记录'}</dd></div>
              <div><dt>后台并发</dt><dd>{resources.worker_limit} 个工作器</dd></div>
            </dl>
          </section>

          <section className="project-task-summary">
            <div className="overview-section-head"><div><span>最近处理</span><h2>任务状态</h2></div><button type="button" onClick={onOpenDocuments}>打开队列</button></div>
            {recentTasks.length === 0 ? (
              <div className="overview-inline-empty"><ListMagnifyingGlass aria-hidden="true" /><span><b>暂无处理任务</b><small>导入资料后会显示进度和错误操作。</small></span></div>
            ) : (
              <div className="overview-task-list">
                {recentTasks.map((task) => <button type="button" key={task.id} onClick={() => onOpenTask(task.id)}><span><b>{task.filename}</b><small>{task.current_step}</small></span><StatusMark status={task.status} /></button>)}
              </div>
            )}
          </section>
        </aside>
      </div>
    </section>
  )
}
