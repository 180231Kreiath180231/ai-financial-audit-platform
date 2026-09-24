import { CheckCircle, Pause, Play, Warning, X } from '@phosphor-icons/react'
import type { TaskRecord } from '../types'

type TaskAction = 'pause' | 'resume' | 'retry' | 'cancel'

export function TaskActions({
  task,
  onChange,
}: {
  task: TaskRecord
  onChange: (task: TaskRecord, action: TaskAction) => void
}) {
  const resourcePaused = task.pause_reason === 'resource'

  return (
    <div className="task-actions">
      {task.status === 'running' && (
        <button className="button secondary" type="button" onClick={() => onChange(task, 'pause')}>
          <Pause aria-hidden="true" />安全暂停
        </button>
      )}
      {task.status === 'paused' && !resourcePaused && (
        <button className="button primary" type="button" onClick={() => onChange(task, 'resume')}>
          <Play aria-hidden="true" />继续处理
        </button>
      )}
      {resourcePaused && ['pausing', 'paused'].includes(task.status) && (
        <div className="resource-pause-note" role="status" aria-live="polite">
          <Warning aria-hidden="true" />
          <span>
            <b>{task.status === 'pausing' ? '资源保护正在安全暂停' : '资源保护已暂停任务'}</b>
            {task.status === 'pausing'
              ? '完成当前安全步骤后暂停，不会中断正在写入的数据。'
              : '整机 CPU 低于 30% 持续 10 秒后自动继续，无需手动操作。'}
          </span>
        </div>
      )}
      {task.status === 'failed' && (
        <button className="button primary" type="button" onClick={() => onChange(task, 'retry')}>
          <Play aria-hidden="true" />重新处理
        </button>
      )}
      {['queued', 'running', 'paused'].includes(task.status) && (
        <button className="button danger" type="button" onClick={() => onChange(task, 'cancel')}>
          <X aria-hidden="true" />取消任务
        </button>
      )}
      {task.status === 'completed' && (
        <div className="completed-note">
          <CheckCircle aria-hidden="true" />
          <span><b>结果已提交</b>可从左侧选择对应文档查看页码与原文。</span>
        </div>
      )}
    </div>
  )
}
