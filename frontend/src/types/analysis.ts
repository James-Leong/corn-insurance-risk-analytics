export interface AnalysisInput { ticker: string; valuation_date: string; strike_ratio: number; quantity: number; budget: number; deductible: number; payout_cap: number | null; shocks: number[] }
export interface AnalysisOptions { schema_version: string; run_id: string; contracts: { ticker: string; valuation_dates: string[] }[]; strike_ratios: number[]; defaults: AnalysisInput; warnings: string[] }
export interface AnalysisReport { schema_version: string; report_id: string; run_id: string; release_state: string; request: AnalysisInput; contract: { ticker: string; valuation_date: string; settlement: number; guarantee_price: number; quantity: number; observation_start: string; observation_end: string }; methods: { method_id: string; name: string; claim_probability: number | null; conditional_mean_payout: number | null; expected_payout: number | null; p90_payout: number | null }[]; price_references: { last: number; ma20: number }; observed: { mean_settlement: number; payout: number }; stress: { shock_percent: number; scenario_price: number; gross_payout: number; net_payout: number; budget_gap: number }[]; versions: { data: string; model: string; rule: string }; warnings: string[] }

export interface UnderwritingDecision {
  outcome: 'accept' | 'adjust' | 'decline'
  method_id: string
  method_name: string
  expected_payout: number
  expected_payout_limit: number | null
  reason: string
  source_report_id: string
}
export interface UnderwritingPlan {
  source_report_id: string
  contract: AnalysisReport['contract']
  price_rule: string
  deductible_per_ton: number
  payout_cap: number | null
  budget: number
  model_scope: 'matched' | 'base_terms_only'
  decision: UnderwritingDecision
}
export interface UnderwritingTrial {
  price_source: 'historical' | 'scenario'
  settlement_price: number
  payout: number
  budget_gap: number
}
