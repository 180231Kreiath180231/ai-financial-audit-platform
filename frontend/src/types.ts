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
  provider_kind: 'fake' | 'openai_compatible' | 'paddleocr_aistudio'
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
  provider_kind: 'openai_compatible' | 'paddleocr_aistudio'
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
  native_page_count: number
  scan_page_count: number
  vision_page_count: number
  external_vision_page_count: number
  vision_status: 'not_required' | 'completed' | 'requires_vision' | 'failed'
  fiscal_year: number | null
  entity_name: string | null
  document_type: string | null
  account_names: string[]
  metadata_version: number
  metadata_updated_at: string | null
}

export interface DocumentMetadataPayload {
  fiscal_year: number | null
  entity_name: string | null
  document_type: string | null
  account_names: string[]
  change_reason?: string
}

export interface ProjectSearchFilters {
  document_id?: string
  fiscal_year?: number
  entity_name?: string
  account_name?: string
  document_type?: string
  parse_method?: string
}

export interface RetrievalStatus {
  chunk_version: string
  chunk_state: 'empty' | 'ready' | 'stale'
  chunk_count: number
  chunked_page_count: number
  source_page_count: number
  keyword_state: 'empty' | 'ready'
  vector_state: 'not_configured' | 'building' | 'ready' | 'stale' | 'failed'
  vector_backend: 'sqlite_vec' | 'memory_cosine' | null
  model_profile_id: string | null
  actual_model: string | null
  dimension: number | null
  indexed_chunk_count: number
  external_request: boolean
  message: string
  action: string
}

export interface PageVisionRecord {
  page_number: number
  status: 'not_required' | 'completed' | 'requires_vision' | 'failed'
  provider_name: string | null
  actual_model: string | null
  model_call_id: string | null
  schema_version: string
  confidence: number | null
  image_sha256: string | null
  external_request: boolean
  remote_request_id: string | null
  remote_cleanup_status: 'not_applicable' | 'unsupported' | 'unknown'
  error_code: string | null
  error_message: string | null
  parse_method: string
  parse_version: string
}

export interface TaskRecord {
  id: string
  task_type: string
  filename: string
  status: TaskStatus
  progress: number
  current_step: string
  error_code: string | null
  error_message: string | null
  next_action: string | null
  result_kind: string | null
  document_id: string | null
  dataset_id: string | null
  created_at: string
  updated_at: string
}

export interface DemoLoadResult {
  queued_task_ids: string[]
  queued_task_count: number
  reused_document_count: number
  reused_task_count: number
  reused_financial_dataset: boolean
  message: string
  external_request: false
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
  chunk_id?: string | null
  document_id: string
  document_name: string
  page_number: number
  block_number: number
  parse_method: string
  parse_version: string
  snippet: string
  match_kind: 'content' | 'filename' | 'metadata' | 'semantic'
  fiscal_year: number | null
  entity_name: string | null
  document_type: string | null
  account_names: string[]
}

export type EvidenceDirection = 'support' | 'counter'
export type RiskStatus = '待复核' | '已核实' | '已排除' | '待补证' | '已关闭'

export interface EvidenceSelection extends SearchHit {
  direction: EvidenceDirection
}

export interface RiskEvidence {
  id: string
  kind: 'document' | 'financial'
  document_id: string | null
  document_name: string
  page_number: number | null
  block_number: number | null
  dataset_id: string | null
  line_start: number | null
  line_end: number | null
  period_key: string | null
  account_code: string | null
  quote: string
  direction: EvidenceDirection
  parse_method: string | null
  parse_version: string | null
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

export interface FinancialPreviewIssue {
  code: string
  message: string
  action: string
  line_number: number | null
  field: string | null
}

export interface FinancialPreview {
  preview_id: string | null
  duplicate_dataset_id: string | null
  valid: boolean
  encoding: string
  size_bytes: number
  row_count: number
  currency: string
  amount_unit: string
  period_type: 'monthly' | 'annual'
  period_start: string
  period_end: string
  extra_columns: string[]
  warnings: FinancialPreviewIssue[]
  errors: FinancialPreviewIssue[]
  sample_rows: Array<Record<string, string>>
}

export type FinancialRuleStatus = 'pass' | 'fail' | 'unavailable'

export interface FinancialRuleResult {
  id: string
  rule_id: string
  rule_version: string
  period_key: string
  status: FinancialRuleStatus
  summary: string
  input_values: Record<string, unknown>
  baseline_values: Record<string, unknown>
  calculation_result: Record<string, unknown>
  scope: Record<string, unknown>
  affected_count: number
  line_start: number | null
  line_end: number | null
  created_at: string
}

export interface FinancialDataset {
  id: string
  filename: string
  sha256: string
  size_bytes: number
  encoding: string
  period_type: 'monthly' | 'annual'
  period_start: string
  period_end: string
  row_count: number
  currency: string
  amount_unit: string
  status: 'active' | 'archived'
  created_at: string
  archived_at: string | null
  rule_run_id: string | null
  rule_set_version: string | null
  rule_run_status: string | null
  passed_count: number | null
  failed_count: number | null
  unavailable_count: number | null
  completed_at: string | null
  import_warnings: FinancialPreviewIssue[]
  rule_results: FinancialRuleResult[]
}

export interface FinancialResultRow {
  line_number: number
  year: number
  period: string
  account_code: string
  account_name: string
  opening_debit: string
  opening_credit: string
  period_debit: string
  period_credit: string
  closing_debit: string
  closing_credit: string
  currency: string
  reason: string
}

export interface FinancialResultRows {
  total: number
  offset: number
  limit: number
  rows: FinancialResultRow[]
}

export interface FinancialEvidenceTarget {
  datasetId: string
  lineStart: number | null
  lineEnd: number | null
  periodKey: string | null
  token: number
}
