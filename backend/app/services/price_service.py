"""Checksum-validated, read-only price reports; no training dependencies."""

import hashlib
import json
import math
from datetime import date, timedelta
from pathlib import Path


class PriceError(ValueError):
    def __init__(self, status, message):
        self.status = status
        self.message = message
        super().__init__(message)


def has_horizon_capacity(as_of: str, expiry: str) -> bool:
    """Weekdays are an upper bound; actual future exchange dates remain unconfirmed."""
    start, end = date.fromisoformat(as_of), date.fromisoformat(expiry)
    return (
        sum(
            (start + timedelta(days=i)).weekday() < 5
            for i in range(1, max(0, (end - start).days) + 1)
        )
        >= 20
    )


def overview(root: Path, ticker: str = "c2701"):
    try:
        manifest_path = root / "manifest.json"
        if manifest_path.is_symlink():
            raise ValueError("Manifest symlink")
        manifest = json.loads(manifest_path.read_bytes())
        if (
            manifest["schema_version"] != "price-store-v1"
            or manifest["data_start"] != "2025-12-31"
            or manifest["data_end"] != "2026-10-23"
        ):
            raise ValueError("Invalid scope")
        if ticker not in manifest["documents"]:
            raise PriceError(404, "未找到该玉米合约的价格报告")
        entry = manifest["documents"][ticker]
        path = root / entry["file"]
        if (
            entry["file"] != f"{ticker}.json"
            or path.is_symlink()
            or not path.resolve().is_relative_to(root.resolve())
        ):
            raise ValueError("Invalid path")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError("Checksum mismatch")
        result = json.loads(raw)
        if (
            result["schema_version"] != "price-v1"
            or result["ticker"] != ticker
            or result["model_version"] != manifest["model_version"]
            or result["data_start"] != manifest["data_start"]
            or result["data_end"] != manifest["data_end"]
        ):
            raise ValueError("Identity mismatch")
        series = result["series"]
        dates = [row["date"] for row in series]
        if (
            not dates
            or dates != sorted(set(dates))
            or dates[-1] != result["as_of"]
            or any(not result["data_start"] <= date <= result["data_end"] for date in dates)
            or any(not math.isfinite(row["settlement"]) or row["settlement"] <= 0 for row in series)
        ):
            raise ValueError("Invalid time series")
        forecast = result["forecast"]
        if forecast["status"] == "available":
            if (
                result["as_of"] != result["data_end"]
                or not has_horizon_capacity(result["as_of"], result["last_trade_date"])
                or result["last_trade_date"] <= result["as_of"]
                or {m["method_id"] for m in forecast["methods"]}
                != {"price_last", "price_ma20", "price_ridge"}
                or any(
                    not math.isfinite(m["value"]) or m["value"] <= 0 for m in forecast["methods"]
                )
            ):
                raise ValueError("Invalid forecast")
        elif forecast["status"] != "unavailable" or forecast["methods"]:
            raise ValueError("Invalid unavailable forecast")
        if (
            forecast["horizon_trading_days"] != 20
            or forecast["target_dates"] is not None
            or forecast["target"] != "future_mean_settlement"
        ):
            raise ValueError("Invalid target")
        for point in result["validation"]["backtest"]:
            if not (
                manifest["split_manifest"]["validation_start"]
                <= point["as_of"]
                < point["label_available_at"]
                <= result["data_end"]
            ):
                raise ValueError("Invalid validation chronology")
        return result
    except PriceError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise PriceError(503, "价格研究报告缺失或校验失败，请挂载完整离线产物") from exc
