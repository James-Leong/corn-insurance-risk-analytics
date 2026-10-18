from dataclasses import dataclass


@dataclass(frozen=True)
class PriceInsuranceScenario:
    insured_tons: float
    guarantee_price: float
    settlement_price: float
    deductible_per_ton: float = 0.0
    payout_cap: float | None = None

    def calculate(self) -> dict[str, float | bool]:
        if (
            self.insured_tons < 0
            or min(self.guarantee_price, self.settlement_price, self.deductible_per_ton) < 0
        ):
            raise ValueError("数量、价格和免赔额不能为负数")
        loss_per_ton = max(
            self.guarantee_price - self.settlement_price - self.deductible_per_ton, 0.0
        )
        payout = loss_per_ton * self.insured_tons
        if self.payout_cap is not None:
            if self.payout_cap < 0:
                raise ValueError("赔付上限不能为负数")
            payout = min(payout, self.payout_cap)
        return {
            "triggered": payout > 0,
            "loss_per_ton": round(loss_per_ton, 2),
            "gross_payout": round(payout, 2),
            "insured_tons": self.insured_tons,
            "guarantee_price": self.guarantee_price,
            "settlement_price": self.settlement_price,
        }
