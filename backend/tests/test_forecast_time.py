from datetime import date, timedelta

import pytest
from app.adapters import market_data
from app.adapters.market_data import MarketDataAdapter


@pytest.mark.parametrize("provider", ["mock", "mock_fallback"])
def test_mock_forecast_dates_follow_latest_sample_across_leap_day(monkeypatch, provider):
    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2028, 2, 28)

    monkeypatch.setattr(market_data, "date", FixedDate)
    data = MarketDataAdapter._mock_series(90, provider, "test")
    assert data["forecast_time_unit"] == "calendar_day"
    origin = date.fromisoformat(data["series"][-1]["date"])
    assert data["forecast"][0]["date"] == "2028-02-29"
    assert data["forecast"][1]["date"] == "2028-03-01"
    assert len(data["forecast"]) == 14
    for point in data["forecast"]:
        assert date.fromisoformat(point["date"]) == origin + timedelta(days=point["step"])
