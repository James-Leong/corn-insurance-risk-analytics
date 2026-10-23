from datetime import date, timedelta
import math

from app.core.config import get_settings


class MarketDataAdapter:
    """Provider boundary. Demo data are deterministic and visibly identified."""

    def get_corn_series(self, days: int = 90) -> dict:
        settings = get_settings()
        provider = settings.data_provider.lower()
        if provider == "mock":
            return self._mock_series(days, "mock", "演示模拟数据，不代表真实市场行情")
        if (
            provider in {"parquet", "uqer"}
            or (settings.market_cache_dir / "manifest.json").exists()
            or any(settings.market_cache_dir.glob("*.parquet"))
        ):
            return self._get_cached(days)
        if provider == "auto":
            return self._mock_series(days, "mock", "尚未挂载行情快照；当前为明确标记的模拟行情")
        raise ValueError("Unsupported data provider")

    @staticmethod
    def _mock_series(days: int, provider: str, warning: str) -> dict:
        start = date.today() - timedelta(days=days - 1)
        points = []
        for i in range(days):
            value = 2380 + i * 0.42 + 36 * math.sin(i / 9) + 16 * math.sin(i / 3.8)
            points.append(
                {"date": (start + timedelta(days=i)).isoformat(), "price": round(value, 2)}
            )
        baseline = sum(point["price"] for point in points[-14:]) / 14
        forecast = [
            {
                "step": step,
                "date": (date.fromisoformat(points[-1]["date"]) + timedelta(days=step)).isoformat(),
                "price": round(baseline + step * 0.15, 2),
                "lower": round(baseline - 18 - step * 0.25, 2),
                "upper": round(baseline + 18 + step * 0.25, 2),
            }
            for step in range(1, 15)
        ]
        return {
            "symbol": "玉米期货 C（演示）",
            "unit": "元/吨",
            "provider": provider,
            "warning": warning,
            "series": points,
            "forecast": forecast,
            "forecast_time_unit": "calendar_day",
        }

    @staticmethod
    def _get_cached(days: int) -> dict:
        from app.repositories.market_cache import read_market_snapshot

        settings = get_settings()
        rows, manifest = read_market_snapshot(
            settings.market_cache_dir,
            settings.market_ticker,
            settings.data_start_date,
            settings.data_end_date,
        )
        series = [
            {"date": str(row["tradeDate"])[:10], "price": round(float(row["settlePrice"]), 2)}
            for row in rows[-days:]
        ]
        baseline = sum(point["price"] for point in series[-14:]) / len(series[-14:])
        return {
            "symbol": f"玉米期货 {settings.market_ticker.upper()}（具体合约结算价）",
            "unit": "元/吨",
            "provider": "parquet",
            "warning": (
                f"UQER离线快照；{series[0]['date']}至{series[-1]['date']}；"
                "不代表实时行情。走势为历史均值情景参照，非模型置信区间。"
            ),
            "series": series,
            "forecast": [
                {
                    "step": step,
                    "price": round(baseline, 2),
                    "lower": round(baseline, 2),
                    "upper": round(baseline, 2),
                }
                for step in range(1, 15)
            ],
            "forecast_time_unit": "trading_day",
            "data_as_of": series[-1]["date"],
            "requested_start": manifest["requested_start"],
            "requested_end": manifest["requested_end"],
        }
