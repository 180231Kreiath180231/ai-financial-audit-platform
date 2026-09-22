import type {
  DocumentRecord,
  GatewayOverview,
  ModelProfile,
  ModelProfilePayload,
  ModelProvider,
  ModelProviderPayload,
  Project,
  ProjectPayload,
  ResourceSnapshot,
  SearchHit,
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
  toggleModelProvider: (providerId: string) =>
    request<ModelProvider>(`/api/v1/model-providers/${providerId}/toggle`, { method: 'POST' }),
  createModelProfile: (payload: ModelProfilePayload) =>
    request<ModelProfile>('/api/v1/model-profiles', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  toggleModelProfile: (modelId: string) =>
    request<ModelProfile>(`/api/v1/model-profiles/${modelId}/toggle`, { method: 'POST' }),
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
  listTasks: (projectId: string) => request<TaskRecord[]>(`/api/v1/projects/${projectId}/tasks`),
  uploadDocuments: (projectId: string, files: File[]) => {
    const form = new FormData()
    files.forEach((file) => form.append('files', file))
    return request<{ accepted: TaskRecord[]; rejected: { message: string; action: string }[] }>(
      `/api/v1/projects/${projectId}/documents`,
      { method: 'POST', body: form },
    )
  },
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
}
