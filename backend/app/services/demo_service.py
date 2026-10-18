from app.adapters.market_data import MarketDataAdapter
from app.domain.insurance import PriceInsuranceScenario


class DemoService:
    def __init__(self) -> None:
        self.market = MarketDataAdapter()

    def dashboard(self) -> dict:
        data = self.market.get_corn_series()
        prices = [item["price"] for item in data["series"]]
        return {
            "data_provider": data["provider"],
            "data_warning": data["warning"],
            "latest_price": prices[-1],
            "daily_change": round(prices[-1] - prices[-2], 2),
            "volatility_proxy": round(max(prices[-20:]) - min(prices[-20:]), 2),
            "forecast_horizon_days": len(data["forecast"]),
            "forecast_method": "14日移动均值 + 趋势外推（基线）",
            "risk_note": "预测仅供情景讨论；保险赔付须依据合同结算价和条款。",
        }

    def scenario(
        self,
        insured_tons: float,
        guarantee_price: float,
        settlement_price: float,
        deductible_per_ton: float = 0,
        payout_cap: float | None = None,
    ) -> dict:
        return PriceInsuranceScenario(
            insured_tons, guarantee_price, settlement_price, deductible_per_ton, payout_cap
        ).calculate()
