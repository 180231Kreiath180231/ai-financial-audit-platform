export type TaskStatus =
  | 'queued'
  | 'running'
  | 'pausing'
  | 'paused'
  | 'retry_wait'
  | 'failed'
  | 'completed'
  | 'cancelled'

export interface Project {
  id: string
  name: string
  entity_name: string
  year_start: number
  year_end: number
  storage_path: string
  model_profile: string
  is_synthetic: boolean
  created_at: string
  document_count: number
  page_count: number
  queued_count: number
  running_count: number
  failed_count: number
  completed_count: number
  storage_available: boolean
  storage_error_code: string | null
}

export interface DocumentRecord {
  id: string
  filename: string
  sha256: string
  size_bytes: number
  page_count: number
  parse_method: string
  parse_version: string
  created_at: string
}

export interface TaskRecord {
  id: string
  filename: string
  status: TaskStatus
  progress: number
  current_step: string
  error_code: string | null
  error_message: string | null
  next_action: string | null
  result_kind: string | null
  document_id: string | null
  created_at: string
  updated_at: string
}

export interface ResourceSnapshot {
  cpu_percent: number
  memory_percent: number
  disk_free_gb: number
  worker_limit: number
  external_api_enabled: boolean
}

export interface ProjectPayload {
  name: string
  entity_name: string
  year_start: number
  year_end: number
  storage_path: string
  model_profile: string
}

export interface SearchHit {
  page_number: number
  snippet: string
}
