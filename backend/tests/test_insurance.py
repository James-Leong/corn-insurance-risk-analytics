from app.domain.insurance import PriceInsuranceScenario


def test_scenario_applies_deductible_and_cap():
    result = PriceInsuranceScenario(
        100, 2600, 2500, deductible_per_ton=20, payout_cap=5000
    ).calculate()
    assert result["triggered"] is True
    assert result["gross_payout"] == 5000


def test_scenario_not_triggered_above_guarantee():
    result = PriceInsuranceScenario(100, 2500, 2550).calculate()
    assert result["triggered"] is False
    assert result["gross_payout"] == 0
