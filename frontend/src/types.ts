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
  external_access_enabled: boolean
}

export type ModelCapability =
  | 'text'
  | 'vision'
  | 'json_schema'
  | 'tools'
  | 'embedding'
  | 'file_upload'

export interface ModelProvider {
  id: string
  provider_kind: 'fake' | 'openai_compatible'
  display_name: string
  base_url: string
  secret_configured: boolean
  default_headers: Record<string, string>
  timeout_seconds: number
  max_retries: number
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface ModelProfile {
  id: string
  provider_id: string
  display_name: string
  model_name: string
  capabilities: ModelCapability[]
  context_window: number
  max_output_tokens: number
  input_cost_per_million: string
  output_cost_per_million: string
  is_fallback: boolean
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface ModelCallRecord {
  id: string
  project_id: string | null
  provider_id: string | null
  model_profile_id: string | null
  capability: ModelCapability
  started_at: string
  completed_at: string | null
  status: string
  error_code: string | null
}

export interface GatewayOverview {
  strict_offline: boolean
  providers: ModelProvider[]
  models: ModelProfile[]
  recent_calls: ModelCallRecord[]
}

export interface ModelProviderPayload {
  provider_kind: 'openai_compatible'
  display_name: string
  base_url: string
  api_key?: string
  clear_api_key?: boolean
  timeout_seconds: number
  max_retries: number
  enabled: boolean
}

export interface ModelProfilePayload {
  provider_id: string
  display_name: string
  model_name: string
  capabilities: ModelCapability[]
  context_window: number
  max_output_tokens: number
  input_cost_per_million: string
  output_cost_per_million: string
  is_fallback: boolean
  enabled: boolean
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
