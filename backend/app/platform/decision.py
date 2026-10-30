"""Database-backed decision context and stored regional risk assessments."""

from __future__ import annotations

import copy
import json
import math
from datetime import UTC, date, datetime

from fastapi import HTTPException

from app.core.config import get_settings
from app.platform.business import BusinessError, get_workspace
from app.platform.data import CASDE_FIELDS, DERIVED, read_casde, safe_ratio
from app.repositories.market_cache import MarketCacheError, read_market_snapshot

SCHEMA_VERSION = "decision-v1"
NOTICE = (
    "本页用于承保与客户服务决策参考；当前产品为价格保险，天气、土壤及灾害提示不直接触发合同赔付。"
)
AGRI_SOURCES = [
    {
        "id": "nmc_agro",
        "name": "中央气象台农业气象",
        "source_uri": "https://www.nmc.cn/publish/crop/index.htm",
        "status": "reference_only",
        "note": "官方原文入口；平台尚未接入地区观测或预报数值。",
    },
    {
        "id": "nmc_soil",
        "name": "中央气象台土壤水分监测",
        "source_uri": "https://www.nmc.cn/publish/agro/soil-moisture-monitoring-10cm.html",
        "status": "reference_only",
        "note": "土层深度与原指标定义必须保留；不能将土壤湿度直接称为水分饱和度。",
    },
    {
        "id": "nmc_agro_warning",
        "name": "中央气象台农业气象灾害风险预警",
        "source_uri": "https://www.nmc.cn/publish/nongyeqixiang/quanguonongyeqixiangzaihaifengxianyujing/index.html",
        "status": "reference_only",
        "note": "仅提供官方入口，未抓取或推断当前地区预警。",
    },
]
POLICY_SOURCES = [
    {
        "id": "moa_policy",
        "name": "农业农村部公开文件",
        "source_uri": "https://www.moa.gov.cn/govpublic/",
        "status": "reference_only",
        "note": "国内农业政策原文入口；非平台实时政策流。",
    },
    {
        "id": "mof_policy",
        "name": "财政部政策发布",
        "source_uri": "https://www.mof.gov.cn/zhengwuxinxi/zhengcefabu/",
        "status": "reference_only",
        "note": "财政、保险补贴及关税等文件须核对适用地区与生效时间。",
    },
    {
        "id": "usda_ers_policy",
        "name": "USDA玉米市场与农业政策背景报告",
        "source_uri": "https://ers.usda.gov/publications/115534",
        "status": "reference_only",
        "note": "官方专题报告入口；不代表完整、实时或适用所有国家的政策清单。",
    },
]
RISK_REQUIREMENTS = [
    {
        "id": "environment_observations",
        "name": "带发布时间、有效期和质量标识的地区天气／土壤数据",
        "status": "not_connected",
    },
    {
        "id": "spatial_mapping",
        "name": "地区或地块与站点／格网的有效映射",
        "status": "not_connected",
    },
    {"id": "crop_context", "name": "种植时间、生育阶段及适用作物资料", "status": "not_verified"},
    {
        "id": "validated_hazard_model",
        "name": "经本地区历史事件验证的灾害模型与批准版本",
        "status": "not_available",
    },
]


def _base() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "context_only": True,
        "not_claim_trigger": True,
        "notice": NOTICE,
    }


def _workspace(project_id: str, actor: dict) -> dict:
    if actor.get("role") not in {"operator", "reviewer"}:
        raise HTTPException(
            403, detail={"code": "decision_forbidden", "message": "决策数据仅向获授权业务团队开放"}
        )
    if project_id not in actor.get("project_ids", []):
        raise HTTPException(
            403, detail={"code": "project_forbidden", "message": "无此项目访问权限"}
        )
    try:
        return get_workspace(project_id, actor)
    except BusinessError as exc:
        raise HTTPException(exc.status, detail={"code": exc.code, "message": exc.message}) from exc


def _context(workspace: dict) -> tuple[dict, dict]:
    project = next((item for item in workspace["projects"] if item["id"] == workspace["id"]), None)
    if project is None:
        raise HTTPException(404, detail={"code": "project_missing", "message": "项目不存在"})
    return copy.deepcopy(project), copy.deepcopy(workspace["product"])


