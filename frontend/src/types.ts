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
  cache_hit: boolean
  route_role: 'primary' | 'fallback'
  fallback_from_model_profile_id: string | null
}

export interface GatewayOverview {
  strict_offline: boolean
  cache_enabled: boolean
  cache_entry_count: number
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
  block_number: number
  parse_method: string
  parse_version: string
  snippet: string
}

export type EvidenceDirection = 'support' | 'counter'
export type RiskStatus = '待复核' | '已核实' | '已排除' | '待补证' | '已关闭'

export interface EvidenceSelection extends SearchHit {
  document_id: string
  document_name: string
  direction: EvidenceDirection
}

export interface RiskEvidence {
  id: string
  document_id: string
  document_name: string
  page_number: number
  block_number: number
  quote: string
  direction: EvidenceDirection
  parse_method: string
  parse_version: string
}

export interface RiskVersion {
  version: number
  change_reason: string
  created_at: string
  snapshot: Record<string, unknown>
}

export interface RiskRecord {
  id: string
  risk_number: string
  risk_type: string
  risk_level: '高' | '中' | '低' | '待评估'
  status: RiskStatus
  summary: string
  trigger_rule_id: string
  trigger_rule_version: string
  input_values: Record<string, unknown>
  baseline_values: Record<string, unknown>
  calculation_result: Record<string, unknown>
  model_explanation: string | null
  uncertainty: string
  human_opinion: string
  model_provider: string | null
  actual_model: string | null
  model_call_id: string | null
  version: number
  created_at: string
  updated_at: string
  evidence: RiskEvidence[]
  versions: RiskVersion[]
}

export interface RiskPayload {
  risk_type: string
  summary: string
  evidence: Array<{
    document_id: string
    page_number: number
    block_number: number
    quote: string
    direction: EvidenceDirection
  }>
}
