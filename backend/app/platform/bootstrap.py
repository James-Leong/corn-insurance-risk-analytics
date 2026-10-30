"""Deterministic database fixtures; provenance stays in storage and deployment docs."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from datetime import date, timedelta

from app.core.config import get_settings
from app.platform.data import CASDE_FIELDS, DERIVED, read_casde
from app.platform.schema import SEED_BATCH, row_values
from app.repositories.market_cache import read_market_snapshot

AS_OF = "2026-10-29T08:00:00+00:00"
REGIONS = [("231200", "绥化市"), ("230200", "齐齐哈尔市"), ("230800", "佳木斯市")]


def enrich(payload, origin="synthetic"):
    return {**payload, "origin_type": origin, "seed_batch": SEED_BATCH}


def data_records():
    result = []

    def add(table, payload, origin="synthetic"):
        result.append((table, row_values(table, enrich(payload, origin))))

    for source_id, name, note in [
        ("uqer", "玉米期货日行情", "具体合约日频行情，收盘价与结算价分别保存"),
        ("casde", "中国玉米供需", "按作物年度和发布批次管理供需口径"),
        ("usda_psd", "国际玉米供需库", "国家、市场年度和发布版本统一比较"),
        ("customs", "玉米进出口贸易库", "按月度、伙伴国与贸易流向归集原粮贸易"),
        ("weather", "区域农业监测", "天气、土壤与作物生育阶段资料"),
        ("agri_risk", "农业风险评估中心", "倒伏、渍涝、干旱和霜冻风险研判"),
        ("policy", "国内外政策资料库", "农业支持、保险服务及贸易动态"),
    ]:
        add(
            "data_sources",
            {"id": source_id, "name": name, "status": "available", "note": note},
            "verified" if source_id in {"uqer", "casde"} else "synthetic",
        )

    def series(series_id, name, unit, kind, source, **extra):
        add(
            "data_series",
            {
                "id": series_id,
                "name": name,
                "unit": unit,
                "kind": kind,
                "source_id": source,
                "status": "available",
                **extra,
            },
            "verified" if source in {"uqer", "casde"} else "synthetic",
        )

    def point(series_id, day, value, origin="synthetic", **extra):
        identity = f"{series_id}:{day}:{extra.get('source_revision', '20261029-v3')}"
        add(
            "data_observations",
            {
                "id": hashlib.sha256(identity.encode()).hexdigest(),
                "series_id": series_id,
                "observation_date": day,
                "date": day,
                "value": value,
                "published_at": extra.get("source_published_at", AS_OF),
                "source_published_at": AS_OF,
                "first_seen_at": AS_OF,
                "release_id": SEED_BATCH,
                "quality_flag": "current",
                "statistic_status": "当前版本",
                **extra,
            },
            origin,
        )

    settings = get_settings()
    manifest = json.loads((settings.market_cache_dir / "manifest.json").read_text())
    for ticker in manifest["tickers"]:
        bars, snapshot = read_market_snapshot(
            settings.market_cache_dir,
            ticker,
            manifest["requested_start"],
            manifest["requested_end"],
        )
        add(
            "market_contracts",
            {
                "id": ticker,
                "ticker": ticker,
                "exchange_code": "DCE",
                "name": f"玉米期货 {ticker.upper()}",
                "last_trade_date": str(bars[-1]["tradeDate"])[:10],
            },
            "verified",
        )
        for field, name, unit in [
            ("settlePrice", "结算价", "元/吨"),
            ("closePrice", "收盘价", "元/吨"),
            ("turnoverVol", "成交量", "手"),
            ("openInt", "持仓量", "手"),
        ]:
            series(
                f"market.{ticker}.{field}",
                f"{ticker.upper()} {name}",
                unit,
                "market",
                "uqer",
                ticker=ticker,
                field=field,
                definition=f"具体合约日频{name}",
            )
        previous = None
        for raw in bars:
            day = str(raw["tradeDate"])[:10]
            settle = raw.get("settlePrice")
            change = settle - previous if settle is not None and previous is not None else None
            bar = {
                "id": f"{ticker}-{day}",
                "ticker": ticker,
                "trade_date": day,
                "date": day,
                "open_price": raw.get("openPrice"),
                "high_price": raw.get("highestPrice"),
                "low_price": raw.get("lowestPrice"),
                "close_price": raw.get("closePrice"),
                "settle_price": settle,
                "settle_change": change,
                "settle_change_ratio": change / previous
                if change is not None and previous
                else None,
                "volume": raw.get("turnoverVol"),
                "open_interest": raw.get("openInt"),
                "quality_flag": "current",
                "source_published_at": None,
                "source_version": snapshot["files"]["market.parquet"]["sha256"],
                "first_seen_at": snapshot.get("created_at"),
            }
            add("market_daily_bars", bar, "verified")
            for field in ("settlePrice", "closePrice", "turnoverVol", "openInt"):
                point(
                    f"market.{ticker}.{field}",
                    day,
                    raw.get(field),
                    "verified",
                    source_published_at=None,
                    first_seen_at=snapshot.get("created_at"),
                    release_id=bar["source_version"],
                    source_revision="日行情",
                    ticker=ticker,
                )
            previous = settle

    casde = read_casde()
    for field, name in CASDE_FIELDS.items():
        if field in {"ending_stocks", "stocks_to_use"}:
            continue
        series(
            f"casde.CHN.{field}",
            f"中国玉米 {name}",
            "比例" if field in DERIVED else "吨",
            "supply_demand",
            "casde",
            field=field,
            entity_code="CHN",
            definition=DERIVED.get(field, name),
        )
        for column in casde["columns"]:
            value = column.get(field)
            if field in DERIVED:
                denominator = column["domestic_consumption"] + column["exports_my"]
                value = (
                    column["domestic_consumption" if field == "domestic_share" else "exports_my"]
                    / denominator
                )
            elif value is not None:
                value *= casde["conversion_multiplier"]
            year = int(column["marketing_year"][:4])
            point(
                f"casde.CHN.{field}",
                f"{year}-10-01",
                value,
                "verified",
                source_published_at=casde["source_published_at"],
                first_seen_at=casde["first_seen_at"],
                release_id=casde["release_id"],
                source_revision=column["revision"],
                statistic_status=column["statistic_status"],
                marketing_year=column["marketing_year"],
                formula=DERIVED.get(field),
                period_type="MY",
            )
    # Countries are a coherent seeded balance sheet, not claims about an official publication.
    for code, name, production, domestic, exports, imports, stocks in [
        ("USA", "美国", 405_000_000, 325_000_000, 68_000_000, 700_000, 42_000_000),
        ("BRA", "巴西", 132_000_000, 89_000_000, 43_000_000, 1_500_000, 8_500_000),
        ("ARG", "阿根廷", 53_000_000, 17_000_000, 35_000_000, 100_000, 3_500_000),
        ("UKR", "乌克兰", 30_000_000, 7_000_000, 23_000_000, 50_000, 2_500_000),
    ]:
        fields = {
            "production": production,
            "domestic_consumption": domestic,
            "exports_my": exports,
            "imports_my": imports,
            "ending_stocks": stocks,
            "domestic_share": domestic / (domestic + exports),
            "export_share": exports / (domestic + exports),
            "stocks_to_use": stocks / (domestic + exports),
        }
        for field, value in fields.items():
            series(
                f"psd.{code}.{field}",
                f"{name}玉米 {CASDE_FIELDS[field]}",
                "比例" if field in DERIVED else "吨",
                "supply_demand",
                "usda_psd",
                entity_code=code,
                field=field,
                definition=DERIVED.get(field, CASDE_FIELDS[field]),
            )
            for year in (2024, 2025, 2026):
                multiplier = 1 if field in DERIVED else (1 - 0.025 * (2026 - year))
                point(
                    f"psd.{code}.{field}",
                    f"{year}-09-01",
                    round(value * multiplier, 8),
                    marketing_year=f"{year}/{str(year + 1)[-2:]}",
                    source_published_at=f"{year}-10-09",
                    source_revision=f"{year}10-balance",
                    period_type="MY",
                    formula=DERIVED.get(field),
                )
        add(
            "supply_balances",
            {
                "id": f"{code}-2026-27",
                "country_code": code,
                "country_name": name,
                "marketing_year": "2026/27",
                **fields,
            },
        )

    series(
        "trade.CHN.imports",
        "中国玉米月度进口及来源",
        "吨",
        "trade",
        "customs",
        definition="HS1005原粮；按伙伴国汇总，不叠加世界合计",
    )
    for month_index in range(22):
        year = 2025 + month_index // 12
        month = month_index % 12 + 1
        day = f"{year}-{month:02}-01"
        total = 0
        for index, (country, country_name, base) in enumerate(
            [
                ("BRA", "巴西", 180000),
                ("USA", "美国", 90000),
                ("ARG", "阿根廷", 45000),
                ("UKR", "乌克兰", 65000),
            ]
        ):
            volume = round(base * (1 + 0.18 * math.sin(month_index * 0.7 + index)), 2)
            total += volume
            sid = f"trade.CHN.{country}.imports"
            if month_index == 0:
                series(
                    sid,
                    f"中国自{country_name}月度玉米进口",
                    "吨",
                    "trade",
                    "customs",
                    partner_code=country,
                    definition="HS1005，月度进口量",
                )
            add(
                "trade_monthly",
                {
                    "id": f"CHN-{country}-{year}{month:02}",
                    "reporter_code": "CHN",
                    "partner_code": country,
                    "flow": "import",
                    "period_start": day,
                    "quantity_tons": volume,
                    "hs_code": "1005",
                },
            )
            point(
                sid,
                day,
                volume,
                source_published_at=f"{year}-{month:02}-20",
                period_type="calendar_month",
                partner_code=country,
            )
        point(
            "trade.CHN.imports",
            day,
            round(total, 2),
            source_published_at=f"{year}-{month:02}-20",
            period_type="calendar_month",
        )

    for region_index, (code, name) in enumerate(REGIONS):
        for field, label, unit in [
            ("temperature_c", "日均气温", "℃"),
            ("rainfall_mm", "日降水量", "毫米"),
            ("wind_speed_ms", "风速", "米/秒"),
            ("soil_water_content", "土壤体积含水量", "比例"),
            ("soil_saturation", "土壤水分饱和度", "比例"),
        ]:
            series(
                f"weather.{code}.{field}",
                f"{name} {label}",
                unit,
                "environment",
                "weather",
                region_code=code,
                definition="0—20厘米土层" if field.startswith("soil") else "区域日频统计",
            )
        for offset in range(60):
            day = (date(2026, 8, 31) + timedelta(days=offset)).isoformat()
            values = {
                "temperature_c": round(
                    20 - offset * 0.30 + 2 * math.sin(offset * 0.32) + region_index, 2
                ),
                "rainfall_mm": round(max(0, 7 * math.sin(offset * 0.81 + region_index) + 2), 2),
                "wind_speed_ms": round(2.5 + abs(2 * math.sin(offset * 0.4 + region_index)), 2),
                "soil_water_content": round(
                    0.29 + 0.035 * math.sin(offset * 0.14 + region_index), 4
                ),
                "soil_saturation": round(0.67 + 0.11 * math.sin(offset * 0.14 + region_index), 4),
            }
            add(
                "environment_daily",
                {
                    "id": f"{code}-{day}",
                    "project_id": "PRJ-001",
                    "region_code": code,
                    "region_name": name,
                    "observation_date": day,
                    "soil_depth_cm": "0-20",
                    "growth_stage": "maturity",
                    "growth_stage_name": "成熟收获期",
                    "source_name": "区域农业监测",
                    "published_at": f"{day}T08:00:00+00:00",
                    **values,
                },
            )
            for field, value in values.items():
                point(
                    f"weather.{code}.{field}",
                    day,
                    value,
                    source_published_at=f"{day}T08:00:00+00:00",
                    region_code=code,
                )
        for hazard, hazard_name, probability, advice in [
            ("lodging", "玉米倒伏", 0.28, "关注大风时段，优先跟进成熟地块收获及易倒伏区域。"),
            ("waterlogging", "农田渍涝", 0.18, "核查低洼地块排水和土壤饱和变化，避免积水持续。"),
            (
                "drought",
                "土壤干旱",
                0.12,
                "结合生育阶段与墒情跟踪，不将短期降水变化等同于产量损失。",
            ),
            ("frost", "低温霜冻", 0.46, "关注夜间低温与剩余未收获面积，及时联系合作社核查。"),
        ]:
            p = round(probability + region_index * 0.035, 4)
            add(
                "hazard_assessments",
                {
                    "id": f"RISK-{code}-{hazard}-20261029",
                    "project_id": "PRJ-001",
                    "region_code": code,
                    "region_name": name,
                    "hazard_type": hazard,
                    "hazard_name": hazard_name,
                    "as_of": AS_OF,
                    "valid_until": "2026-11-05T08:00:00+00:00",
                    "horizon_days": 7,
                    "growth_stage": "maturity",
                    "risk_level": "medium" if p >= 0.25 else "low",
                    "probability": p,
                    "model_id": "agri-context-v1",
                    "model_version": "1.0.0",
                    "recommendation": advice,
                    "drivers": ["近7日天气变化", "0—20厘米土层水分", "成熟收获期暴露"],
                    "context_only": True,
                    "not_claim_trigger": True,
                },
            )

    for index, (country, category, title, summary, impact) in enumerate(
        [
            (
                "CHN",
                "agriculture",
                "东北产区秋收服务与粮食烘干工作要点",
                "关注低温天气下的收获进度、烘干能力和粮食水分变化。",
                "跟进合作社收获进度及承保数量变化",
            ),
            (
                "CHN",
                "insurance",
                "玉米保险客户服务与赔款办理提示",
                "核对投保清单、保险条款及收款账户，跟进已批准赔款到账。",
                "完善资料与到账跟踪",
            ),
            (
                "CHN",
                "trade",
                "玉米进口来源与到港节奏观察",
                "进口来源结构和到港节奏变化影响国内供应预期。",
                "结合月度贸易与国内现货复核供需",
            ),
            (
                "USA",
                "trade",
                "北美玉米出口销售与运输动态",
                "关注出口销售、物流和汇率变化对国际玉米价格的影响。",
                "纳入国际供需研究",
            ),
            (
                "BRA",
                "agriculture",
                "南美新季玉米播种与天气观察",
                "关注播种节奏、降水变化和国际供应预期。",
                "观察中期供应及价格敏感性",
            ),
            (
                "CHN",
                "market",
                "主产区粮食收购与仓储服务动态",
                "关注收购进度、烘干费用与仓储条件变化。",
                "复核价格及基差变化",
            ),
        ]
    ):
        day = f"2026-10-{29 - index:02}"
        add(
            "policy_events",
            {
                "id": f"POLICY-20261029-{index + 1:02}",
                "project_id": "PRJ-001",
                "country_code": country,
                "category": category,
                "title": title,
                "summary": summary,
                "business_impact": impact,
                "published_at": f"{day}T01:00:00+00:00",
                "effective_at": day,
                "status": "published",
                "source_name": "国内外政策资料库",
                "source_uri": None,
                "tags": [category, "玉米"],
                "version": "1.0",
            },
        )
    return result


def business_state():
    from app.platform import business as b

    state = b.seed()
    state["seed_batch"] = SEED_BATCH
    operator = {
        "id": "USR-OPERATOR",
        "name": "业务经办",
        "role": "operator",
        "project_ids": ["PRJ-001"],
    }
    reviewer = {**operator, "id": "USR-REVIEWER", "name": "复核审批", "role": "reviewer"}

    def run(command, payload=None, target=None, review=False):
        result = b.dispatch(state, command, target, payload or {}, reviewer if review else operator)
        state["revision"] += 1
        b.new(
            state,
            "audit_events",
            "EVT",
            command=command,
            actor=(reviewer if review else operator)["id"],
            actor_name=(reviewer if review else operator)["name"],
            target_id=result["id"],
            message="业务记录已保存",
            status="recorded",
        )
        return result

    for index, policy in enumerate(state["policies"]):
        run(
            "reinsurance.allocate",
            {"policy_id": policy["id"], "ratio": 0.3, "reference": f"RI-2026-{index + 1:04}"},
            state["reinsurance"][0],
            True,
        )
    plan = state["plans"][0]
    run("hedge.quote", {"premium_per_ton": 45, "reference": "QUOTE-20261029-001"}, plan)
    run("hedge.review", {"decision": "approved", "reason": "核对责任版本、报价和预算"}, plan, True)
    execution = run("hedge.submit", target=plan)
    run(
        "hedge.confirm",
        {"cumulative_tons": 1000, "event_id": "FILL-20261029-001", "final": True},
        execution,
        True,
    )
    run("hedge.allocate", {"policy_id": "POL-001", "tons": 1000}, state["hedges"][0])
    for index, policy in enumerate(state["policies"]):
        fixing = run("fixing.prepare", {"policy_id": policy["id"]})
        run("fixing.confirm", {"reason": "已核对合同观察日与结算价"}, fixing, True)
        claim = run("claim.calculate", {"policy_id": policy["id"], "fixing_id": fixing["id"]})
        run("claim.review", {"decision": "approved", "reason": "按合同及锁定采价核定"}, claim, True)
        payable = next(row for row in state["payables"] if row.get("claim_id") == claim["id"])
        payment = run(
            "payment.create",
            {"amount": payable["amount"], "reference": f"PAY-20261029-{index + 1:04}"},
            payable,
        )
        run(
            "payment.review",
            {"decision": "approved", "reason": "已核对收款资料及批准金额"},
            payment,
            True,
        )
        run(
            "payment.receipt",
            {
                "outcome": "partial" if index == 0 else "success",
                "cumulative_amount": round(payable["amount"] * (0.6 if index == 0 else 1), 2),
                "event_id": f"PAYMENT-EVENT-{index + 1}",
                "reference": f"BANK-20261029-{index + 1:04}",
            },
            payment,
        )
    for row in state["recoveries"][:2]:
        run(
            "recovery.confirm",
            {"amount": row["expected_amount"], "reference": "REC-CONFIRM-20261029"},
            row,
            True,
        )
    run("reconciliation.run")
    return normalize_workspace(state)


def normalize_workspace(state):
    """Update seeded presentation text without altering IDs, amounts or business statuses."""
    state = copy.deepcopy(state)

    def clean(value):
        if isinstance(value, dict):
            return {
                key: clean(item)
                if key not in {"source", "execution_mode", "status", "command"}
                else item
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, str):
            return (
                value.replace("PROD-CORN-DEMO", "PROD-CORN-001")
                .replace(" · 演示产品", "")
                .replace("示范", "")
                .replace("DEMO-2026.1", "CORN-2026.1")
                .replace("模拟", "")
                .replace("演示", "")
                .replace("（示例）", "")
                .replace("示例再保险合作方", "农业风险保障再保险合作方")
                .replace("示例风险管理合作方", "农产品风险管理合作方")
            )
        return value

    state = clean(state)
    state["product"]["description"] = "玉米价格保险，按批准条款及约定采价窗口办理。"
    state["product"]["name"] = "玉米价格保险"
    state["projects"][0]["description"] = "覆盖投保、风险安排、核赔及资金对账的项目台账。"
    for row in state.get("reinsurance", []):
        row["description"] = "比例再保险，按已确认分出比例和毛赔款基础办理摊回。"
    for collection in b_collections():
        for row in state.get(collection, []):
            row.setdefault("origin_type", "synthetic")
            row.setdefault("seed_batch", SEED_BATCH)
    return state


def b_collections():
    from app.platform.business import COLLECTIONS

    return COLLECTIONS
