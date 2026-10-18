import type { Dashboard, MarketData, ScenarioResult } from './types/api'
const base = '/api/v1'
async function get<T>(path: string): Promise<T> { const response = await fetch(`${base}${path}`); if (!response.ok) throw new Error(`请求失败 (${response.status})`); return response.json() }
export const api = {
  dashboard: () => get<Dashboard>('/dashboard'),
  market: () => get<MarketData>('/market/corn'),
  scenario: async (body: { insured_tons: number; guarantee_price: number; settlement_price: number; deductible_per_ton: number; payout_cap: number }) => {
    const response = await fetch(`${base}/insurance/scenario`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    if (!response.ok) throw new Error(`计算失败 (${response.status})`)
    return response.json() as Promise<ScenarioResult>
  },
}
