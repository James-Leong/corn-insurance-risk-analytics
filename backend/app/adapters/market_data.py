from datetime import date, timedelta
import math

from app.core.config import get_settings


class MarketDataAdapter:
    """Provider boundary. Demo data are deterministic and visibly identified."""

    def get_corn_series(self, days: int = 90) -> dict:
        settings = get_settings()
        if settings.data_provider.lower() == "uqer" and settings.uqer_token:
            try:
                return self._get_uqer(days, settings.uqer_token)
            except Exception as exc:
                return self._mock_series(
                    days, "mock_fallback", f"UQER 获取失败（{type(exc).__name__}），已回退模拟数据"
                )
        return self._mock_series(days, "mock", "演示模拟数据，不代表真实市场行情")

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
    def _get_uqer(days: int, token: str) -> dict:
        """Optional integration using the public UQER DataAPI calling convention.

        Install the UQER SDK in the runtime and supply a token via environment.
        SDK availability depends on the deployment environment. No credential is logged.
        """
        import uqer
        from uqer import DataAPI

        uqer.Client(token=token)
        end = date.today()
        begin = end - timedelta(days=days * 2)  # calendar days include weekends/holidays
        frame = DataAPI.MktFutdGet(
            beginDate=begin.strftime("%Y%m%d"),
            endDate=end.strftime("%Y%m%d"),
            exchangeCD="XDCE",
            contractObject="c",
            field="",
            pandas="1",
        )
        if frame is None or frame.empty:
            raise RuntimeError("UQER 返回空行情")
        price_column = next(
            (name for name in ("closePrice", "settlePrice", "close") if name in frame.columns), None
        )
        date_column = next(
            (name for name in ("tradeDate", "barDate", "date") if name in frame.columns), None
        )
        if not price_column or not date_column:
            raise RuntimeError("UQER 行情缺少日期/收盘价字段")
        clean = frame[[date_column, price_column]].dropna().tail(days)
        if clean.empty:
            raise RuntimeError("UQER 无可用行情记录")
        series = [
            {
                "date": str(row[date_column])[:10].replace("/", "-"),
                "price": round(float(row[price_column]), 2),
            }
            for _, row in clean.iterrows()
        ]
        baseline = sum(item["price"] for item in series[-14:]) / min(len(series), 14)
        forecast = [
            {
                "step": step,
                "price": round(baseline, 2),
                "lower": round(baseline - 20, 2),
                "upper": round(baseline + 20, 2),
            }
            for step in range(1, 15)
        ]
        # Daily observations define a trading-day horizon. Without an exchange
        # calendar, keep relative horizons rather than inventing concrete dates.
        return {
            "symbol": "玉米期货 C 大商所（近月样本）",
            "unit": "元/吨",
            "provider": "uqer",
            "warning": "UQER 实时/历史行情；合约滚动与连续合约处理仍需完善",
            "series": series,
            "forecast": forecast,
            "forecast_time_unit": "trading_day",
        }
