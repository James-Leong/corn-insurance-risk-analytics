export type Partition = 'validation' | 'test'
export interface ComparisonGroup { comparison_group_id: string; title: string; run_count: number }
export interface Selection { frozen: boolean; selected_method_id: string | null; reason_code: string }
export interface ComparisonRun {
  schema_version: string; run_id: string; comparison_group_id: string; title: string; created_at: string
  source_kind: 'measured' | 'schema_fixture'; label_kind: string; run_status: string
  data_start: string; data_end: string; warnings: string[]; protocol: Record<string, unknown>
  selection: Selection; released_partitions: Partition[]
}
export interface Metric { metric_id: string; value: number | null; unit: string; direction: string; missing_reason?: string }
export interface ComparisonModel {
  method_id: string; task?: string; model_version: string | null; release_state: string
  coverage: number; failure_count: number; reason_code?: string; metrics: Metric[]
}
export interface ComparisonMetrics {
  run_id: string; partition: Partition; sample_count: number; date_count: number; models: ComparisonModel[]; selection: Selection
}
export interface CaseOutput {
  method_id: string; claim_probability: number | null; conditional_mean_payout?: number | null
  expected_payout: number | null; p90_payout: number | null; p90_status: string; reason_code?: string
  scenario_payout?: number | null; reference_price?: number | null
}
export interface ComparisonCase {
  case_id: string; valuation_date: string; contract_id: string; guarantee_price: number; quantity_tons: number
  observed_payout: number | null; outputs: CaseOutput[]; observation_dates?: string[]
  deductible_per_ton?: number; payout_cap?: number | null; price_field?: string
}
export interface Evidence { run_id: string; partition: Partition; view: string; items: Record<string, unknown>[] }
