export type RiskTier = 'low' | 'medium' | 'high' | 'critical'

export interface DocumentInfo {
  doc_id: string
  document_type: string
  status: string
  expiry_date: string | null
  extraction_status: string
  embedding_status: string
}

export interface BLESummary {
  ble_id: string
  fund_id: string
  name: string
  tier: RiskTier
  score: number
  screening_is_real: boolean
  last_trigger_type: string | null
}

export interface FundSummary {
  fund_id: string
  name: string
  incorporation_country: string
  direct_tier: RiskTier
  direct_score: number
  escalated_tier: RiskTier | null
  escalation_reason: string | null
  synthetic_static: boolean
  synthetic_profile: boolean
  bles: BLESummary[]
}

export interface FundDetail extends FundSummary {
  ubo_chain_layers: number
  ubo_chain_resolved: boolean
  documents: DocumentInfo[]
  ruleset_version: string
  factor_scores: Record<string, number>
}

export interface ProductInfo {
  product_id: string
  product_type: string
  workflow_template: string
  status: string
}

export interface BLEDetail {
  ble_id: string
  fund_id: string
  fund_name: string
  name: string
  tier: RiskTier
  score: number
  screening_is_real: boolean
  institution: string
  location: string
  counterparty_country: string
  screening_status: string
  hit_type: string | null
  hit_severity: string | null
  products: ProductInfo[]
  documents: DocumentInfo[]
  factor_scores: Record<string, number>
  ruleset_version: string
}

export interface HighRiskEntry {
  fund_id: string
  fund_name: string
  synthetic_static: boolean
  effective_tier: RiskTier
  direct_tier: RiskTier
  direct_score: number
  escalated_ble_name: string | null
  last_trigger_type: string | null
}

export interface DashboardResponse {
  total_funds: number
  live_funds: number
  high_critical_count: number
  tier_distribution: Record<string, number>
  high_risk_queue: HighRiskEntry[]
}

export interface SuggestionItem {
  suggestion_id: string
  scope: string
  scope_id: string
  fund_id: string
  fund_name: string
  ble_name: string | null
  trigger_type: string
  what_changed_summary: string
  status: string
  created_at: string
  cascade_info: Record<string, string> | null
}

export interface CitationItem {
  text: string
  doc_id: string
  document_type: string
}

export interface CopilotAnswer {
  question: string
  routing: string
  answer: string
  sql: string | null
  citations: CitationItem[]
  is_mock: boolean
}

export interface RulesetConfig {
  version: string
  scope_level: string
  weight_country: number
  weight_screening: number
  weight_pep: number
  weight_ubo: number
  weight_documents: number
  hard_stop_enabled: boolean
  escalation_enabled: boolean
}

export interface RiskScore {
  direct_score: number
  direct_tier: RiskTier
  escalated_tier: RiskTier | null
  escalation_reason: string | null
  hard_stop: boolean
  factor_scores: Record<string, number>
}

export interface EvalRunSummary {
  eval_category: string
  label: string
  last_run_at: string | null
  pass_count: number
  fail_count: number
  pass_rate: number
  latency_ms: number
  cost_usd: number
  status: string
  is_mock: boolean
}

export interface ReportCitation {
  claim: string
  doc_id: string
  citation_text: string
  document_type: string
}

export interface DecisionRequest {
  decision: 'accepted' | 'rejected' | 'edited'
  actor: string
  notes?: string
  edited_narrative?: string
}

export interface DecisionRecord extends DecisionRequest {
  scope: string
  scope_id: string
  fund_id: string
  decided_at: string
}

export interface AnalystReport {
  scope: string
  scope_id: string
  fund_id: string
  fund_name: string
  ble_name: string | null
  effective_tier: RiskTier
  direct_tier: RiskTier
  direct_score: number
  escalation_reason: string | null
  escalated_ble_names: string[]
  factor_scores: Record<string, number>
  narrative: string
  citations: ReportCitation[]
  document_status: DocumentInfo[]
  screening_status: string | null
  hit_type: string | null
  ruleset_version: string
  model: string
  prompt_version: string
  is_mock: boolean
  generated_at: string
}