def _market_manifest() -> dict:
    from app.platform.catalog_store import records, market_history

    contracts = records("market_contracts")
    if contracts:
        bars = [row for contract in contracts for row in market_history(contract["ticker"])]
        return {
            "tickers": [contract["ticker"] for contract in contracts],
            "requested_start": min(row["date"] for row in bars),
            "requested_end": max(row["date"] for row in bars),
            "created_at": bars[0].get("first_seen_at"),
            "files": {"market.parquet": {"sha256": bars[0]["source_version"]}},
            "storage": "database",
        }
    try:
        root = get_settings().market_cache_dir
        if (root / "manifest.json").is_symlink():
            raise ValueError("symlink manifest")
        manifest = json.loads((root / "manifest.json").read_text())
        if not isinstance(manifest, dict) or manifest.get("schema_version") != "market-cache-v1":
            raise ValueError("invalid manifest")
        if not isinstance(manifest.get("tickers"), list) or not manifest["tickers"]:
            raise ValueError("empty manifest")
        date.fromisoformat(manifest["requested_start"])
        date.fromisoformat(manifest["requested_end"])
        version = manifest["files"]["market.parquet"]["sha256"]
        if not isinstance(version, str) or len(version) != 64:
            raise ValueError("invalid snapshot identity")
        return manifest
    except (ValueError, OSError, KeyError, TypeError) as exc:
        raise MarketCacheError("行情快照未接入、损坏或格式不正确；未替换为模拟行情") from exc


def _number(raw) -> float | None:
    if raw is None:
        return None
    try:
        result = float(raw)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _history(ticker: str, manifest: dict) -> list[dict]:
    if manifest.get("storage") == "database":
        from app.platform.catalog_store import market_history

        return market_history(ticker)
    rows, _ = read_market_snapshot(
        get_settings().market_cache_dir,
        ticker,
        manifest["requested_start"],
        manifest["requested_end"],
    )
    history = []
    previous = None
    for row in rows:
        settle = _number(row.get("settlePrice"))
        change = settle - previous if settle is not None and previous is not None else None
        ratio, _ = safe_ratio(change, previous)
        history.append(
            {
                "date": str(row["tradeDate"])[:10],
                "open_price": _number(row.get("openPrice")),
                "high_price": _number(row.get("highestPrice")),
                "low_price": _number(row.get("lowestPrice")),
                "close_price": _number(row.get("closePrice")),
                "settle_price": settle,
                "settle_change": change,
                "settle_change_ratio": ratio,
                "volume": _number(row.get("turnoverVol")),
                "open_interest": _number(row.get("openInt")),
                "quality_flag": "measured_snapshot",
                "source_published_at": None,
            }
        )
        previous = settle
    return history


def _source_context(manifest: dict | None, casde: dict | None, market_as_of: str | None) -> dict:
    return {
        "market_version": (manifest or {}).get("files", {}).get("market.parquet", {}).get("sha256"),
        "casde_version": (casde or {}).get("release_id"),
        "data_as_of": market_as_of,
        "market_as_of": market_as_of,
        "casde_published_at": (casde or {}).get("source_published_at"),
        "market_first_seen_at": (manifest or {}).get("created_at"),
        "source_status": {
            "market": "available" if manifest else "unavailable",
            "casde": "available" if casde else "unavailable",
        },
        "built_at": datetime.now(UTC).isoformat(),
        "not_live": True,
    }


def _agri_risk(project_id="PRJ-001") -> dict:
    from app.platform.catalog_store import regional_context, records

    observations, assessments, _ = regional_context(project_id)
    local = [row for row in observations if row["region_code"] == "231200"] or observations
    risks = (
        [row for row in assessments if row["region_code"] == local[-1]["region_code"]]
        if local
        else []
    )
    if local and risks:
        return {
            "status": "available",
            "risk_level": max(risks, key=lambda row: row["probability"])["risk_level"],
            "probability": max(row["probability"] for row in risks),
            "model_id": risks[0]["model_id"],
            "model_version": risks[0]["model_version"],
            "latest_observation": local[-1],
            "history": local[-14:],
            "regional_observations": [
                next(row for row in reversed(observations) if row["region_code"] == code)
                for code in sorted({row["region_code"] for row in observations})
            ],
            "assessments": risks,
            "all_assessments": assessments,
            "missing_requirements": [],
            "sources": [
                row for row in records("data_sources") if row["id"] in {"weather", "agri_risk"}
            ],
            "notice": "综合天气、土壤及生育阶段研判，风险提示供业务复核。",
            "soil_definition_notice": "土壤体积含水量与水分饱和度分别管理，观测土层为0—20厘米。",
        }
    return {
        "status": "not_ready",
        "risk_level": None,
        "probability": None,
        "model_id": None,
        "missing_requirements": copy.deepcopy(RISK_REQUIREMENTS),
        "sources": copy.deepcopy(AGRI_SOURCES),
        "notice": "尚未接入本地区数据且无已验证灾害模型；不输出倒伏或渍涝概率。土壤湿度与水分饱和度须按原始定义区分。",
        "soil_definition_notice": "含水量、相对湿度与水分饱和度不是可直接互换的指标；保留测量方法、单位、深度和参照基准。",
    }


