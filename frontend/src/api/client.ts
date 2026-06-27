import type {
  AnalystReport,
  BLEDetail,
  CopilotAnswer,
  DashboardResponse,
  DecisionRecord,
  DecisionRequest,
  EvalRunSummary,
  FundDetail,
  FundSummary,
  RiskScore,
  RulesetConfig,
  SuggestionItem,
} from '../types'

const BASE = (import.meta.env.VITE_API_BASE_URL ?? '') + '/api'

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(`GET ${path} → ${res.status}`)
  return res.json() as Promise<T>
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const detail = await res.text()
    throw new Error(`POST ${path} → ${res.status}: ${detail}`)
  }
  return res.json() as Promise<T>
}

async function postForm<T>(path: string, formData: FormData): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { method: 'POST', body: formData })
  if (!res.ok) {
    const detail = await res.text()
    throw new Error(`POST ${path} → ${res.status}: ${detail}`)
  }
  return res.json() as Promise<T>
}

export interface UploadedDoc {
  document_id: string
  filename: string | null
  document_type: string
  status: string
  expiry_date: string | null
  extraction_status: string
  embedding_status: string
}

export interface ExtractionResult {
  document_id: string
  extraction_status: string
  extracted_fields: Record<string, unknown>
}

export interface ScreeningResult {
  screened_entities: number
  triggers_fired: number
  cards_created: number
  results: Array<{
    name: string
    scope: string
    result: string
    severity: string | null
    hit_type: string | null
    datasets: string[]
    screened_at: string | null
    match_name: string | null
  }>
}

export const api = {
  getDashboard: () => get<DashboardResponse>('/dashboard'),
  getFunds: () => get<FundSummary[]>('/funds'),
  getFund: (fundId: string) => get<FundDetail>(`/funds/${fundId}`),
  getFundRiskScore: (fundId: string) => get<RiskScore>(`/funds/${fundId}/risk-score`),
  getBLE: (bleId: string) => get<BLEDetail>(`/bles/${bleId}`),
  getBLERiskScore: (bleId: string) => get<RiskScore>(`/bles/${bleId}/risk-score`),

  getSuggestions: (status = 'pending') =>
    get<SuggestionItem[]>(`/suggestions?status=${status}`),
  acceptSuggestion: (id: string, body: { actor: string; notes?: string }) =>
    post<Record<string, string>>(`/suggestions/${id}/accept`, body),
  declineSuggestion: (id: string, body: { actor: string; notes?: string }) =>
    post<Record<string, string>>(`/suggestions/${id}/decline`, body),
  bulkAccept: (body: { ids: string[]; actor: string }) =>
    post<Record<string, string>[]>('/suggestions/bulk-accept', body),
  bulkDecline: (body: { ids: string[]; actor: string; notes?: string }) =>
    post<Record<string, string>[]>('/suggestions/bulk-decline', body),

  askCopilot: (body: {
    question: string
    fund_id?: string
    scope?: string
    scope_id?: string
  }) => post<CopilotAnswer>('/copilot/ask', body),

  getRuleset: () => get<RulesetConfig>('/admin/ruleset'),
  publishRuleset: (config: RulesetConfig) =>
    post<RulesetConfig>('/admin/ruleset', config),
  runScreening: () => post<ScreeningResult>('/admin/run-screening'),
  screenSingleBle: (bleId: string) => post<ScreeningResult>(`/admin/screen-ble/${bleId}`),
  getLastScreening: async (bleId: string): Promise<ScreeningResult | null> => {
    const res = await fetch(`${BASE}/admin/screen-ble/${bleId}`)
    if (res.status === 404) return null
    if (!res.ok) throw new Error(`GET /admin/screen-ble/${bleId} → ${res.status}`)
    return res.json() as Promise<ScreeningResult>
  },

  getEvals: () => get<EvalRunSummary[]>('/evals'),

  getAnalystReport: (scope: string, scopeId: string) =>
    get<AnalystReport>(`/analyst-reports/${scope}/${scopeId}`),

  submitDecision: (scope: string, scopeId: string, body: DecisionRequest) =>
    post<DecisionRecord>(`/analyst-reports/${scope}/${scopeId}/decision`, body),

  uploadFundDocument: (fundId: string, formData: FormData) =>
    postForm<UploadedDoc>(`/funds/${fundId}/documents`, formData),
  listFundUploadedDocs: (fundId: string) =>
    get<UploadedDoc[]>(`/funds/${fundId}/documents`),
  uploadBLEDocument: (bleId: string, formData: FormData) =>
    postForm<UploadedDoc>(`/bles/${bleId}/documents`, formData),
  listBLEUploadedDocs: (bleId: string) =>
    get<UploadedDoc[]>(`/bles/${bleId}/documents`),

  extractDocument: (documentId: string) =>
    post<ExtractionResult>(`/documents/${documentId}/extract`),
}
