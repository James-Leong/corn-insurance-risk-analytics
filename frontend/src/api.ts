import type { Dashboard, MarketData, ScenarioResult } from './types/api'
const base = '/api/v1'
async function get<T>(path: string): Promise<T> { const response = await fetch(`${base}${path}`); if (!response.ok) throw new Error(`请求失败 (${response.status})`); return response.json() }
export const api = {
  dashboard: () => get<Dashboard>('/dashboard'),
  market: () => get<MarketData>('/market/corn'),
  scenario: async (body: { insured_tons: number; guarantee_price: number; settlement_price: number; deductible_per_ton: number; payout_cap: number | null }) => {
    const response = await fetch(`${base}/insurance/scenario`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    if (!response.ok) throw new Error(`计算失败 (${response.status})`)
    return response.json() as Promise<ScenarioResult>
  },
}

import type { ComparisonGroup, ComparisonRun, ComparisonMetrics, ComparisonCase, Evidence, Partition } from './types/comparison'
async function comparisonGet<T>(path: string): Promise<T> {
  const response = await fetch(`${base}/comparisons${path}`)
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const detail = body?.detail
    throw new Error(typeof detail?.message === 'string' ? detail.message : `研究报告读取失败 (${response.status})`)
  }
  return response.json()
}
export const comparisonApi = {
  groups: () => comparisonGet<{ items: ComparisonGroup[]; default_group_id: string | null; empty_reason: string | null; data_mode: string }>('/groups'),
  runs: (group: string) => comparisonGet<{ items: ComparisonRun[] }>(`/groups/${encodeURIComponent(group)}/runs`),
  run: (run: string, partition: Partition) => comparisonGet<ComparisonRun>(`/runs/${encodeURIComponent(run)}?partition=${partition}`),
  metrics: (run: string, partition: Partition) => comparisonGet<ComparisonMetrics>(`/runs/${encodeURIComponent(run)}/metrics?partition=${partition}`),
  cases: (run: string, partition: Partition) => comparisonGet<{ items: ComparisonCase[] }>(`/runs/${encodeURIComponent(run)}/cases?partition=${partition}`),
  evidence: (run: string, partition: Partition, view: string) => comparisonGet<Evidence>(`/runs/${encodeURIComponent(run)}/evidence?partition=${partition}&view=${encodeURIComponent(view)}`),
  exportUrl: (run: string, partition: Partition, format: 'json' | 'csv') => `${base}/comparisons/runs/${encodeURIComponent(run)}/export?partition=${partition}&format=${format}`,
}
