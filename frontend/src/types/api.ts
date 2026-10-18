export interface Point { date: string; price: number }
export interface ForecastPoint { step: number; date?: string; price: number; lower: number; upper: number }
export interface MarketData { symbol: string; unit: string; provider: string; warning: string; series: Point[]; forecast: ForecastPoint[]; forecast_time_unit?: 'calendar_day' | 'trading_day' }
export interface Dashboard { data_provider: string; data_warning: string; latest_price: number; daily_change: number; volatility_proxy: number; forecast_horizon_days: number; forecast_method: string; risk_note: string }
export interface ScenarioResult { triggered: boolean; loss_per_ton: number; gross_payout: number; insured_tons: number; guarantee_price: number; settlement_price: number }
