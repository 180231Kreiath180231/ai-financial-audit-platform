import type {
  DocumentRecord,
  DocumentMetadataPayload,
  FinancialDataset,
  FinancialPreview,
  FinancialResultRows,
  GatewayOverview,
  ModelProfile,
  ModelProfilePayload,
  ModelProvider,
  ModelProviderPayload,
  PageVisionRecord,
  Project,
  ProjectPayload,
  ResourceSnapshot,
  RetrievalStatus,
  RiskPayload,
  RiskRecord,
  RiskStatus,
  SearchHit,
  ProjectSearchFilters,
  TaskRecord,
} from './types'

interface ApiProblem {
  detail?: string | { code?: string; message?: string; action?: string }
}

async function request<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const response = await fetch(input, { credentials: 'include', ...init })
  if (!response.ok) {
    let problem: ApiProblem = {}
    try {
      problem = (await response.json()) as ApiProblem
    } catch {
      // HTTP status remains the authoritative fallback.
    }
    const detail = problem.detail
    const message = typeof detail === 'string' ? detail : detail?.message
    const action = typeof detail === 'object' ? detail.action : undefined
    throw new Error([message ?? `请求失败（${response.status}）`, action].filter(Boolean).join('；'))
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const api = {
  createSession: () => request<void>('/api/v1/session', { method: 'POST' }),
  listProjects: () => request<Project[]>('/api/v1/projects'),
  createProject: (payload: ProjectPayload) =>
    request<Project>('/api/v1/projects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  gatewayOverview: () => request<GatewayOverview>('/api/v1/gateway'),
  setOfflineMode: (strictOffline: boolean) =>
    request<GatewayOverview>('/api/v1/settings/offline', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ strict_offline: strictOffline }),
    }),
  setModelCache: (enabled: boolean) =>
    request<GatewayOverview>('/api/v1/settings/model-cache', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    }),
  clearModelCache: () =>
    request<{ deleted_entries: number }>('/api/v1/model-cache', { method: 'DELETE' }),
  setProjectExternalAccess: (projectId: string, enabled: boolean) =>
    request<Project>(`/api/v1/projects/${projectId}/external-access`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    }),
  createModelProvider: (payload: ModelProviderPayload) =>
    request<ModelProvider>('/api/v1/model-providers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  updateModelProvider: (providerId: string, payload: ModelProviderPayload) =>
    request<ModelProvider>(`/api/v1/model-providers/${providerId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  toggleModelProvider: (providerId: string) =>
    request<ModelProvider>(`/api/v1/model-providers/${providerId}/toggle`, { method: 'POST' }),
  deleteModelProvider: (providerId: string) =>
    request<void>(`/api/v1/model-providers/${providerId}`, { method: 'DELETE' }),
  createModelProfile: (payload: ModelProfilePayload) =>
    request<ModelProfile>('/api/v1/model-profiles', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  updateModelProfile: (modelId: string, payload: ModelProfilePayload) =>
    request<ModelProfile>(`/api/v1/model-profiles/${modelId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  toggleModelProfile: (modelId: string) =>
    request<ModelProfile>(`/api/v1/model-profiles/${modelId}/toggle`, { method: 'POST' }),
  deleteModelProfile: (modelId: string) =>
    request<void>(`/api/v1/model-profiles/${modelId}`, { method: 'DELETE' }),
  probeGateway: (projectId: string) =>
    request<{ actual_model: string; provider: string; output: string; external_request: boolean }>(
      '/api/v1/model-gateway/probe',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: projectId, capability: 'json_schema' }),
      },
    ),
  listDocuments: (projectId: string) =>
    request<DocumentRecord[]>(`/api/v1/projects/${projectId}/documents`),
  updateDocumentMetadata: (
    projectId: string,
    documentId: string,
    payload: DocumentMetadataPayload,
  ) => request<DocumentRecord>(
    `/api/v1/projects/${projectId}/documents/${documentId}/metadata`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  ),
  listPageAnalyses: (projectId: string, documentId: string) =>
    request<PageVisionRecord[]>(
      `/api/v1/projects/${projectId}/documents/${documentId}/page-analyses`,
    ),
  listTasks: (projectId: string) => request<TaskRecord[]>(`/api/v1/projects/${projectId}/tasks`),
  uploadDocuments: (projectId: string, files: File[]) => {
    const form = new FormData()
    files.forEach((file) => form.append('files', file))
    return request<{ accepted: TaskRecord[]; rejected: { message: string; action: string }[] }>(
      `/api/v1/projects/${projectId}/documents`,
      { method: 'POST', body: form },
    )
  },
  previewFinancialData: (projectId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<FinancialPreview>(`/api/v1/projects/${projectId}/financial-data/preview`, {
      method: 'POST',
      body: form,
    })
  },
  confirmFinancialData: (projectId: string, previewId: string) =>
    request<{ reused_dataset_id: string | null; task: TaskRecord | null }>(
      `/api/v1/projects/${projectId}/financial-data/confirm`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ preview_id: previewId }),
      },
    ),
  listFinancialDatasets: (projectId: string) =>
    request<FinancialDataset[]>(`/api/v1/projects/${projectId}/financial-data`),
  getFinancialDataset: (projectId: string, datasetId: string) =>
    request<FinancialDataset>(`/api/v1/projects/${projectId}/financial-data/${datasetId}`),
  financialResultRows: (
    projectId: string,
    datasetId: string,
    resultId: string,
    offset = 0,
    limit = 100,
  ) =>
    request<FinancialResultRows>(
      `/api/v1/projects/${projectId}/financial-data/${datasetId}/results/${resultId}/rows?offset=${offset}&limit=${limit}`,
    ),
  archiveFinancialDataset: (projectId: string, datasetId: string) =>
    request<FinancialDataset>(
      `/api/v1/projects/${projectId}/financial-data/${datasetId}/archive`,
      { method: 'POST' },
    ),
  reuseFinancialRuleRun: (projectId: string, datasetId: string) =>
    request<{ reused: boolean; run_id: string; rule_set_version: string; message: string }>(
      `/api/v1/projects/${projectId}/financial-data/${datasetId}/rule-runs`,
      { method: 'POST' },
    ),
  changeTask: (projectId: string, taskId: string, action: string) =>
    request<TaskRecord>(`/api/v1/projects/${projectId}/tasks/${taskId}/${action}`, {
      method: 'POST',
    }),
  resources: () => request<ResourceSnapshot>('/api/v1/resources'),
  documentUrl: (projectId: string, documentId: string) =>
    `/api/v1/projects/${projectId}/documents/${documentId}/file`,
  searchDocument: (projectId: string, documentId: string, query: string) =>
    request<SearchHit[]>(
      `/api/v1/projects/${projectId}/documents/${documentId}/search?q=${encodeURIComponent(query)}`,
    ),
  searchProject: (projectId: string, query: string, filters: ProjectSearchFilters = {}) => {
    const parameters = new URLSearchParams({ q: query, limit: '20' })
    Object.entries(filters).forEach(([key, value]) => {
      if (value !== undefined && value !== '') parameters.set(key, String(value))
    })
    return request<SearchHit[]>(`/api/v1/projects/${projectId}/search?${parameters}`)
  },
  retrievalStatus: (projectId: string) =>
    request<RetrievalStatus>(`/api/v1/projects/${projectId}/retrieval/status`),
  listRisks: (projectId: string) =>
    request<RiskRecord[]>(`/api/v1/projects/${projectId}/risks`),
  getRisk: (projectId: string, riskId: string) =>
    request<RiskRecord>(`/api/v1/projects/${projectId}/risks/${riskId}`),
  createRisk: (projectId: string, payload: RiskPayload) =>
    request<RiskRecord>(`/api/v1/projects/${projectId}/risks`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  transitionRisk: (projectId: string, riskId: string, status: RiskStatus, note: string) =>
    request<RiskRecord>(`/api/v1/projects/${projectId}/risks/${riskId}/transition`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status, note }),
    }),
  createFakeRiskExplanation: (projectId: string, riskId: string) =>
    request<{ risk: RiskRecord; external_request: boolean }>(
      `/api/v1/projects/${projectId}/risks/${riskId}/fake-explanation`,
      { method: 'POST' },
    ),
}