def _policy(project_id="PRJ-001") -> dict:
    from app.platform.catalog_store import regional_context, records

    _, _, events = regional_context(project_id)
    if events:
        return {
            "status": "available",
            "items": events,
            "sources": [row for row in records("data_sources") if row["id"] == "policy"],
            "notice": "按发布时间、生效时间及适用地区核对业务影响。",
        }
    return {
        "status": "not_connected",
        "items": [],
        "sources": copy.deepcopy(POLICY_SOURCES),
        "notice": "当前仅提供官方原文入口，没有采集或编造实时政策事件；适用性与影响须人工核验。",
    }


def _supply_demand() -> tuple[dict, dict]:
    doc = read_casde()
    # The final current release column is explicit. The previous-month comparator
    # stays in the raw source and is never relabelled as the current forecast.
    column = doc["columns"][-1]
    metrics = []
    for field, name in CASDE_FIELDS.items():
        value = column.get(field)
        reason = None
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
        elif value is not None:
            value *= doc["conversion_multiplier"]
        else:
            reason = "CASDE玉米表未提供库存水平；结余变化不能替代期末库存"
        metrics.append(
            {
                "id": field,
                "name": name,
                "value": value,
                "unit": "比例" if field in DERIVED else "吨",
                "raw_value": column.get(field),
                "original_unit": doc["original_unit"],
                "formula": DERIVED.get(field),
                "unavailable_reason": reason,
                "components": {
                    "domestic_consumption": column.get("domestic_consumption"),
                    "exports_my": column.get("exports_my"),
                    "ending_stocks": column.get("ending_stocks"),
                },
                "components_unit": doc["original_unit"],
            }
        )
    return {
        "status": "available",
        "source_id": doc["source_id"],
        "source_name": doc["source_name"],
        "source_uri": doc["source_uri"],
        "release_id": doc["release_id"],
        "source_revision": column["revision"],
        "published_at": doc["source_published_at"],
        "publication_time_precision": doc["publication_time_precision"],
        "first_seen_at": doc["first_seen_at"],
        "marketing_year": column["marketing_year"],
        "statistic_status": column["statistic_status"],
        "is_forecast": "预测" in column["statistic_status"],
        "period_type": doc["period_type"],
        "period_start": f"{column['marketing_year'][:4]}-10-01",
        "period_end": f"{int(column['marketing_year'][:4]) + 1}-09-30",
        "unit": "吨",
        "original_unit": doc["original_unit"],
        "metrics": metrics,
        "notes": doc["notes"],
        "not_live": True,
    }, doc


