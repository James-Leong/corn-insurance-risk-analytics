"""Versioned database observations and verified local corn snapshots."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from app.core.config import get_settings
from app.repositories.market_cache import MarketCacheError, read_market_snapshot

SNAPSHOTS = Path(__file__).resolve().parents[2] / "data" / "platform"
CASDE_FIELDS = {
    "production": "产量",
    "imports_my": "市场年度进口",
    "domestic_consumption": "国内消费",
    "food_use": "食用消费",
    "feed_use": "饲用消费",
    "industrial_use": "工业消费",
    "seed_use": "种子用量",
    "loss_other": "损耗及其它",
    "exports_my": "市场年度出口",
    "stock_change": "结余变化",
    "ending_stocks": "期末库存",
    "domestic_share": "国内使用占用途比",
    "export_share": "出口占用途比",
    "stocks_to_use": "库存/总使用",
}
DERIVED = {
    "domestic_share": "C/(C+X)",
    "export_share": "X/(C+X)",
    "stocks_to_use": "E/(C+X)",
}
MARKET_FIELDS = {
    "settlePrice": ("结算价", "元/吨"),
    "closePrice": ("收盘价", "元/吨"),
    "turnoverVol": ("成交量", "手"),
    "openInt": ("持仓量", "手"),
}


def read_casde() -> dict:
    document = json.loads((SNAPSHOTS / "casde_20261009.json").read_text())
    source = (SNAPSHOTS / document["source_file"]).read_bytes()
    if hashlib.sha256(source).hexdigest() != document["source_file_sha256"]:
        raise ValueError("CASDE原文校验失败，禁止加载派生数据")
    return document


def _manifest() -> dict | None:
    path = get_settings().market_cache_dir / "manifest.json"
    try:
        manifest = json.loads(path.read_text())
        return manifest if isinstance(manifest, dict) else None
    except (OSError, ValueError):
        return None


def catalog() -> dict:
    manifest = _manifest()
    coverage = {}
    if manifest:
        try:
            for ticker in manifest.get("tickers", []):
                rows, _ = read_market_snapshot(
                    get_settings().market_cache_dir,
                    ticker,
                    manifest["requested_start"],
                    manifest["requested_end"],
                )
                coverage[ticker] = {
                    field: sum(row.get(field) is not None for row in rows)
                    for field in MARKET_FIELDS
                }
        except (MarketCacheError, KeyError):
            coverage = {}
    sources = [
        {
            "id": "uqer",
            "name": "UQER具体合约离线行情",
            "status": "available" if manifest else "not_connected",
            "source_uri": "https://uqer.datayes.com/",
            "note": "非实时；历史原始发布时间未核实，研究回放须披露可得时点假设。",
        },
        {
            "id": "casde",
            "name": "农业农村部CASDE",
            "status": "available",
            "source_uri": read_casde()["source_uri"],
            "note": "2026年10月公开报告固定快照；没有玉米库存水平。",
        },
        {
            "id": "customs",
            "name": "中国海关玉米贸易",
            "status": "not_connected",
            "source_uri": "http://stats.customs.gov.cn/",
            "note": "尚未取得可追溯月度文件；禁止将供需表年度进口当作海关月度贸易。",
        },
        {
            "id": "usda_psd",
            "name": "USDA国别供需",
            "status": "not_connected",
            "source_uri": "https://apps.fas.usda.gov/psdonline/app/index.html",
            "note": "美国、巴西、阿根廷、乌克兰待接入；MY与TY须分开。",
        },
        {
            "id": "weather",
            "name": "天气与农情",
            "status": "not_connected",
            "source_uri": "https://www.nmc.cn/publish/crop/index.htm",
            "note": "待确认授权、站点范围与历史发布版本。",
        },
    ]
    series = []
    for ticker in (manifest or {}).get("tickers", []):
        quality = manifest.get("quality", {}).get(ticker, {})
        for field, (label, unit) in MARKET_FIELDS.items():
            series.append(
                {
                    "id": f"market.{ticker}.{field}",
                    "name": f"{ticker.upper()} {label}",
                    "unit": unit,
                    "source_id": "uqer",
                    "status": "available"
                    if coverage.get(ticker, {}).get(field, 0)
                    else "unavailable",
                    "kind": "market",
                    "ticker": ticker,
                    "field": field,
                    "definition": f"具体合约日频{label}；不拼接连续合约",
                    "non_null_count": coverage.get(ticker, {}).get(field, 0),
                    "start_date": quality.get("first_date", manifest["requested_start"]),
                    "end_date": quality.get("last_date", manifest["requested_end"]),
                }
            )
    for field, name in CASDE_FIELDS.items():
        series.append(
            {
                "id": f"casde.CHN.{field}",
                "name": f"中国玉米 {name}",
                "unit": "比例" if field in DERIVED else "吨",
                "source_id": "casde",
                "kind": "supply_demand",
                "status": "unavailable"
                if field in {"ending_stocks", "stocks_to_use"}
                else "available",
                "entity_code": "CHN",
                "field": field,
                "definition": DERIVED.get(field, name),
                "start_date": "2024-10-01",
                "end_date": "2027-09-30",
            }
        )
    for entity, name in (("USA", "美国"), ("BRA", "巴西"), ("ARG", "阿根廷"), ("UKR", "乌克兰")):
        series.append(
            {
                "id": f"psd.{entity}.export_share",
                "name": f"{name}玉米出口占用途比",
                "unit": "比例",
                "source_id": "usda_psd",
                "kind": "supply_demand",
                "status": "not_connected",
                "entity_code": entity,
                "definition": "X/(C+X)，同MY同发布版本",
            }
        )
    series.append(
        {
            "id": "trade.CHN.imports",
            "name": "中国玉米月度进口及来源",
            "unit": "吨",
            "source_id": "customs",
            "kind": "trade",
            "status": "not_connected",
            "definition": "HS1005原粮；父子项、世界伙伴与逐国伙伴不重复加总",
        }
    )
    from app.platform.research import imported_data

    for imported in imported_data():
        sources.append(imported["source"])
        series.extend(imported["series"])
    from app.platform.catalog_store import records

    database_sources = records("data_sources")
    database_series = records("data_series")
    if database_series:
        sources = list({row["id"]: row for row in [*sources, *database_sources]}.values())
        series = list({row["id"]: row for row in [*series, *database_series]}.values())
        series = [
            row for row in series if row.get("status") not in {"unavailable", "not_connected"}
        ]
    return {"sources": sources, "series": series}


def safe_ratio(
    numerator: float | None, denominator: float | None
) -> tuple[float | None, str | None]:
    if numerator is None or denominator is None:
        return None, "缺少源字段，不能计算"
    if not math.isfinite(numerator) or not math.isfinite(denominator) or denominator == 0:
        return None, "分母为零或数值无效，不能计算"
    return numerator / denominator, None


def _cutoff(value: str, *, end_of_day: bool = True) -> datetime:
    if len(value) == 10:
        result = datetime.combine(date.fromisoformat(value), datetime.min.time(), tzinfo=UTC)
        return result + timedelta(days=1) if end_of_day else result
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return result.replace(tzinfo=UTC) if result.tzinfo is None else result.astimezone(UTC)


def query_data(request: dict) -> dict:
    for key in ("start_date", "end_date"):
        if request.get(key):
            date.fromisoformat(request[key])
    if (
        request.get("start_date")
        and request.get("end_date")
        and request["start_date"] > request["end_date"]
    ):
        raise ValueError("查询起点不能晚于终点")
    series_id = request["series_id"]
    series = next((item for item in catalog()["series"] if item["id"] == series_id), None)
    if series is None:
        raise ValueError("指标不存在，请从数据目录选择")
    result = {"series": series, "observations": [], "warnings": [], "status": series["status"]}
    if series["status"] == "not_connected":
        result["warnings"].append("该数据尚未接入，没有可查询观测值。")
        return result
    observations = []
    from app.platform.catalog_store import records

    database_observations = records("data_observations", series_id=series_id)
    if database_observations:
        observations = sorted(
            database_observations, key=lambda row: (row["date"], row.get("source_revision", ""))
        )
    elif series["kind"] == "market":
        settings = get_settings()
        manifest = _manifest()
        if not manifest:
            raise MarketCacheError("行情快照未接入")
        rows, manifest = read_market_snapshot(
            settings.market_cache_dir,
            series["ticker"],
            manifest["requested_start"],
            manifest["requested_end"],
        )
        for row in rows:
            day = str(row["tradeDate"])[:10]
            raw = row.get(series["field"])
            observations.append(
                {
                    "date": day,
                    "value": float(raw) if raw is not None else None,
                    "source_published_at": None,
                    "source_date": day,
                    "publication_time_precision": "unverified",
                    "first_seen_at": manifest.get("created_at"),
                    "release_id": manifest["files"]["market.parquet"]["sha256"],
                    "quality_flag": "measured" if raw is not None else "missing",
                    "ticker": series["ticker"],
                    "source_attribute": series["field"],
                    "period_type": "trading_day",
                    "availability_note": "原始发布时间未核实；来源回放按下一自然日可用假设。",
                }
            )
        result["warnings"].append(
            "历史日行情的原始发布时间未核实；source_published回放采用下一自然日可用假设，不宣称精确时点回测。"
        )
    elif series["source_id"] == "casde":
        doc = read_casde()
        for column in doc["columns"]:
            year = int(column["marketing_year"][:4])
            field = series["field"]
            value, reason = column.get(field), None
            if field in DERIVED:
                numerator = column.get(
                    "domestic_consumption"
                    if field == "domestic_share"
                    else "exports_my"
                    if field == "export_share"
                    else "ending_stocks"
                )
                value, reason = safe_ratio(
                    numerator, column["domestic_consumption"] + column["exports_my"]
                )
            elif field == "ending_stocks":
                reason = "CASDE玉米表未提供期末库存；结余变化不能代替库存"
            else:
                value = value * doc["conversion_multiplier"] if value is not None else None
            observations.append(
                {
                    "date": f"{year}-10-01",
                    "period_start": f"{year}-10-01",
                    "period_end": f"{year + 1}-09-30",
                    "value": value,
                    "raw_value": column.get(field),
                    "original_unit": doc["original_unit"],
                    "source_published_at": doc["source_published_at"],
                    "first_seen_at": doc["first_seen_at"],
                    "publication_time_precision": "date",
                    "release_id": doc["release_id"],
                    "source_revision": column["revision"],
                    "statistic_status": column["statistic_status"],
                    "quality_flag": "not_provided" if value is None else "official_report",
                    "period_type": "MY",
                    "marketing_year": column["marketing_year"],
                    "entity_code": "CHN",
                    "source_uri": doc["source_uri"],
                    "source_attribute": CASDE_FIELDS[field],
                    "formula": DERIVED.get(field),
                    "unavailable_reason": reason,
                    "components": {
                        key: column.get(key)
                        for key in ("domestic_consumption", "exports_my", "ending_stocks")
                    },
                    "components_unit": "万吨",
                }
            )
        result["warnings"].extend(doc["notes"])
    else:
        from app.platform.research import imported_data

        for imported in imported_data():
            observations.extend(
                row for row in imported["observations"] if row["series_id"] == series_id
            )
        result["warnings"].append(
            "人工导入数据；平台未向原发布机构核验真实性，须由业务复核原始文件。"
        )
        if any(row.get("quality_flag") == "fixture" for row in observations):
            result["warnings"].append(
                "当前为合成验收样例（fixture），不代表真实国家供需或实际贸易数据。"
            )
    start, end = request.get("start_date"), request.get("end_date")
    as_of = _cutoff(request["as_of"]) if request.get("as_of") else None
    mode = request.get("availability_mode", "source_published")
    if mode not in {"source_published", "platform_available"}:
        raise ValueError("未知的数据可得时点模式")
    for row in observations:
        if start and row["date"] < start or end and row["date"] > end:
            continue
        published = row.get("source_published_at")
        # A date-only release is conservatively unavailable until the next UTC day.
        source_time = _cutoff(published) if published else _cutoff(row["date"])
        if mode == "platform_available" and not row.get("first_seen_at"):
            raise ValueError("记录缺少可核验首次入库时间，不能按平台历史可得时点回放")
        available = _cutoff(row["first_seen_at"]) if mode == "platform_available" else source_time
        if as_of and available >= as_of:
            continue
        if as_of and _cutoff(row["date"], end_of_day=False) >= as_of:
            continue
        result["observations"].append(row)
    result["availability_mode"] = mode
    return result


def validate_trade_rows(rows: list[dict]) -> None:
    """Protect standard-file ingestion from two common double-counting errors."""
    if len(rows) > 10000:
        raise ValueError("单批贸易数据超过10000行")
    scopes: dict[tuple, set] = {}
    for row in rows:
        required = (
            "reporter",
            "partner",
            "flow",
            "hs_code",
            "hs_revision",
            "period",
            "value",
            "unit",
        )
        if any(key not in row for key in required):
            raise ValueError("贸易记录缺少必需字段")
        key = (row["reporter"], row["flow"], row["hs_revision"], row["period"], row["unit"])
        scopes.setdefault(key, set()).add((str(row["hs_code"]), str(row["partner"])))
    for members in scopes.values():
        codes = {code for code, _ in members}
        if "1005" in codes and any(code.startswith("1005") and len(code) > 4 for code in codes):
            raise ValueError("HS1005总项不能与子项同时聚合")
        for code in codes:
            partners = {partner for hs, partner in members if hs == code}
            if partners & {"0", "WLD", "World"} and len(partners) > 1:
                raise ValueError("世界伙伴总量不能与逐国伙伴同时聚合")
