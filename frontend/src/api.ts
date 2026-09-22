import type {
  DocumentRecord,
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