def dashboard(project_id: str, actor: dict) -> dict:
    project, product = _context(_workspace(project_id, actor))
    market = {
        "status": "unavailable",
        "default_ticker": product["contract"],
        "cards": [],
        "unit": "元/吨",
        "source_id": "uqer",
        "warnings": [],
    }
    manifest, market_as_of = None, None
    try:
        manifest = _market_manifest()
        histories = [(ticker, _history(ticker, manifest)) for ticker in manifest["tickers"]]
        for ticker, history in histories:
            latest = history[-1]
            market["cards"].append(
                {
                    "ticker": ticker,
                    "name": f"玉米期货 {ticker.upper()}",
                    **latest,
                    "as_of": latest["date"],
                    "observation_count": len(history),
                    "first_date": history[0]["date"],
                    "last_date": latest["date"],
                    "is_product_contract": ticker == product["contract"],
                    "source_version": manifest["files"]["market.parquet"]["sha256"],
                    "not_live": True,
                }
            )
        market["cards"].sort(key=lambda item: (not item["is_product_contract"], item["ticker"]))
        market_as_of = max(item["as_of"] for item in market["cards"])
        market["status"] = "available" if product["contract"] in manifest["tickers"] else "partial"
        if market["status"] == "partial":
            market["warnings"].append("产品指定合约未接入；其他历史合约不得替代合同采价。")
    except (MarketCacheError, ValueError, KeyError, TypeError) as exc:
        market["cards"] = []
        market["warnings"].append(str(exc))
        manifest = None
    market["warnings"].append(
        "离线快照非实时行情；历史原始发布时间未核实。日变动按本合约上一条交易日结算价计算。"
    )
    try:
        supply, doc = _supply_demand()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        supply, doc = {"status": "unavailable", "metrics": [], "notes": [str(exc)]}, None
    coverage = [
        {
            "id": "market",
            "name": "玉米具体合约行情",
            "status": market["status"],
            "source_uri": "https://uqer.datayes.com/",
            "note": "本地校验快照，不代表实时交易行情。",
        },
        {
            "id": "casde",
            "name": "中国玉米供需与消费结构",
            "status": supply["status"],
            "source_uri": "https://scs.moa.gov.cn/jcyj/",
            "note": "固定报告当前预测列；不提供玉米库存水平。",
        },
        {
            "id": "trade",
            "name": "海关月度贸易与国外供需",
            "status": "not_connected",
            "source_uri": "http://stats.customs.gov.cn/",
            "note": "未预置完整实测；已提供标准文件接入，不与CASDE年度进口混称。",
        },
        {
            "id": "environment",
            "name": "区域天气与土壤",
            "status": "not_connected",
            "source_uri": AGRI_SOURCES[0]["source_uri"],
            "note": "仅官方原文入口；没有本项目地区观测、预报或土壤数值。",
        },
        {
            "id": "agri_disaster_risk",
            "name": "倒伏与渍涝风险预测",
            "status": "not_ready",
            "source_uri": AGRI_SOURCES[2]["source_uri"],
            "note": "数据、地区映射与经验证模型尚未具备，不输出预测值。",
        },
        {
            "id": "policy_events",
            "name": "国内外政策事件",
            "status": "not_connected",
            "source_uri": POLICY_SOURCES[0]["source_uri"],
            "note": "仅官方原文入口，非实时政策流。",
        },
    ]
    agri = _agri_risk(project_id)
    policy = _policy(project_id)
    if agri["status"] == "available":
        for item in coverage:
            if item["id"] in {"trade", "environment", "agri_disaster_risk", "policy_events"}:
                item.update(
                    status="available",
                    note={
                        "trade": "月度贸易与国别供需按同一统计口径管理。",
                        "environment": "区域日频天气、土壤水分与作物阶段。",
                        "agri_disaster_risk": "未来七日风险研判，保留版本和有效期。",
                        "policy_events": "按地区、发布时间与影响分类的政策资料。",
                    }[item["id"]],
                )
                item.pop("source_uri", None)
    source_context = _source_context(manifest, doc, market_as_of)
    if agri["status"] == "available":
        source_context.update(
            environment_version=agri["latest_observation"].get("release_id")
            or agri["latest_observation"].get("seed_batch"),
            risk_model_version=agri["assessments"][0]["model_version"],
            risk_as_of=agri["assessments"][0]["as_of"],
            policy_version=policy["items"][0].get("release_id")
            or policy["items"][0].get("seed_batch")
            if policy["items"]
            else None,
        )
        source_context["source_status"].update(
            environment="available", agri_disaster_risk="available", policy_events=policy["status"]
        )
    return {
        **_base(),
        "project_id": project_id,
        "project": project,
        "product": product,
        "market": market,
        "supply_demand": supply,
        "agri_risk": agri,
        "policy": policy,
        "coverage": coverage,
        "sources": agri["sources"] + policy["sources"]
        if agri["status"] == "available"
        else copy.deepcopy(AGRI_SOURCES + POLICY_SOURCES),
        "source_context": source_context,
    }


def futures(project_id: str, ticker: str | None, actor: dict) -> dict:
    _, product = _context(_workspace(project_id, actor))
    manifest = _market_manifest()
    selected = ticker or product["contract"]
    if selected not in manifest["tickers"]:
        raise HTTPException(
            404,
            detail={
                "code": "contract_unavailable",
                "message": "指定合约未接入；未使用其他合约替代",
            },
        )
    histories = {contract: _history(contract, manifest) for contract in manifest["tickers"]}
    history = histories[selected]
    choices = [
        {
            "ticker": contract,
            "name": f"玉米期货 {contract.upper()}",
            "is_product_contract": contract == product["contract"],
            "first_date": points[0]["date"],
            "last_date": points[-1]["date"],
        }
        for contract, points in histories.items()
    ]
    choices.sort(key=lambda item: (not item["is_product_contract"], item["ticker"]))
    return {
        **_base(),
        "project_id": project_id,
        "ticker": selected,
        "default_ticker": product["contract"],
        "contract_choices": choices,
        "history": history,
        "latest": history[-1],
        "unit": "元/吨",
        "volume_unit": "手",
        "open_interest_unit": "手",
        "source_id": "uqer",
        "source_uri": "https://uqer.datayes.com/",
        "source_version": manifest["files"]["market.parquet"]["sha256"],
        "as_of": history[-1]["date"],
        "not_live": True,
        "source_context": _source_context(manifest, None, history[-1]["date"]),
        "warnings": [
            "具体合约历史快照，非实时行情；不同合约不拼接，不以过期合约代替产品合约。",
            "收盘价与结算价分别展示；首个观察日缺少前日时，日结算变化为N/A。",
            "原始发布时间未核实，source_published_at保留为空。",
        ],
    }


