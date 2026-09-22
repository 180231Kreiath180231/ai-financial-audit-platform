import { CheckCircle, CircleNotch, Clock, PauseCircle, WarningCircle, XCircle } from '@phosphor-icons/react'
import type { TaskStatus } from '../types'

const labels: Record<TaskStatus, string> = {
  queued: '排队中',
  running: '处理中',
  pausing: '正在暂停',
  paused: '已暂停',
  retry_wait: '等待重试',
  failed: '处理失败',
  completed: '已完成',
  cancelled: '已取消',
}

export function StatusMark({ status }: { status: TaskStatus }) {
  const Icon =
    status === 'completed'
      ? CheckCircle
      : status === 'failed'
        ? WarningCircle
        : status === 'cancelled'
          ? XCircle
          : status === 'paused' || status === 'pausing'
            ? PauseCircle
            : status === 'running'
              ? CircleNotch
              : Clock
  return (
    <span className={`status-mark status-${status}`}>
      <Icon aria-hidden="true" weight={status === 'running' ? 'bold' : 'regular'} />
      {labels[status]}
    </span>
  )
}
