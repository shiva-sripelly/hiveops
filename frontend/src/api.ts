// Typed client for the HiveOps API.

export type RunStatus = 'queued' | 'running' | 'awaiting_approval' | 'completed' | 'failed' | 'rejected'

export interface Step {
  agent: string
  instruction: string
  approval: boolean
}

export interface Workflow {
  id: string
  name: string
  description: string
  mode: 'custom' | 'auto'
  steps: Step[]
  defaultTask: string
  isTemplate: boolean
  updatedAt: string
  runCount?: number
}

export interface RunSummary {
  id: string
  workflowId: string | null
  workflowName: string
  mode: string
  task: string
  status: RunStatus
  plan: string[]
  tokens: number
  cost: number
  latencyMs: number
  createdAt: string
  finishedAt: string | null
}

export interface RunEvent {
  seq: number
  type: string
  agent: string | null
  message: string
  data: Record<string, unknown>
  ts: string
}

export interface Approval {
  id: string
  runId: string
  kind: 'tool_action' | 'step_output'
  agent: string
  title: string
  payload: { tool?: string; args?: Record<string, string>; output?: string; agent: string; kind: string }
  status: 'pending' | 'approved' | 'rejected' | 'cancelled'
  comment: string
  createdAt: string
  decidedAt: string | null
  workflowName?: string
  task?: string
}

export interface RunDetail extends RunSummary {
  steps: Step[]
  output: string
  sources: string[]
  error: string | null
  provider: string
  model: string
  tokensIn: number
  tokensOut: number
  events: RunEvent[]
  approvals: Approval[]
  deliveries: { channel: string; recipient: string; subject: string; delivered: boolean; detail: string }[]
}

export interface Agent {
  id: string
  name: string
  role: string
  color: string
  tools: { name: string; requiresApproval: boolean; description: string }[]
  system: string
}

export interface AgentHealth {
  id: string
  name: string
  color: string
  calls: number
  avgLatencyMs: number | null
  tokens: number
  cost: number
  errors: number
  errorRate: number
}

export interface EvalMetrics {
  cases: number
  passRate: number
  retrievalHitRate: number
  avgRecall: number
  avgGroundedness: number
  avgLatencyMs: number
  totalTokens: number
  totalCost: number
}

export interface Dashboard {
  kpis: {
    spend: number
    spendChange: number | null
    runs: number
    runsChange: number | null
    successRate: number | null
    approvalRate: number | null
    pendingApprovals: number
    activeAgents: number
    totalAgents: number
    avgLatencyMs: number | null
    tokens: number
  }
  daily: { date: string; cost: number; runs: number; failed: number }[]
  routing: { edges: { from: string; to: string; count: number }[]; stages: Record<string, number> }
  agents: AgentHealth[]
  statusCounts: Record<string, number>
  pendingApprovals: Approval[]
  recentRuns: RunSummary[]
  latestEval: { id: string; metrics: EvalMetrics; createdAt: string } | null
}

export interface DocumentInfo {
  id: string
  name: string
  kind: string
  size: number
  chunks: number
  createdAt: string
}

export interface SearchHit {
  document: string
  documentId: string
  chunkId: number
  text: string
  score: number
}

export interface DatasetInfo {
  id: string
  name: string
  source: string
  rows: number
  columns: { name: string; type: 'number' | 'string' }[]
  createdAt: string
}

export interface DatasetDetail extends DatasetInfo {
  preview: Record<string, string | number | null>[]
}

export interface OutboxItem {
  id: number
  runId: string | null
  channel: string
  recipient: string
  subject: string
  body: string
  delivered: boolean
  detail: string
  createdAt: string
}

export interface EvalCaseResult {
  question: string
  answer: string
  error: string | null
  retrieved: string[]
  expectedSource: string | null
  retrievalHit: boolean
  recall: number
  groundedness: number
  passed: boolean
  latencyMs: number
  tokens: number
  cost: number
}

export interface EvalSuite {
  id: string
  name: string
  description: string
  cases: { question: string; expected: string[]; expected_source: string }[]
}

export interface EvalRun {
  id: string
  suiteId: string
  suiteName: string
  status: 'running' | 'completed' | 'failed'
  provider: string
  model: string
  metrics: EvalMetrics | Record<string, never>
  results: EvalCaseResult[]
  createdAt: string
}

export interface Health {
  status: string
  version: string
  database: string
  databaseOk: boolean
  vectorStore: string
  redis: boolean | null
  llm: { provider: string; model: string; simulated: boolean }
  workers: number
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init)
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') message = body.detail
      else if (Array.isArray(body.detail)) message = body.detail.map((d: { msg: string }) => d.msg).join('; ')
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, message)
  }
  return res.status === 204 ? (undefined as T) : res.json()
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

const upload = (file: File): RequestInit => {
  const form = new FormData()
  form.append('file', file)
  return { method: 'POST', body: form }
}

export const api = {
  health: () => request<Health>('/api/health'),
  dashboard: () => request<Dashboard>('/api/dashboard'),
  agents: () => request<Agent[]>('/api/agents'),

  workflows: () => request<Workflow[]>('/api/workflows'),
  workflow: (id: string) => request<Workflow>(`/api/workflows/${id}`),
  saveWorkflow: (wf: Omit<Workflow, 'id' | 'isTemplate' | 'updatedAt'>, id?: string) =>
    request<Workflow>(id ? `/api/workflows/${id}` : '/api/workflows', json(id ? 'PUT' : 'POST', { ...wf, default_task: wf.defaultTask })),
  deleteWorkflow: (id: string) => request<void>(`/api/workflows/${id}`, { method: 'DELETE' }),
  runWorkflow: (id: string, task: string) => request<RunSummary>(`/api/workflows/${id}/run`, json('POST', { task })),

  runs: (status?: string) => request<RunSummary[]>(`/api/runs${status ? `?status=${status}` : ''}`),
  run: (id: string) => request<RunDetail>(`/api/runs/${id}`),
  cancelRun: (id: string) => request<{ status: string }>(`/api/runs/${id}/cancel`, { method: 'POST' }),

  approvals: (status?: string) => request<Approval[]>(`/api/approvals${status ? `?status=${status}` : ''}`),
  decide: (id: string, approved: boolean, comment: string) =>
    request<Approval>(`/api/approvals/${id}/decide`, json('POST', { approved, comment })),

  documents: () => request<DocumentInfo[]>('/api/documents'),
  uploadDocument: (file: File) => request<{ id: string; name: string; chunks: number }>('/api/documents', upload(file)),
  deleteDocument: (id: string) => request<void>(`/api/documents/${id}`, { method: 'DELETE' }),
  search: (query: string, k = 5) => request<SearchHit[]>('/api/documents/search', json('POST', { query, k })),

  datasets: () => request<DatasetInfo[]>('/api/datasets'),
  dataset: (id: string) => request<DatasetDetail>(`/api/datasets/${id}`),
  uploadDataset: (file: File) => request<DatasetInfo>('/api/datasets', upload(file)),
  deleteDataset: (id: string) => request<void>(`/api/datasets/${id}`, { method: 'DELETE' }),
  outbox: () => request<OutboxItem[]>('/api/outbox'),

  evalSuites: () => request<EvalSuite[]>('/api/evals/suites'),
  evalRuns: () => request<EvalRun[]>('/api/evals/runs'),
  runEval: (suiteId: string) => request<{ id: string }>(`/api/evals/suites/${suiteId}/run`, { method: 'POST' }),
}