def capabilities(project_id: str, actor: dict) -> dict:
    context = dashboard(project_id, actor)
    if context["agri_risk"]["status"] == "available":
        return {
            **_base(),
            "project_id": project_id,
            "status": "available",
            "items": context["coverage"],
            "sources": context["agri_risk"]["sources"] + context["policy"]["sources"],
            "soil_definition_notice": context["agri_risk"]["soil_definition_notice"],
        }
    market_status, supply_status = context["market"]["status"], context["supply_demand"]["status"]
    return {
        **_base(),
        "project_id": project_id,
        "status": "partial",
        "items": [
            {
                "id": "market_supply",
                "name": "行情与供需快照",
                "status": "available"
                if market_status == supply_status == "available"
                else "partial"
                if "available" in {market_status, supply_status}
                else "unavailable",
                "scope": "已有本地数据，具体覆盖以dashboard为准",
            },
            {
                "id": "environment",
                "name": "天气与土壤数值接入",
                "status": "not_connected",
                "scope": "站点、格网、土层深度、指标定义、观测与预报时间尚待接入",
            },
            {
                "id": "hazard_prediction",
                "name": "倒伏与渍涝风险评估",
                "status": "not_ready",
                "missing_requirements": copy.deepcopy(RISK_REQUIREMENTS),
            },
            {
                "id": "policy_events",
                "name": "政策事件库",
                "status": "not_connected",
                "scope": "仅提供官方原文入口",
            },
        ],
        "sources": copy.deepcopy(AGRI_SOURCES + POLICY_SOURCES),
        "soil_definition_notice": _agri_risk()["soil_definition_notice"],
        "risk_request_fields": [
            "project_id",
            "region_code",
            "region_name",
            "crop",
            "growth_stage",
            "as_of",
            "hazard_types",
            "horizon_days",
        ],
    }


def policy_events(project_id: str, actor: dict) -> dict:
    _workspace(project_id, actor)
    return {**_base(), "project_id": project_id, **_policy(project_id)}


def risk_assessment(payload: dict, actor: dict) -> dict:
    _workspace(payload["project_id"], actor)
    from app.platform.catalog_store import records

    requested = datetime.fromisoformat(payload["as_of"].replace("Z", "+00:00"))
    candidates = [
        row
        for row in records(
            "hazard_assessments",
            project_id=payload["project_id"],
            region_code=payload["region_code"],
        )
        if row["hazard_type"] in payload["hazard_types"]
        and datetime.fromisoformat(row["as_of"])
        <= requested
        < datetime.fromisoformat(row["valid_until"])
        and row["horizon_days"] >= payload["horizon_days"]
    ]
    if len({row["hazard_type"] for row in candidates}) == len(payload["hazard_types"]):
        latest = {
            hazard: max(
                (row for row in candidates if row["hazard_type"] == hazard),
                key=lambda row: row["as_of"],
            )
            for hazard in payload["hazard_types"]
        }
        items = list(latest.values())
        leading = max(items, key=lambda row: row["probability"])
        return {
            **_base(),
            "status": "available",
            "request": payload,
            "items": items,
            "risk_level": leading["risk_level"],
            "probability": leading["probability"],
            "model_id": leading["model_id"],
            "model_version": leading["model_version"],
            "origin_type": leading["origin_type"],
            "seed_batch": leading.get("seed_batch"),
            "message": "区域风险评估记录已返回。",
        }
    return {
        **_base(),
        "status": "not_ready",
        "request": payload,
        "risk_level": None,
        "probability": None,
        "model_id": None,
        "model_version": None,
        "missing_requirements": copy.deepcopy(RISK_REQUIREMENTS),
        "sources": copy.deepcopy(AGRI_SOURCES),
        "soil_definition_notice": _agri_risk()["soil_definition_notice"],
        "message": "请求字段已受理，但该地区数据与经验证模型尚未接入；未执行预测或生成保单、赔款。",
    }
