"""Transactional policy operations for the insurance workspace.

Every command runs under a locked MySQL transaction. The project document is a
versioned aggregate; durable request receipts and external-event identifiers
prevent duplicate trades, liabilities and cash allocations after a retry.
"""

from __future__ import annotations

import copy
import hashlib
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.platform.auth import now
from app.platform.store import ensure_schema, transaction


class BusinessError(Exception):
    def __init__(self, message: str, code: str = "invalid_operation", status: int = 422):
        self.message, self.code, self.status = message, code, status
        super().__init__(message)


COLLECTIONS = (
    "projects",
    "applications",
    "policies",
    "batches",
    "issuance_requests",
    "reinsurance",
    "reinsurance_allocations",
    "plans",
    "executions",
    "hedges",
    "allocations",
    "fixings",
    "claims",
    "payables",
    "payments",
    "recoveries",
    "reconciliations",
    "audit_events",
    "premium_adjustments",
    "decision_records",
)


def number(value, *, positive=False, maximum=1_000_000_000) -> Decimal:
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result < 0 or result > maximum or (positive and not result):
            raise ValueError
        return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        raise BusinessError("请输入范围内的有效非负数值", "invalid_number") from None


def money(value) -> float:
    return float(number(value))


def total(rows, field) -> Decimal:
    return sum((number(row.get(field, 0)) for row in rows), Decimal(0))


def text_field(payload, name, *, required=False, default="") -> str:
    raw = payload.get(name, default)
    if raw is None:
        raw = default
    if not isinstance(raw, str):
        raise BusinessError(f"字段 {name} 须为文本", "invalid_field")
    value = raw.strip()
    if (required and not value) or len(value) > 2000:
        raise BusinessError(f"字段 {name} 缺失或长度不符合要求", "invalid_field")
    return value


def item(state, collection, item_id):
    result = next((row for row in state[collection] if row["id"] == item_id), None)
    if not result:
        raise BusinessError("未找到当前项目中的业务记录", "not_found", 404)
    return result


def new(state, collection, prefix, **fields):
    entity = {
        "id": f"{prefix}-{uuid.uuid4().hex[:10].upper()}",
        "version": 1,
        "status": "draft",
        "created_at": now(),
        "updated_at": now(),
        "project_id": state["id"],
        "execution_mode": "simulation",
        **fields,
    }
    state[collection].append(entity)
    return entity


def touch(entity, **fields):
    entity.update(fields)
    entity["version"] += 1
    entity["updated_at"] = now()
    return entity


def check_version(entity, expected):
    if expected is None:
        raise BusinessError("请携带当前对象版本后重试", "version_required", 409)
    if entity["version"] != expected:
        raise BusinessError("记录已被其他操作更新，请刷新后重试", "version_conflict", 409)


def permission(user, roles):
    if user["role"] not in roles:
        raise BusinessError("当前账号无权执行此操作", "forbidden", 403)


def independent(user, entity):
    if entity.get("created_by") == user["id"]:
        raise BusinessError("经办与复核必须由不同人员完成", "separation_of_duties", 403)


def allowed_project(user, project_id):
    if project_id not in user.get("project_ids", []):
        raise BusinessError("无权访问该项目", "forbidden", 403)


def seed() -> dict:
    state = {
        "id": "PRJ-001",
        "revision": 1,
        "execution_mode": "simulation",
        "as_of": now(),
        **{k: [] for k in COLLECTIONS},
    }
    dates = ["2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23"]
    state["product"] = {
        "id": "PROD-CORN-DEMO",
        "name": "玉米价格保险 · 产品",
        "version": "DEMO-2026.1",
        "terms_version": "DEMO-2026.1",
        "status": "simulation_only",
        "official_ready": False,
        "description": "用于演示既定产品接入；正式条款、再保与交易主体尚待业务确认。",
        "contract": "c2701",
        "price_field": "settlePrice",
        "price_unit": "元/吨",
        "guarantee_price": 2400,
        "premium_per_ton": 60,
        "deductible_per_ton": 0,
        "payout_cap_per_ton": 600,
        "fixing_method": "arithmetic_mean",
        "fixing_dates": dates,
        "currency": "CNY",
        "execution_mode": "simulation",
        "formula": "min(max(保障价－观察日结算价均值－免赔额,0),每吨赔付上限)×承保吨数",
        "requires_full_premium": True,
        "quantity_unit": "吨",
    }
    project = new(
        state,
        "projects",
        "PRJ",
        name="黑龙江玉米价格保障示范项目",
        region="黑龙江省·绥化市",
        owner="保单业务团队",
        status="active",
        period_start="2026-07-01",
        period_end="2026-12-31",
        product_id=state["product"]["id"],
        product_version="DEMO-2026.1",
        organization="玉米种植合作社",
        hedge_budget=5_000_000,
        description="全部业务与外部通道均为",
    )
    project["id"] = "PRJ-001"
    for i, name, tons, status in (
        (1, "向阳种植合作社", 1200, "issued"),
        (2, "丰禾农业合作社", 800, "issued"),
        (3, "兴田家庭农场", 600, "submitted"),
        (4, "兴农种植户", 300, "draft"),
    ):
        app = new(
            state,
            "applications",
            "APP",
            applicant_name=name,
            insured_name=name,
            customer_id="USR-CUSTOMER" if i in (1, 4) else f"CUSTOMER-{i}",
            tons=tons,
            area_mu=tons * 2,
            region="黑龙江省·绥化市",
            phone="138****2026",
            period_start="2026-07-01",
            period_end="2026-10-23",
            terms_confirmed=True,
            materials=["种植证明（示例）", "投保清单（示例）"],
            premium_due=tons * 60,
            premium_received=tons * 60 if i < 3 else 0,
            status=status,
            created_by="USR-OPERATOR",
            product_version="DEMO-2026.1",
            review_reason="核保通过" if i < 3 else "",
            reviewed_by="USR-REVIEWER" if i < 3 else None,
            premium_receipts=[],
        )
        app["id"] = f"APP-{i:03}"
        if i < 3:
            policy = new(
                state,
                "policies",
                "POL",
                **{
                    k: app[k]
                    for k in (
                        "applicant_name",
                        "insured_name",
                        "customer_id",
                        "tons",
                        "area_mu",
                        "region",
                        "period_start",
                        "period_end",
                    )
                },
                application_id=app["id"],
                policy_no=f"SIM-CORN-2026-{i:04}",
                status="active",
                contract="c2701",
                guarantee_price=2400,
                premium=tons * 60,
                product_snapshot=copy.deepcopy(state["product"]),
                fixing_dates=dates,
                price_field="settlePrice",
                responsibility_version=1,
                history=[],
                pending_change=None,
                created_by="USR-OPERATOR",
                source="simulation_core",
            )
            policy["id"] = f"POL-{i:03}"
            app["policy_id"] = policy["id"]
    ri = new(
        state,
        "reinsurance",
        "RI",
        name="玉米价格责任比例再保（示例）",
        contract_no="SIM-RI-2026-001",
        counterparty="示例再保险合作方",
        structure="quota_share",
        ratio=0.3,
        calculation_basis="gross_claim",
        accepted=True,
        status="accepted",
        contract="c2701",
        product_version="DEMO-2026.1",
        period_start="2026-01-01",
        period_end="2026-12-31",
        limit=3_000_000,
        reference="SIM-RI-CONFIRMATION",
        description="仅示范按毛赔款分出的比例结构，非真实再保合同",
    )
    ri["id"] = "RI-001"
    plan = new(
        state,
        "plans",
        "HPL",
        name="首批玉米责任保护方案",
        policy_ids=["POL-001"],
        policy_versions={"POL-001": 1},
        tons=1000,
        tool="otc_put",
        strike_price=2400,
        premium_per_ton=45,
        budget=45000,
        contract="c2701",
        fixing_dates=dates,
        counterparty="示例风险管理合作方",
        direction="buy",
        status="draft",
        created_by="USR-OPERATOR",
        report_id=None,
        basis="gross_responsibility",
        quote_expires_at=None,
        quote_reference=None,
        approved_by=None,
        approval_version=None,
        reason="覆盖首批价格下跌责任的场外看跌方案",
    )
    plan["id"] = "HPL-001"
    new(
        state,
        "audit_events",
        "EVT",
        command="workspace.seed",
        actor="system",
        actor_name="系统",
        message="已建立明确标记的项目与业务样例",
        status="recorded",
    )
    return state


def load(connection, project_id):
    ensure_schema(connection)
    row = connection.execute(
        "SELECT document FROM platform_workspaces WHERE id = ?", (project_id,)
    ).fetchone()
    if row:
        state = json.loads(row["document"])
        for collection in COLLECTIONS:
            state.setdefault(collection, [])
        return state
    if project_id != "PRJ-001":
        raise BusinessError("项目不存在", "not_found", 404)
    state = seed()
    save(connection, state)
    return state


def save(connection, state):
    connection.execute(
        "INSERT INTO platform_workspaces VALUES (?, ?, ?) ON DUPLICATE KEY UPDATE "
        "revision = VALUES(revision), document = VALUES(document)",
        (state["id"], state["revision"], json.dumps(state, ensure_ascii=False, allow_nan=False)),
    )
    from app.platform.catalog_store import sync_workspace

    sync_workspace(connection, state)


def own_application(user, entity):
    if user["role"] == "customer" and entity["customer_id"] != user["id"]:
        raise BusinessError("只能访问本人的投保记录", "forbidden", 403)


def make_tasks(state):
    tasks = []
    for collection, statuses, module, label in (
        (
            "applications",
            {"submitted", "needs_materials", "approved", "issuing"},
            "policies",
            "投保申请办理",
        ),
        ("plans", {"quoted", "invalidated"}, "risk", "对冲方案待复核"),
        ("executions", {"processing", "unknown", "partially_confirmed"}, "risk", "交易确认与查单"),
        ("fixings", {"missing", "pending_review"}, "settlement", "采价补齐与复核"),
        ("claims", {"pending_review", "payable", "partially_paid"}, "settlement", "赔案办理"),
        (
            "payments",
            {"pending_review", "processing", "unknown", "partially_paid"},
            "settlement",
            "付款审批与回执",
        ),
        (
            "recoveries",
            {"expected", "confirmed", "partially_received"},
            "settlement",
            "风险转移回收",
        ),
        ("reconciliations", {"open", "pending_review"}, "settlement", "对账差异处理"),
        ("allocations", {"needs_review"}, "risk", "批改后的责任匹配复核"),
        ("reinsurance_allocations", {"needs_review"}, "risk", "批改后的再保适用复核"),
        ("premium_adjustments", {"pending_confirmation"}, "policies", "批改新增保费待确认"),
    ):
        for row in state[collection]:
            if row["status"] in statuses:
                tasks.append(
                    {
                        "id": f"TASK-{row['id']}",
                        "target_id": row["id"],
                        "source_type": collection,
                        "module": module,
                        "title": label,
                        "description": row.get("insured_name", row.get("name", row["id"])),
                        "status": row["status"],
                        "created_at": row["updated_at"],
                        "assignee_role": "reviewer"
                        if row["status"] in {"submitted", "quoted", "pending_review"}
                        else "operator",
                    }
                )
    return tasks


def snapshot(state, user):
    result = copy.deepcopy(state)
    result["storage_backend"] = "mysql"
    result["as_of"] = now()
    for payable in result["payables"]:
        payable["available_amount"] = money(
            max(
                Decimal(0),
                number(payable["amount"])
                - number(payable["paid_amount"])
                - number(payable["reserved_amount"]),
            )
        )
    if user["role"] == "customer":
        result["applications"] = [
            row for row in result["applications"] if row["customer_id"] == user["id"]
        ]
        result["policies"] = [row for row in result["policies"] if row["customer_id"] == user["id"]]
        policy_ids = {row["id"] for row in result["policies"]}
        result["claims"] = [row for row in result["claims"] if row["policy_id"] in policy_ids]
        for application in result["applications"]:
            application.pop("decision_id", None)
            application.pop("decision_snapshot", None)
        for claim in result["claims"]:
            payables = [
                row
                for row in state["payables"]
                if row.get("claim_id") == claim["id"] and row.get("kind", "claim") == "claim"
            ]
            payments = [
                row
                for row in state["payments"]
                if row.get("claim_id") == claim["id"] and row.get("kind", "claim") == "claim"
            ]
            approved = total(payables, "amount")
            paid = total(payables, "paid_amount")
            in_transit = total(payables, "reserved_amount")
            unpaid = max(Decimal(0), approved - paid)
            payment_status = (
                "zero_closed"
                if claim["status"] == "zero_closed"
                else (
                    "not_payable"
                    if not approved
                    else "paid"
                    if not unpaid
                    else "unknown"
                    if any(row["status"] == "unknown" for row in payments)
                    else "partially_paid"
                    if paid
                    else "processing"
                    if in_transit
                    else "payable"
                )
            )
            claim.update(
                paid_amount=money(paid),
                unpaid_amount=money(unpaid),
                in_transit_amount=money(in_transit),
                payment_status=payment_status,
                payment_progress={
                    "approved_amount": money(approved),
                    "paid_amount": money(paid),
                    "unpaid_amount": money(unpaid),
                    "in_transit_amount": money(in_transit),
                    "status": payment_status,
                },
            )
        for key in COLLECTIONS:
            if key not in {"projects", "applications", "policies", "claims"}:
                result[key] = []
        result["product"].pop("premium_per_ton", None)
    active = [p for p in result["policies"] if p["status"] == "active"]
    matched = [a for a in result["allocations"] if a["status"] == "confirmed"]
    reserve = total(result["executions"], "reserved_tons")
    responsibility = total(active, "tons")
    ri_tons = sum(
        (
            number(a["tons"]) * number(a["ratio"])
            for a in result["reinsurance_allocations"]
            if a["status"] == "confirmed"
        ),
        Decimal(0),
    )
    result["tasks"] = make_tasks(result)
    result["summary"] = {
        "applications": len(result["applications"]),
        "active_policies": len(active),
        "insured_tons": float(responsibility),
        "reinsured_tons": money(ri_tons),
        "retained_tons": money(responsibility - ri_tons),
        "hedged_tons": money(total(matched, "tons")),
        "confirmed_hedge_tons": money(total(result["hedges"], "tons")),
        "reserved_tons": money(reserve),
        "uncovered_tons": money(max(Decimal(0), responsibility - total(matched, "tons"))),
        "premium_due": money(total(result["applications"], "premium_due")),
        "premium_received": money(total(result["applications"], "premium_received")),
        "approved_payable": money(total(result["payables"], "amount")),
        "paid_amount": money(total(result["payables"], "paid_amount")),
        "reserved_payments": money(total(result["payables"], "reserved_amount")),
        "outstanding_payable": money(
            sum(
                (number(p["amount"]) - number(p["paid_amount"]) for p in result["payables"]),
                Decimal(0),
            )
        ),
        "recovery_expected": money(total(result["recoveries"], "expected_amount")),
        "recovery_confirmed": money(total(result["recoveries"], "confirmed_amount")),
        "recovery_received": money(total(result["recoveries"], "received_amount")),
        "open_tasks": len(result["tasks"]),
        "pending_applications": sum(a["status"] == "submitted" for a in result["applications"]),
        "pending_claims": sum(a["status"] == "pending_review" for a in result["claims"]),
    }
    result["portfolio"] = []
    for policy in active:
        allocations = [a for a in matched if a["policy_id"] == policy["id"]]
        reinsurance = [
            a
            for a in result["reinsurance_allocations"]
            if a["policy_id"] == policy["id"] and a["status"] == "confirmed"
        ]
        result["portfolio"].append(
            {
                "policy_id": policy["id"],
                "policy_no": policy["policy_no"],
                "insured_name": policy["insured_name"],
                "tons": policy["tons"],
                "contract": policy["contract"],
                "responsibility_version": policy["responsibility_version"],
                "reinsurance_ratio": float(total(reinsurance, "ratio")),
                "hedged_tons": money(total(allocations, "tons")),
                "uncovered_tons": money(
                    max(Decimal(0), number(policy["tons"]) - total(allocations, "tons"))
                ),
                "fixing_dates": policy["fixing_dates"],
                "status": policy["status"],
            }
        )
    result["permissions"] = {
        "role": user["role"],
        "can_review": user["role"] == "reviewer",
        "can_operate": user["role"] == "operator",
    }
    return result


def get_workspace(project_id, user):
    allowed_project(user, project_id)
    with transaction() as connection:
        return snapshot(load(connection, project_id), user)


def application_values(payload, product, user, current=None):
    if user["role"] == "customer" and payload.get("decision_id"):
        raise BusinessError("客户不能引用内部承保判断记录", "forbidden", 403)
    values = {**(current or {}), **payload}
    tons = number(values.get("tons", 0), positive=True, maximum=1_000_000)
    start = text_field(values, "period_start", required=True)
    end = text_field(values, "period_end", required=True)
    try:
        if date.fromisoformat(start) > date.fromisoformat(end):
            raise ValueError
    except ValueError:
        raise BusinessError("保险期间应为有效日期且开始日不晚于结束日", "invalid_period") from None
    if not start <= min(product["fixing_dates"]) <= max(product["fixing_dates"]) <= end:
        raise BusinessError(
            "本期产品保险期间必须覆盖2026年10月19日至23日采价窗口", "fixing_period_mismatch"
        )
    materials = values.get("materials", [])
    if (
        not isinstance(materials, list)
        or len(materials) > 30
        or any(not isinstance(v, str) or len(v) > 200 for v in materials)
    ):
        raise BusinessError("材料应为不超过30个文件名称的列表", "invalid_materials")
    customer_id = (
        user["id"]
        if user["role"] == "customer"
        else text_field(values, "customer_id", default="USR-CUSTOMER")
    )
    return {
        "applicant_name": text_field(values, "applicant_name", required=True),
        "insured_name": text_field(values, "insured_name", required=True),
        "customer_id": customer_id,
        "tons": money(tons),
        "area_mu": money(values.get("area_mu", 0)),
        "region": text_field(values, "region", required=True),
        "phone": text_field(values, "phone", required=True),
        "period_start": start,
        "period_end": end,
        "terms_confirmed": values.get("terms_confirmed") is True,
        "materials": materials,
        "premium_due": money(tons * number(product["premium_per_ton"])),
        "product_version": product["version"],
    }


def create_application(state, values, user, **extra):
    return new(
        state,
        "applications",
        "APP",
        **values,
        status="draft",
        premium_received=0,
        premium_receipts=[],
        created_by=user["id"],
        **extra,
    )


def validate_submit(app):
    if not app["terms_confirmed"]:
        raise BusinessError("请先确认产品条款", "terms_required")
    if not app["materials"]:
        raise BusinessError("请补充投保材料", "materials_required")


def issue_policy(state, application):
    if (
        not application["period_start"]
        <= min(state["product"]["fixing_dates"])
        <= max(state["product"]["fixing_dates"])
        <= application["period_end"]
    ):
        raise BusinessError("保险期间与合同采价窗口不一致，不能出单", "fixing_period_mismatch")
    existing = next(
        (p for p in state["policies"] if p["application_id"] == application["id"]), None
    )
    if existing:
        return existing
    policy = new(
        state,
        "policies",
        "POL",
        **{
            k: application[k]
            for k in (
                "applicant_name",
                "insured_name",
                "customer_id",
                "tons",
                "area_mu",
                "region",
                "period_start",
                "period_end",
            )
        },
        application_id=application["id"],
        policy_no=f"SIM-CORN-{uuid.uuid4().hex[:12].upper()}",
        status="active",
        contract=state["product"]["contract"],
        guarantee_price=state["product"]["guarantee_price"],
        premium=application["premium_due"],
        product_snapshot=copy.deepcopy(state["product"]),
        fixing_dates=state["product"]["fixing_dates"],
        price_field=state["product"]["price_field"],
        responsibility_version=1,
        history=[],
        pending_change=None,
        created_by=application["created_by"],
        source="simulation_core",
    )
    touch(application, status="issued", policy_id=policy["id"])
    return policy


def application_command(state, command, target, payload, user):
    if command == "application.create":
        permission(user, {"operator", "customer"})
        values = application_values(payload, state["product"], user)
        decision_id = text_field(payload, "decision_id")
        if decision_id:
            decision = item(state, "decision_records", decision_id)
            if (
                decision["product_id"] != state["product"]["id"]
                or decision["product_version"] != state["product"]["version"]
            ):
                raise BusinessError("人工判断所引用产品已变更，请重新记录", "stale_decision", 409)
            values.update(decision_id=decision["id"], decision_snapshot=copy.deepcopy(decision))
        return create_application(state, values, user)
    if command == "application.import_preview":
        permission(user, {"operator", "customer"})
        rows = payload.get("rows")
        if not isinstance(rows, list) or not 1 <= len(rows) <= 500:
            raise BusinessError("每批请导入1至500行逐户资料", "invalid_batch")
        previews, seen = [], set()
        for index, values in enumerate(rows, 1):
            try:
                if not isinstance(values, dict):
                    raise BusinessError("每行必须是申请字段对象")
                cleaned = application_values(values, state["product"], user)
                key = (cleaned["insured_name"], cleaned["region"], cleaned["period_start"])
                if key in seen:
                    raise BusinessError("本批次同一被保险人、区域和期间重复", "duplicate_row")
                seen.add(key)
                previews.append({"row": index, "valid": True, "values": cleaned, "errors": []})
            except BusinessError as exc:
                previews.append(
                    {"row": index, "valid": False, "values": values, "errors": [exc.message]}
                )
        fingerprint = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
        old = next(
            (
                b
                for b in state["batches"]
                if b["fingerprint"] == fingerprint and b["created_by"] == user["id"]
            ),
            None,
        )
        return old or new(
            state,
            "batches",
            "BAT",
            rows=previews,
            fingerprint=fingerprint,
            status="valid" if all(r["valid"] for r in previews) else "invalid",
            created_by=user["id"],
            row_count=len(rows),
            error_count=sum(not row["valid"] for row in previews),
        )
    if command == "application.import_confirm":
        permission(user, {"operator", "customer"})
        batch = target
        if user["role"] == "customer" and batch["created_by"] != user["id"]:
            raise BusinessError("不能确认其他客户的导入", "forbidden", 403)
        if batch["status"] == "confirmed":
            return batch
        if batch["status"] != "valid":
            raise BusinessError("导入存在错误行，请修改后重新预览", "invalid_batch")
        apps = [
            create_application(state, row["values"], user, batch_id=batch["id"])
            for row in batch["rows"]
        ]
        return touch(batch, status="confirmed", application_ids=[a["id"] for a in apps])
    app = target
    own_application(user, app)
    if command == "application.update":
        permission(user, {"operator", "customer"})
        if app["status"] in {"issued", "issuing"}:
            raise BusinessError("已请求出单的申请不能直接修改，请办理保单变更")
        values = application_values(payload, state["product"], user, app)
        if number(values["premium_due"]) < number(app["premium_received"]):
            raise BusinessError("新保费低于已收金额，请先办理经复核的保费差额处理")
        return touch(
            app, **values, status="draft", reviewed_by=None, review_reason="修改后需重新提交"
        )
    if command == "application.submit":
        permission(user, {"operator", "customer"})
        if app["status"] not in {"draft", "needs_materials"}:
            raise BusinessError("只有草稿或待补件申请可提交")
        if payload.get("terms_confirmed") is True:
            app["terms_confirmed"] = True
        if "materials" in payload:
            app["materials"] = application_values(payload, state["product"], user, app)["materials"]
        validate_submit(app)
        return touch(app, status="submitted", submitted_at=now())
    if command == "application.review":
        permission(user, {"reviewer"})
        independent(user, app)
        if app["status"] != "submitted":
            raise BusinessError("申请当前不在待核保状态")
        decision = payload.get("decision")
        if decision not in {"approved", "needs_materials", "rejected"}:
            raise BusinessError("请选择通过、补件或拒绝")
        return touch(
            app,
            status=decision,
            reviewed_by=user["id"],
            review_reason=text_field(payload, "reason", required=True),
            approved_application_version=app["version"] + 1,
        )
    if command == "application.premium":
        permission(user, {"operator"})
        if app["status"] != "approved":
            raise BusinessError("核保通过后才能登记保费确认")
        amount = number(payload.get("amount"), positive=True)
        reference = text_field(payload, "reference", required=True)
        old = next((r for r in app["premium_receipts"] if r["reference"] == reference), None)
        if old:
            if number(old["amount"]) != amount:
                raise BusinessError("同一保费回执编号金额不一致", "event_conflict", 409)
            return app
        if amount + number(app["premium_received"]) > number(app["premium_due"]):
            raise BusinessError("保费实收不能超过应收")
        app["premium_receipts"].append(
            {
                "reference": reference,
                "amount": money(amount),
                "source": "simulation_receipt",
                "recorded_by": user["id"],
                "created_at": now(),
            }
        )
        return touch(app, premium_received=money(number(app["premium_received"]) + amount))
    if command == "policy.issue":
        permission(user, {"operator"})
        if app["status"] == "issued":
            return item(state, "policies", app["policy_id"])
        if app["status"] == "issuing":
            raise BusinessError("原出单请求尚未确认，请先查单", "pending_external", 409)
        if app["status"] != "approved" or number(app["premium_received"]) < number(
            app["premium_due"]
        ):
            raise BusinessError("出单前须核保通过且保费足额确认", "issuance_precondition")
        request = new(
            state,
            "issuance_requests",
            "ISS",
            application_id=app["id"],
            status="processing",
            external_no=f"SIM-CORE-{uuid.uuid4().hex[:10]}",
            created_by=user["id"],
        )
        touch(app, status="issuing", issuance_request_id=request["id"])
        return request
    if command == "policy.query":
        permission(user, {"operator"})
        if app["status"] == "issued":
            return item(state, "policies", app["policy_id"])
        if app["status"] != "issuing":
            raise BusinessError("尚无可查询的出单请求")
        request = item(state, "issuance_requests", app["issuance_request_id"])
        outcome = payload.get("outcome", "confirmed")
        if outcome == "unknown":
            touch(request, status="unknown")
            return touch(app, issuance_status="unknown")
        if outcome == "failed":
            touch(request, status="failed")
            return touch(app, status="approved", issuance_status="failed")
        if outcome != "confirmed":
            raise BusinessError("不支持的核心回执")
        policy = issue_policy(state, app)
        touch(request, status="confirmed", policy_id=policy["id"])
        return policy
    raise BusinessError("不支持的申请命令")


def policy_change(state, policy, payload, user):
    action = payload.get("action", "request")
    if action in {"approve", "reject"}:
        permission(user, {"reviewer"})
        change = policy.get("pending_change")
        if not change or change["status"] != "pending_review":
            raise BusinessError("当前没有待复核的批改")
        independent(user, change)
        reason = text_field(payload, "reason", required=True)
        if action == "reject":
            policy["history"].append({**change, "status": "rejected", "review_reason": reason})
            return touch(policy, pending_change=None)
        old = {
            k: copy.deepcopy(v) for k, v in policy.items() if k not in {"history", "pending_change"}
        }
        policy["history"].append(
            {
                "before": old,
                "change": copy.deepcopy(change),
                "reviewed_by": user["id"],
                "review_reason": reason,
                "at": now(),
            }
        )
        policy["responsibility_version"] += 1
        for collection in ("allocations", "reinsurance_allocations"):
            for allocation in state[collection]:
                if allocation["policy_id"] == policy["id"] and allocation["status"] == "confirmed":
                    touch(allocation, status="needs_review", reason="保单责任批改后重新确认")
        for plan in state["plans"]:
            if policy["id"] in plan["policy_ids"] and plan["status"] in {
                "draft",
                "quoted",
                "approved",
            }:
                touch(plan, status="invalidated", approved_by=None, approval_version=None)
        new_premium = number(change["tons"]) * number(policy["product_snapshot"]["premium_per_ton"])
        difference = new_premium - number(policy["premium"])
        touch(
            policy,
            tons=change["tons"],
            premium=money(new_premium),
            status="terminated" if change["terminate"] else "active",
            pending_change=None,
        )
        if difference < 0:
            upsert_payable(
                state,
                "premium_refund",
                change["id"],
                -difference,
                policy["insured_name"],
                policy_id=policy["id"],
                basis_version=policy["responsibility_version"],
                reference=f"SIM-APPROVED-CHANGE-{change['id']}",
            )
        elif difference > 0:
            new(
                state,
                "premium_adjustments",
                "PAD",
                policy_id=policy["id"],
                change_id=change["id"],
                amount=money(difference),
                received_amount=0,
                status="pending_confirmation",
                receipts=[],
                created_by=change["created_by"],
                approved_by=user["id"],
            )
        return policy
    permission(user, {"operator"})
    if policy["status"] != "active":
        raise BusinessError("仅有效保单可申请批改")
    if policy.get("pending_change"):
        raise BusinessError("存在待复核批改，请先完成原请求")
    if any(c["policy_id"] == policy["id"] for c in state["claims"]):
        raise BusinessError("已进入理赔的保单须先完成核定差额处理，本期不直接批改")
    if any(
        policy["id"] in e["policy_ids"] and number(e["reserved_tons"]) > 0
        for e in state["executions"]
    ):
        raise BusinessError("存在待确认交易预占，请先查单完成交易后再批改")
    terminate = payload.get("terminate") is True
    tons = 0 if terminate else money(number(payload.get("tons", policy["tons"]), positive=True))
    change = {
        "id": f"CHG-{uuid.uuid4().hex[:8]}",
        "tons": tons,
        "terminate": terminate,
        "reason": text_field(payload, "reason", required=True),
        "status": "pending_review",
        "created_by": user["id"],
        "created_at": now(),
        "before_tons": policy["tons"],
    }
    return touch(policy, pending_change=change)


def reinsurance_allocate(state, arrangement, payload, user):
    permission(user, {"reviewer"})
    if payload.get("action") == "close_for_new":
        allocation = item(state, "reinsurance_allocations", payload.get("allocation_id"))
        if (
            allocation["arrangement_id"] != arrangement["id"]
            or allocation["status"] != "needs_review"
        ):
            raise BusinessError("仅当前再保安排的待复核分配可停止新增适用")
        allocation.setdefault("history", []).append(
            {
                "status": allocation["status"],
                "tons": allocation["tons"],
                "policy_version": allocation["policy_version"],
                "at": now(),
            }
        )
        touch(
            allocation,
            status="historical",
            reviewed_by=user["id"],
            reason=text_field(payload, "reason", required=True),
        )
        touch(arrangement)
        return allocation
    policy = item(state, "policies", payload.get("policy_id"))
    if policy["status"] != "active" or policy["pending_change"]:
        raise BusinessError("仅责任稳定的有效保单可分保")
    if not arrangement["accepted"] or arrangement["structure"] != "quota_share":
        raise BusinessError("只支持已接受的演示比例再保安排")
    if (
        arrangement["contract"] != policy["contract"]
        or arrangement["product_version"] != policy["product_snapshot"]["version"]
    ):
        raise BusinessError("再保安排与保单责任不适用", "incompatible_responsibility")
    if not arrangement["period_start"] <= policy["period_start"] <= arrangement["period_end"]:
        raise BusinessError("保单归属日期不在再保合同范围内")
    ratio = number(payload.get("ratio", arrangement["ratio"]), positive=True, maximum=1)
    if ratio != number(arrangement["ratio"]):
        raise BusinessError("分出比例须与已接受合同一致")
    existing = next(
        (
            a
            for a in state["reinsurance_allocations"]
            if a["policy_id"] == policy["id"] and a["arrangement_id"] == arrangement["id"]
        ),
        None,
    )
    other = total(
        [
            a
            for a in state["reinsurance_allocations"]
            if a["policy_id"] == policy["id"]
            and a["status"] == "confirmed"
            and (not existing or a["id"] != existing["id"])
        ],
        "ratio",
    )
    if other + ratio > 1:
        raise BusinessError("同一保单分出比例合计不能超过100%", "over_allocation")
    if existing:
        if (
            existing["status"] == "confirmed"
            and existing["policy_version"] == policy["responsibility_version"]
        ):
            return existing
        touch(
            existing,
            status="confirmed",
            policy_version=policy["responsibility_version"],
            tons=policy["tons"],
            premium=money(number(policy["premium"]) * ratio),
            reference=text_field(payload, "reference", required=True),
        )
        upsert_payable(
            state,
            "reinsurance_premium",
            existing["id"],
            existing["premium"],
            arrangement["counterparty"],
            policy_id=policy["id"],
            basis_version=existing["version"],
            reference=existing["reference"],
        )
        touch(arrangement)
        return existing
    allocation = new(
        state,
        "reinsurance_allocations",
        "RIA",
        arrangement_id=arrangement["id"],
        policy_id=policy["id"],
        policy_version=policy["responsibility_version"],
        tons=policy["tons"],
        ratio=float(ratio),
        premium=money(number(policy["premium"]) * ratio),
        status="confirmed",
        created_by=user["id"],
        reference=text_field(payload, "reference", required=True),
    )
    touch(arrangement)
    upsert_payable(
        state,
        "reinsurance_premium",
        allocation["id"],
        allocation["premium"],
        arrangement["counterparty"],
        policy_id=policy["id"],
        basis_version=allocation["version"],
        reference=allocation["reference"],
    )
    return allocation


def upsert_payable(
    state,
    kind,
    source_id,
    amount,
    counterparty,
    *,
    policy_id=None,
    basis_version=1,
    reference="",
    claim_id=None,
):
    """One payable per approved business source; later changes adjust the balance."""
    amount = number(amount)
    payable = next(
        (
            p
            for p in state["payables"]
            if p.get("kind", "claim") == kind and p.get("source_id", p.get("claim_id")) == source_id
        ),
        None,
    )
    if payable:
        committed = number(payable["paid_amount"]) + number(payable["reserved_amount"])
        if amount < committed:
            raise BusinessError(
                "变更后的应付低于已付及在途资金，须先处理差额", "cash_conflict", 409
            )
        if amount != number(payable["amount"]):
            payable["history"].append(
                {
                    "before": payable["amount"],
                    "after": money(amount),
                    "at": now(),
                    "reference": reference,
                }
            )
        touch(
            payable,
            amount=money(amount),
            balance=money(amount - number(payable["paid_amount"])),
            basis_version=basis_version,
            status="paid"
            if amount == number(payable["paid_amount"])
            else "partially_paid"
            if number(payable["paid_amount"])
            else "payable",
        )
        return payable
    if not amount:
        return None
    return new(
        state,
        "payables",
        "PAY",
        kind=kind,
        source_id=source_id,
        claim_id=claim_id,
        policy_id=policy_id,
        counterparty=counterparty,
        amount=money(amount),
        paid_amount=0,
        reserved_amount=0,
        balance=money(amount),
        status="payable",
        currency="CNY",
        basis_version=basis_version,
        claim_version=basis_version if claim_id else None,
        reference=reference,
        history=[],
    )


def plan_values(state, payload, current=None):
    values = {**(current or {}), **payload}
    policy_ids = values.get("policy_ids", [])
    if (
        not isinstance(policy_ids, list)
        or not policy_ids
        or len(policy_ids) != len(set(policy_ids))
    ):
        raise BusinessError("请关联至少一份不重复的有效保单")
    policies = [item(state, "policies", identity) for identity in policy_ids]
    if any(p["status"] != "active" or p.get("pending_change") for p in policies):
        raise BusinessError("方案只能引用无待办批改的有效保单")
    if len({(p["contract"], tuple(p["fixing_dates"])) for p in policies}) != 1:
        raise BusinessError("不同合约或采价窗口应分别编制方案", "incompatible_responsibility")
    tons = number(values.get("tons", 0), positive=True, maximum=1_000_000)
    if tons > total(policies, "tons"):
        raise BusinessError("方案量不能超过所关联保单的毛责任量", "over_allocation")
    if values.get("tool", "otc_put") != "otc_put":
        raise BusinessError(
            "当前产品使用场外看跌期权执行路线，请选择已配置交易工具", "route_unavailable"
        )
    premium = number(values.get("premium_per_ton", 45))
    strike = number(values.get("strike_price", state["product"]["guarantee_price"]), positive=True)
    return {
        "name": text_field(values, "name", default="玉米责任对冲方案"),
        "policy_ids": policy_ids,
        "policy_versions": {p["id"]: p["responsibility_version"] for p in policies},
        "tons": money(tons),
        "tool": "otc_put",
        "strike_price": money(strike),
        "premium_per_ton": money(premium),
        "budget": money(tons * premium),
        "contract": policies[0]["contract"],
        "fixing_dates": policies[0]["fixing_dates"],
        "counterparty": text_field(values, "counterparty", default="示例风险管理合作方"),
        "direction": "buy",
        "report_id": values.get("report_id") or None,
        "reason": text_field(values, "reason", default="责任保护"),
        "basis": "gross_responsibility",
    }


def check_report(report_id, user):
    if not report_id:
        return
    try:
        from app.platform.research import get_report

        get_report(report_id, user)
    except ImportError:
        raise BusinessError(
            "研究报告服务尚未就绪，不能引用不存在的报告", "report_unavailable"
        ) from None


def execution_consumption(state, policy_id):
    consumed = Decimal(0)
    for execution in state["executions"]:
        remaining = number(execution["confirmed_tons"]) + number(execution["reserved_tons"])
        for reservation in execution["responsibility_reservations"]:
            portion = min(number(reservation["tons"]), remaining)
            if reservation["policy_id"] == policy_id:
                consumed += portion
            remaining -= portion
    return consumed


def make_reservations(state, plan):
    remaining = number(plan["tons"])
    reservations = []
    for identity in plan["policy_ids"]:
        policy = item(state, "policies", identity)
        available = max(Decimal(0), number(policy["tons"]) - execution_consumption(state, identity))
        portion = min(remaining, available)
        if portion:
            reservations.append(
                {
                    "policy_id": identity,
                    "policy_version": policy["responsibility_version"],
                    "tons": money(portion),
                }
            )
            remaining -= portion
    if remaining:
        raise BusinessError(
            "相关责任已被其他交易或在途请求占用，不能重复下单", "insufficient_responsibility", 409
        )
    return reservations


def check_plan_fresh(state, plan):
    for identity, version in plan["policy_versions"].items():
        policy = item(state, "policies", identity)
        if (
            policy["responsibility_version"] != version
            or policy["status"] != "active"
            or policy["pending_change"]
        ):
            raise BusinessError("方案责任版本已失效，请重新编制并审批", "stale_responsibility", 409)
    try:
        expires = datetime.fromisoformat(str(plan.get("quote_expires_at")))
        if expires.tzinfo is None or expires <= datetime.now(UTC):
            raise ValueError
    except ValueError:
        raise BusinessError(
            "报价已过期或尚无有效报价，请重新报价并复核", "quote_expired", 409
        ) from None


def apply_execution_receipt(state, execution, payload, user):
    event_id = text_field(payload, "event_id", required=True)
    cumulative = number(payload.get("cumulative_tons", execution["confirmed_tons"]))
    outcome = payload.get("outcome", "confirmed")
    final = payload.get("final") is True or outcome == "rejected"
    event = {
        "event_id": event_id,
        "cumulative_tons": money(cumulative),
        "outcome": outcome,
        "final": final,
    }
    old = next((e for e in execution["events"] if e["event_id"] == event_id), None)
    if old:
        if any(old[k] != event[k] for k in event):
            raise BusinessError("同一交易回执编号内容冲突", "event_conflict", 409)
        return execution
    if execution["status"] in {"confirmed", "rejected"}:
        if cumulative == number(execution["confirmed_tons"]):
            execution["events"].append({**event, "at": now(), "actor": user["id"], "ignored": True})
            return touch(execution)
        raise BusinessError("终态交易不能直接改变确认量，需进入更正流程", "terminal_state", 409)
    if cumulative < number(execution["confirmed_tons"]) or cumulative > number(
        execution["requested_tons"]
    ):
        raise BusinessError("累计确认量不能减少或超过请求量", "invalid_receipt")
    execution["events"].append(
        {**event, "at": now(), "actor": user["id"], "source": "simulation_counterparty"}
    )
    if outcome == "unknown":
        if cumulative != number(execution["confirmed_tons"]):
            raise BusinessError("未知状态不能增加实际确认量", "invalid_receipt")
        return touch(execution, status="unknown")
    if outcome not in {"confirmed", "rejected"}:
        raise BusinessError("不支持的交易回执状态")
    requested = number(execution["requested_tons"])
    remaining = Decimal(0) if final else requested - cumulative
    status = (
        "confirmed"
        if cumulative == requested or final and cumulative > 0
        else ("rejected" if final else "partially_confirmed" if cumulative else "processing")
    )
    touch(
        execution,
        status=status,
        confirmed_tons=money(cumulative),
        reserved_tons=money(remaining),
        reserved_budget=money(remaining * number(execution["premium_per_ton"])),
    )
    plan = item(state, "plans", execution["plan_id"])
    touch(plan, status="executed" if status in {"confirmed", "rejected"} else "executing")
    hedge = next((h for h in state["hedges"] if h["execution_id"] == execution["id"]), None)
    if cumulative:
        if hedge:
            touch(
                hedge,
                tons=money(cumulative),
                cost=money(cumulative * number(plan["premium_per_ton"])),
            )
        else:
            hedge = new(
                state,
                "hedges",
                "HDG",
                execution_id=execution["id"],
                plan_id=plan["id"],
                status="confirmed",
                tons=money(cumulative),
                tool=plan["tool"],
                contract=plan["contract"],
                fixing_dates=plan["fixing_dates"],
                strike_price=plan["strike_price"],
                premium_per_ton=plan["premium_per_ton"],
                cost=money(cumulative * number(plan["premium_per_ton"])),
                counterparty=plan["counterparty"],
                policy_ids=plan["policy_ids"],
                contract_no=f"SIM-OTC-{uuid.uuid4().hex[:10].upper()}",
                source="simulation_confirmation",
            )
        execution["hedge_id"] = hedge["id"]
        upsert_payable(
            state,
            "hedge_premium",
            hedge["id"],
            hedge["cost"],
            hedge["counterparty"],
            basis_version=hedge["version"],
            reference=execution["external_no"],
        )
    return execution


def hedge_command(state, command, target, payload, user):
    if command == "hedge.plan":
        permission(user, {"operator"})
        values = plan_values(state, payload)
        check_report(values["report_id"], user)
        return new(
            state,
            "plans",
            "HPL",
            **values,
            status="draft",
            created_by=user["id"],
            quote_expires_at=None,
            quote_reference=None,
            approved_by=None,
            approval_version=None,
        )
    if command == "hedge.allocate":
        hedge = target
        action = payload.get("action", "allocate")
        if action in {"release", "reconfirm"}:
            permission(user, {"reviewer"})
            allocation = item(state, "allocations", payload.get("allocation_id"))
            if allocation["hedge_id"] != hedge["id"] or allocation["status"] != "needs_review":
                raise BusinessError("仅当前合同待复核的分配可处理")
            reason = text_field(payload, "reason", required=True)
            allocation.setdefault("history", []).append(
                {
                    "tons": allocation["tons"],
                    "policy_version": allocation["policy_version"],
                    "status": allocation["status"],
                    "at": now(),
                    "reason": reason,
                }
            )
            if action == "release":
                touch(allocation, status="released", reviewed_by=user["id"], review_reason=reason)
            else:
                policy = item(state, "policies", allocation["policy_id"])
                if policy["status"] != "active" or policy.get("pending_change"):
                    raise BusinessError("保单责任尚不可重新匹配")
                tons = number(payload.get("tons", allocation["tons"]), positive=True)
                others = [
                    a
                    for a in state["allocations"]
                    if a["id"] != allocation["id"] and a["status"] in {"confirmed", "needs_review"}
                ]
                if total(
                    [a for a in others if a["hedge_id"] == hedge["id"]], "tons"
                ) + tons > number(hedge["tons"]) or (
                    total([a for a in others if a["policy_id"] == policy["id"]], "tons") + tons
                    > number(policy["tons"])
                ):
                    raise BusinessError("重新分配超过双方剩余量", "over_allocation", 409)
                touch(
                    allocation,
                    status="confirmed",
                    tons=money(tons),
                    policy_version=policy["responsibility_version"],
                    reviewed_by=user["id"],
                    review_reason=reason,
                )
            touch(hedge)
            return allocation
        permission(user, {"operator"})
        policy = item(state, "policies", payload.get("policy_id"))
        if policy["status"] != "active" or policy.get("pending_change"):
            raise BusinessError("只能匹配无待办变更的有效保单")
        if (
            hedge["contract"] != policy["contract"]
            or hedge["fixing_dates"] != policy["fixing_dates"]
        ):
            raise BusinessError("交易与保单标的或观察窗口不兼容", "incompatible_responsibility")
        if policy["id"] not in hedge["policy_ids"]:
            raise BusinessError("本次成交仅可用于原批准方案责任，跨责任需重新审批")
        tons = number(payload.get("tons"), positive=True)
        matching = [
            a
            for a in state["allocations"]
            if a["hedge_id"] == hedge["id"] and a["status"] in {"confirmed", "needs_review"}
        ]
        on_policy = [
            a
            for a in state["allocations"]
            if a["policy_id"] == policy["id"] and a["status"] in {"confirmed", "needs_review"}
        ]
        if total(matching, "tons") + tons > number(hedge["tons"]) or total(
            on_policy, "tons"
        ) + tons > number(policy["tons"]):
            raise BusinessError("分配超过交易或保单剩余量", "over_allocation", 409)
        allocation = new(
            state,
            "allocations",
            "ALC",
            hedge_id=hedge["id"],
            policy_id=policy["id"],
            tons=money(tons),
            status="confirmed",
            policy_version=policy["responsibility_version"],
            hedge_version=hedge["version"],
            created_by=user["id"],
            mismatch="名义匹配不代表风险完全消除",
        )
        touch(hedge)
        return allocation
    if command in {"hedge.confirm", "hedge.query"}:
        permission(user, {"reviewer"} if command == "hedge.confirm" else {"operator"})
        if command == "hedge.query":
            payload = {"outcome": "unknown", "event_id": f"QUERY-{uuid.uuid4().hex}", **payload}
        return apply_execution_receipt(state, target, payload, user)
    plan = target
    if command == "hedge.update":
        permission(user, {"operator"})
        if plan["status"] in {"executing", "executed"}:
            raise BusinessError("执行中的计划不可修改，请先查单处理")
        values = plan_values(state, payload, plan)
        check_report(values["report_id"], user)
        return touch(
            plan,
            **values,
            status="draft",
            quote_expires_at=None,
            quote_reference=None,
            approved_by=None,
            approval_version=None,
        )
    if command == "hedge.quote":
        permission(user, {"operator"})
        if plan["status"] in {"executing", "executed"}:
            raise BusinessError("执行中的方案不可换报价")
        expires_at = (
            payload.get("quote_expires_at")
            or (datetime.now(UTC) + timedelta(minutes=30)).isoformat()
        )
        try:
            expiry = datetime.fromisoformat(expires_at)
            if expiry.tzinfo is None:
                raise ValueError
        except (ValueError, TypeError):
            raise BusinessError("报价有效期必须为含时区的ISO日期时间") from None
        premium = number(payload.get("premium_per_ton", plan["premium_per_ton"]))
        return touch(
            plan,
            status="quoted",
            premium_per_ton=money(premium),
            budget=money(premium * number(plan["tons"])),
            quote_expires_at=expires_at,
            quote_reference=text_field(
                payload, "reference", default=f"SIM-QUOTE-{uuid.uuid4().hex[:8]}"
            ),
            quote_source="simulation_counterparty",
            approved_by=None,
            approval_version=None,
        )
    if command == "hedge.review":
        permission(user, {"reviewer"})
        independent(user, plan)
        if plan["status"] != "quoted":
            raise BusinessError("请先取得报价后提交复核")
        decision = payload.get("decision", "approved")
        if decision not in {"approved", "rejected"}:
            raise BusinessError("无效的审批决定")
        if decision == "approved":
            check_plan_fresh(state, plan)
        return touch(
            plan,
            status=decision,
            approved_by=user["id"] if decision == "approved" else None,
            approval_version=plan["version"] + 1 if decision == "approved" else None,
            review_reason=text_field(payload, "reason", required=True),
        )
    if command == "hedge.submit":
        permission(user, {"operator"})
        if plan["status"] != "approved" or plan["approval_version"] != plan["version"]:
            raise BusinessError("仅当前版本已批准的方案可下单", "approval_required", 409)
        check_plan_fresh(state, plan)
        reservations = make_reservations(state, plan)
        committed_budget = sum(
            (
                number(e["reserved_budget"])
                + number(e["confirmed_tons"]) * number(e["premium_per_ton"])
                for e in state["executions"]
            ),
            Decimal(0),
        )
        if number(plan["budget"]) + committed_budget > number(state["projects"][0]["hedge_budget"]):
            raise BusinessError("超出本期交易授权预算", "budget_limit", 409)
        execution = new(
            state,
            "executions",
            "EXE",
            plan_id=plan["id"],
            policy_ids=plan["policy_ids"],
            requested_tons=plan["tons"],
            confirmed_tons=0,
            reserved_tons=plan["tons"],
            reserved_budget=plan["budget"],
            premium_per_ton=plan["premium_per_ton"],
            responsibility_reservations=reservations,
            status="processing",
            events=[],
            created_by=user["id"],
            external_no=f"SIM-OTC-{uuid.uuid4().hex[:10]}",
            approval_version=plan["approval_version"],
            source="simulation_channel",
        )
        touch(plan, status="executing", execution_id=execution["id"])
        return execution
    raise BusinessError("不支持的风险方案命令")


def prepare_fixing(state, payload, user):
    permission(user, {"operator"})
    policy = item(state, "policies", payload.get("policy_id"))
    if policy["status"] != "active" or policy.get("pending_change"):
        raise BusinessError("有效且责任稳定的保单才能采价")
    expected = policy["fixing_dates"]
    source_snapshot = None
    if "prices" in payload:
        prices = payload["prices"]
        if not isinstance(prices, list) or not prices:
            raise BusinessError("人工价格须提供逐日值")
        reference = text_field(payload, "reason", required=True)
        observations = []
        for row in prices:
            if not isinstance(row, dict) or row.get("date") not in expected:
                raise BusinessError("人工价格包含非合同观察日")
            observations.append(
                {
                    "date": row["date"],
                    "value": money(number(row.get("value"), positive=True)),
                    "source": "manual_simulation",
                    "reference": reference,
                    "published_at": None,
                    "source_published_at": None,
                    "publication_time_precision": "unavailable",
                    "recorded_at": now(),
                }
            )
        source, source_version, source_error = "manual_simulation", reference, None
    else:
        from app.core.config import get_settings
        from app.repositories.market_cache import MarketCacheError, read_market_snapshot
        from app.platform.catalog_store import market_snapshot

        settings = get_settings()
        observations, source, source_version, source_error = [], "unavailable", None, None
        try:
            rows, manifest = market_snapshot(policy["contract"]) or read_market_snapshot(
                settings.market_cache_dir,
                policy["contract"],
                settings.data_start_date,
                settings.data_end_date,
            )
            source_kind = (
                "database_market"
                if manifest.get("storage") == "database"
                else "uqer_verified_snapshot"
            )
            observations = [
                {
                    "date": str(row["tradeDate"])[:10],
                    "value": money(number(row[policy["price_field"]], positive=True)),
                    "source": source_kind,
                    "published_at": None,
                    "source_published_at": None,
                    "publication_time_precision": "unavailable",
                    "publication_note": "原始行情发布时间未核实；交易日不代表发布时间",
                    "snapshot_created_at": manifest.get("created_at"),
                }
                for row in rows
                if str(row["tradeDate"])[:10] in expected
            ]
            source, source_version = (
                source_kind,
                manifest["files"]["market.parquet"]["sha256"],
            )
            source_snapshot = {
                "file": "market_daily_bars"
                if manifest.get("storage") == "database"
                else "market.parquet",
                "sha256": source_version,
                "created_at": manifest.get("created_at"),
                "requested_start": manifest["requested_start"],
                "requested_end": manifest["requested_end"],
            }
        except (MarketCacheError, KeyError, ValueError) as exc:
            source_error = str(exc)
    if len({row["date"] for row in observations}) != len(observations):
        raise BusinessError("同一观察日不能重复计入采价")
    observations.sort(key=lambda row: row["date"])
    missing = [day for day in expected if day not in {row["date"] for row in observations}]
    old = [f for f in state["fixings"] if f["policy_id"] == policy["id"]]
    if any(c["policy_id"] == policy["id"] and c["status"] != "rejected" for c in state["claims"]):
        raise BusinessError("已核定责任不得静默重采，请按核定更正流程处理")
    fixing = new(
        state,
        "fixings",
        "FIX",
        policy_id=policy["id"],
        contract=policy["contract"],
        price_field=policy["price_field"],
        expected_dates=expected,
        observations=observations,
        expected_count=len(expected),
        actual_count=len(observations),
        missing_dates=missing,
        status="missing" if missing else "pending_review",
        source=source,
        source_version=source_version,
        source_snapshot=source_snapshot,
        source_error=source_error,
        created_by=user["id"],
        previous_fixing_id=old[-1]["id"] if old else None,
        average_price=None,
        unit="元/吨",
        rule_version=policy["product_snapshot"]["version"],
    )
    return fixing


def claim_rule(policy, fixing, price=None):
    product = policy["product_snapshot"]
    settlement = number(fixing["average_price"] if price is None else price)
    loss = max(
        Decimal(0),
        number(policy["guarantee_price"]) - settlement - number(product["deductible_per_ton"]),
    )
    payout = min(loss, number(product["payout_cap_per_ton"]))
    return {
        "guarantee_price": policy["guarantee_price"],
        "settlement_price": money(settlement),
        "deductible_per_ton": product["deductible_per_ton"],
        "payout_cap_per_ton": product["payout_cap_per_ton"],
        "payout_per_ton": money(payout),
        "tons": policy["tons"],
        "rule_amount": money(payout * number(policy["tons"])),
        "currency": "CNY",
        "formula": product["formula"],
        "rule_version": product["version"],
    }


def sync_claim_cash(state, claim):
    payable = next((p for p in state["payables"] if p["claim_id"] == claim["id"]), None)
    if payable:
        paid = number(payable["paid_amount"])
        balance = number(payable["amount"]) - paid
        touch(
            payable,
            balance=money(balance),
            status="paid" if not balance else ("partially_paid" if paid else "payable"),
        )
        if claim["status"] != "pending_review":
            touch(
                claim,
                status="zero_closed"
                if not number(payable["amount"])
                else "paid"
                if not balance
                else "partially_paid"
                if paid
                else "payable",
            )


def update_recoveries(state, claim, policy, fixing):
    candidates = []
    for allocation in state["reinsurance_allocations"]:
        if allocation["policy_id"] != policy["id"] or allocation["status"] != "confirmed":
            continue
        arrangement = item(state, "reinsurance", allocation["arrangement_id"])
        if arrangement["calculation_basis"] != "gross_claim":
            raise BusinessError("再保综合口径尚未确认，不能自动生成摊回")
        candidates.append(
            (
                "reinsurance",
                allocation["id"],
                arrangement["counterparty"],
                number(claim["approved_amount"]) * number(allocation["ratio"]),
                "毛核定赔款×已接受分出比例",
            )
        )
    for allocation in state["allocations"]:
        if allocation["policy_id"] != policy["id"] or allocation["status"] != "confirmed":
            continue
        hedge = item(state, "hedges", allocation["hedge_id"])
        payoff = max(Decimal(0), number(hedge["strike_price"]) - number(fixing["average_price"]))
        candidates.append(
            (
                "hedge",
                allocation["id"],
                hedge["counterparty"],
                payoff * number(allocation["tons"]),
                "场外看跌期权约定观察均价回收（）",
            )
        )
    for kind, source_id, counterparty, amount, basis in candidates:
        amount = number(amount)
        recovery = next(
            (
                r
                for r in state["recoveries"]
                if r["claim_id"] == claim["id"]
                and r["kind"] == kind
                and r["source_id"] == source_id
            ),
            None,
        )
        if recovery:
            if amount < number(recovery["received_amount"]):
                raise BusinessError("更正后的回收低于已到账金额，请先处理资金差额")
            touch(
                recovery,
                expected_amount=money(amount),
                status="expected"
                if amount != number(recovery["confirmed_amount"])
                else recovery["status"],
                history=[
                    *recovery["history"],
                    {"before": recovery["expected_amount"], "after": money(amount), "at": now()},
                ],
            )
        elif amount:
            new(
                state,
                "recoveries",
                "REC",
                kind=kind,
                source_id=source_id,
                claim_id=claim["id"],
                policy_id=policy["id"],
                counterparty=counterparty,
                expected_amount=money(amount),
                confirmed_amount=0,
                received_amount=0,
                balance=0,
                status="expected",
                receipts=[],
                calculation_basis=basis,
                history=[],
                currency="CNY",
            )


def settlement_command(state, command, target, payload, user):
    if command == "fixing.prepare":
        return prepare_fixing(state, payload, user)
    if command == "fixing.confirm":
        permission(user, {"reviewer"})
        independent(user, target)
        if target["status"] != "pending_review" or target["missing_dates"]:
            raise BusinessError("只有完整且待复核的采价可锁定", "fixing_incomplete")
        if not target["observations"]:
            raise BusinessError("没有可锁定的观察值")
        average = total(target["observations"], "value") / len(target["observations"])
        return touch(
            target,
            status="locked",
            average_price=money(average),
            locked_by=user["id"],
            locked_at=now(),
            review_reason=text_field(payload, "reason", required=True),
        )
    if command == "claim.calculate":
        permission(user, {"operator"})
        policy = item(state, "policies", payload.get("policy_id"))
        fixing = item(state, "fixings", payload.get("fixing_id"))
        if fixing["status"] != "locked" or fixing["policy_id"] != policy["id"]:
            raise BusinessError("须选择本保单已锁定采价", "fixing_required")
        if policy["status"] != "active" or policy["pending_change"]:
            raise BusinessError("责任状态尚不允许核定")
        existing = next((c for c in state["claims"] if c["policy_id"] == policy["id"]), None)
        if existing and existing["status"] != "rejected":
            return existing
        calculation = claim_rule(policy, fixing)
        assessed = number(payload.get("assessed_amount", calculation["rule_amount"]))
        reason = text_field(payload, "reason", default="按合同规则计算")
        if existing:
            payable = next((p for p in state["payables"] if p["claim_id"] == existing["id"]), None)
            if payable and assessed < number(payable["paid_amount"]) + number(
                payable["reserved_amount"]
            ):
                raise BusinessError(
                    "重新核定金额低于已支付及在途金额，请先处理差额", "cash_conflict", 409
                )
            existing["history"].append(
                {
                    "approved_amount": existing["approved_amount"],
                    "assessed_amount": existing["assessed_amount"],
                    "status": existing["status"],
                    "fixing_id": existing["fixing_id"],
                    "calculation": copy.deepcopy(existing["calculation"]),
                    "reviewed_by": existing.get("reviewed_by"),
                    "review_reason": existing.get("review_reason"),
                    "at": now(),
                    "reason": reason,
                }
            )
            return touch(
                existing,
                fixing_id=fixing["id"],
                policy_version=policy["responsibility_version"],
                calculation=calculation,
                rule_amount=calculation["rule_amount"],
                assessed_amount=money(assessed),
                status="pending_review",
                created_by=user["id"],
                reason=reason,
            )
        return new(
            state,
            "claims",
            "CLM",
            policy_id=policy["id"],
            fixing_id=fixing["id"],
            policy_version=policy["responsibility_version"],
            calculation=calculation,
            rule_amount=calculation["rule_amount"],
            assessed_amount=money(assessed),
            approved_amount=0,
            status="pending_review",
            created_by=user["id"],
            reason=reason,
            history=[],
            currency="CNY",
            notification_status="not_sent",
        )
    if command == "claim.correct":
        permission(user, {"operator"})
        if target["status"] == "pending_review":
            raise BusinessError("请完成当前核定后再办理批准金额更正")
        amount = number(payload.get("assessed_amount"))
        payable = next((p for p in state["payables"] if p["claim_id"] == target["id"]), None)
        if payable and amount < number(payable["paid_amount"]) + number(payable["reserved_amount"]):
            raise BusinessError("更正金额低于已支付及在途金额，请先处理差额", "cash_conflict", 409)
        target["history"].append(
            {
                "approved_amount": target["approved_amount"],
                "assessed_amount": target["assessed_amount"],
                "status": target["status"],
                "reviewed_by": target.get("reviewed_by"),
                "review_reason": target.get("review_reason"),
                "at": now(),
                "reason": text_field(payload, "reason", required=True),
            }
        )
        return touch(
            target,
            assessed_amount=money(amount),
            status="pending_review",
            created_by=user["id"],
            reason=text_field(payload, "reason", required=True),
        )
    if command == "claim.review":
        permission(user, {"reviewer"})
        independent(user, target)
        if target["status"] != "pending_review":
            raise BusinessError("赔案当前不在待复核状态")
        decision = payload.get("decision", "approved")
        reason = text_field(payload, "reason", required=True)
        if decision == "rejected":
            return touch(target, status="rejected", reviewed_by=user["id"], review_reason=reason)
        if decision != "approved":
            raise BusinessError("无效核定决定")
        amount = number(payload.get("approved_amount", target["assessed_amount"]))
        payable = next((p for p in state["payables"] if p["claim_id"] == target["id"]), None)
        if payable and amount < number(payable["paid_amount"]) + number(payable["reserved_amount"]):
            raise BusinessError("批准金额不能低于已付及在途金额", "cash_conflict", 409)
        touch(
            target,
            status="zero_closed" if not amount else "payable",
            approved_amount=money(amount),
            reviewed_by=user["id"],
            review_reason=reason,
            approved_at=now(),
            approved_version=target["version"] + 1,
            notification_status="simulated_delivered",
            notification_reference=f"SIM-NOTICE-{uuid.uuid4().hex[:8]}",
        )
        if payable:
            payable["history"].append(
                {"before": payable["amount"], "after": money(amount), "at": now()}
            )
            touch(payable, amount=money(amount), claim_version=target["approved_version"])
            payable["basis_version"] = target["approved_version"]
        elif amount:
            policy = item(state, "policies", target["policy_id"])
            payable = new(
                state,
                "payables",
                "PAY",
                claim_id=target["id"],
                policy_id=policy["id"],
                counterparty=policy["insured_name"],
                amount=money(amount),
                paid_amount=0,
                reserved_amount=0,
                balance=money(amount),
                status="payable",
                currency="CNY",
                kind="claim",
                source_id=target["id"],
                basis_version=target["approved_version"],
                claim_version=target["approved_version"],
                history=[],
            )
        if payable:
            sync_claim_cash(state, target)
        policy = item(state, "policies", target["policy_id"])
        fixing = item(state, "fixings", target["fixing_id"])
        update_recoveries(state, target, policy, fixing)
        return target
    if command == "payment.create":
        permission(user, {"operator"})
        payable = target
        claim = item(state, "claims", payable["claim_id"]) if payable.get("claim_id") else None
        if claim and claim["status"] == "pending_review":
            raise BusinessError("核定正在更正复核中，不能新增付款")
        amount = number(payload.get("amount"), positive=True)
        available = (
            number(payable["amount"])
            - number(payable["paid_amount"])
            - number(payable["reserved_amount"])
        )
        if amount > available:
            raise BusinessError(
                "付款超过应付可用余额，待核实付款仍预占", "insufficient_balance", 409
            )
        payment = new(
            state,
            "payments",
            "PMT",
            payable_id=payable["id"],
            claim_id=claim["id"] if claim else None,
            kind=payable.get("kind", "claim"),
            source_id=payable.get("source_id"),
            amount=money(amount),
            paid_amount=0,
            reserved_amount=money(amount),
            status="pending_review",
            created_by=user["id"],
            events=[],
            currency="CNY",
            reference=text_field(payload, "reference", required=True),
            basis_version=payable.get("basis_version", payable.get("claim_version", 1)),
            claim_version=payable.get("claim_version"),
            external_no=None,
        )
        touch(payable, reserved_amount=money(number(payable["reserved_amount"]) + amount))
        return payment
    if command == "payment.review":
        permission(user, {"reviewer"})
        independent(user, target)
        if target["status"] != "pending_review":
            raise BusinessError("只有待审付款可复核")
        reason = text_field(payload, "reason", required=True)
        payable = item(state, "payables", target["payable_id"])
        if payload.get("decision", "approved") == "rejected":
            touch(
                payable,
                reserved_amount=money(
                    number(payable["reserved_amount"]) - number(target["reserved_amount"])
                ),
            )
            return touch(
                target,
                status="failed",
                reserved_amount=0,
                review_reason=reason,
                reviewed_by=user["id"],
            )
        if payload.get("decision", "approved") != "approved":
            raise BusinessError("无效付款审核决定")
        claim = item(state, "claims", target["claim_id"]) if target.get("claim_id") else None
        if (claim and claim["status"] == "pending_review") or target.get(
            "basis_version"
        ) != payable.get("basis_version"):
            raise BusinessError("付款所引用核定已变更，请退回重新申请", "stale_assessment", 409)
        return touch(
            target,
            status="processing",
            reviewed_by=user["id"],
            review_reason=reason,
            external_no=f"SIM-PAYMENT-{uuid.uuid4().hex[:10]}",
            sent_at=now(),
        )
    if command == "payment.receipt":
        return payment_receipt(state, target, payload, user)
    if command == "recovery.confirm":
        permission(user, {"reviewer"})
        amount = number(payload.get("amount", target["expected_amount"]))
        if amount < number(target["received_amount"]):
            raise BusinessError("确认应收不能低于已收金额")
        if amount != number(target["expected_amount"]):
            raise BusinessError("本期应收确认须与核定依据一致，差额请先更正核定")
        return touch(
            target,
            confirmed_amount=money(amount),
            balance=money(amount - number(target["received_amount"])),
            status="received" if amount == number(target["received_amount"]) else "confirmed",
            confirmed_by=user["id"],
            reference=text_field(payload, "reference", required=True),
        )
    if command == "recovery.receipt":
        return recovery_receipt(state, target, payload, user)
    raise BusinessError("不支持的结算命令")


def payment_receipt(state, payment, payload, user):
    permission(user, {"operator"})
    if payment["status"] == "pending_review":
        raise BusinessError("付款未批准，不能应用支付回执", "approval_required", 409)
    event_id = text_field(payload, "event_id", required=True)
    reference = text_field(payload, "reference", required=True)
    outcome = payload.get("outcome", "success")
    if outcome not in {"unknown", "partial", "success", "failed"}:
        raise BusinessError("不支持的付款回执状态")
    cumulative = number(
        payload.get(
            "cumulative_amount",
            payment["amount"] if outcome == "success" else payment["paid_amount"],
        )
    )
    receipt = {
        "event_id": event_id,
        "outcome": outcome,
        "cumulative_amount": money(cumulative),
        "reference": reference,
    }
    for candidate in state["payments"]:
        old = next((e for e in candidate["events"] if e["event_id"] == event_id), None)
        if old:
            if candidate["id"] != payment["id"] or any(old[k] != receipt[k] for k in receipt):
                raise BusinessError("支付回执编号已用于其他业务或内容冲突", "event_conflict", 409)
            return payment
    if payment["status"] in {"paid", "failed"}:
        if cumulative == number(payment["paid_amount"]):
            payment["events"].append({**receipt, "ignored": True, "at": now()})
            return touch(payment)
        raise BusinessError("终态付款不能直接改变金额，请进入对账处理", "terminal_state", 409)
    previous = number(payment["paid_amount"])
    if cumulative < previous or cumulative > number(payment["amount"]):
        raise BusinessError("累计支付不能减少或超过付款金额", "invalid_receipt")
    if outcome == "success" and cumulative != number(payment["amount"]):
        raise BusinessError("成功回执须对应全额，部分金额请选择partial")
    if outcome == "unknown" and cumulative != previous:
        raise BusinessError("未知状态不能确认新增实付金额")
    payable = item(state, "payables", payment["payable_id"])
    payment["events"].append(
        {**receipt, "at": now(), "source": "simulation_payment_channel", "actor": user["id"]}
    )
    if outcome == "unknown":
        return touch(payment, status="unknown")
    reserved = number(payment["amount"]) - cumulative if outcome != "failed" else Decimal(0)
    previous_reserved = number(payment["reserved_amount"])
    touch(
        payment,
        paid_amount=money(cumulative),
        reserved_amount=money(reserved),
        status="failed"
        if outcome == "failed"
        else "paid"
        if cumulative == number(payment["amount"])
        else "partially_paid",
    )
    touch(
        payable,
        paid_amount=money(number(payable["paid_amount"]) + cumulative - previous),
        reserved_amount=money(number(payable["reserved_amount"]) - previous_reserved + reserved),
    )
    if payment.get("claim_id"):
        sync_claim_cash(state, item(state, "claims", payment["claim_id"]))
    else:
        touch(
            payable,
            balance=money(number(payable["amount"]) - number(payable["paid_amount"])),
            status="paid"
            if number(payable["amount"]) == number(payable["paid_amount"])
            else "partially_paid"
            if number(payable["paid_amount"])
            else "payable",
        )
    return payment


def recovery_receipt(state, recovery, payload, user):
    permission(user, {"operator"})
    if recovery["status"] == "expected":
        raise BusinessError("请先复核确认应收金额，预计回收不等于应收或到账")
    event_id = text_field(payload, "event_id", required=True)
    reference = text_field(payload, "reference", required=True)
    amount = number(payload.get("amount"), positive=True)
    receipt = {"event_id": event_id, "amount": money(amount), "reference": reference}
    for candidate in state["recoveries"]:
        old = next((e for e in candidate["receipts"] if e["event_id"] == event_id), None)
        if old:
            if candidate["id"] != recovery["id"] or any(old[k] != receipt[k] for k in receipt):
                raise BusinessError("收款回执已分配或内容冲突", "event_conflict", 409)
            return recovery
    received = number(recovery["received_amount"]) + amount
    if received > number(recovery["confirmed_amount"]):
        raise BusinessError("回款分配超过确认应收余额", "over_allocation", 409)
    recovery["receipts"].append(
        {**receipt, "at": now(), "source": "simulation_bank_receipt", "actor": user["id"]}
    )
    return touch(
        recovery,
        received_amount=money(received),
        balance=money(number(recovery["confirmed_amount"]) - received),
        status="received"
        if received == number(recovery["confirmed_amount"])
        else "partially_received",
    )


def open_issues(state):
    issues = []
    for payable in state["payables"]:
        balance = number(payable["amount"]) - number(payable["paid_amount"])
        if balance:
            issues.append(
                {
                    "type": f"unpaid_{payable.get('kind', 'claim')}",
                    "target_id": payable["id"],
                    "amount": money(balance),
                    "description": "批准应付尚未足额支付",
                }
            )
    for payment in state["payments"]:
        if number(payment["reserved_amount"]):
            issues.append(
                {
                    "type": "payment_in_transit",
                    "target_id": payment["id"],
                    "amount": payment["reserved_amount"],
                    "description": "在途或待核实付款保留预占，须查询权威结果",
                }
            )
    for recovery in state["recoveries"]:
        remaining = number(recovery["expected_amount"]) - number(recovery["received_amount"])
        if remaining:
            issues.append(
                {
                    "type": f"{recovery['kind']}_recovery",
                    "target_id": recovery["id"],
                    "amount": money(remaining),
                    "description": "风险转移回收尚有未确认或未到账金额",
                }
            )
    for execution in state["executions"]:
        if number(execution["reserved_tons"]):
            issues.append(
                {
                    "type": "execution_pending",
                    "target_id": execution["id"],
                    "tons": execution["reserved_tons"],
                    "description": "交易请求仍有待确认量",
                }
            )
    for collection in ("allocations", "reinsurance_allocations"):
        for allocation in state[collection]:
            if allocation["status"] == "needs_review":
                issues.append(
                    {
                        "type": "allocation_review",
                        "target_id": allocation["id"],
                        "description": "批改后责任分配尚未复核",
                    }
                )
    for adjustment in state["premium_adjustments"]:
        if adjustment["status"] != "confirmed":
            issues.append(
                {
                    "type": "premium_receivable",
                    "target_id": adjustment["id"],
                    "amount": money(
                        number(adjustment["amount"]) - number(adjustment["received_amount"])
                    ),
                    "description": "批准批改增加的保费尚未足额确认",
                }
            )
    return issues


def reconcile_command(state, command, target, payload, user):
    if command == "reconciliation.run":
        permission(user, {"operator"})
        issues = open_issues(state)
        keys = {(issue["type"], issue["target_id"]) for issue in issues}
        for difference in state["reconciliations"]:
            if (
                difference["status"] == "open"
                and (difference["type"], difference["target_id"]) not in keys
            ):
                touch(difference, status="pending_review", source_resolved_at=now())
        created = []
        for issue in issues:
            existing = next(
                (
                    row
                    for row in state["reconciliations"]
                    if row["type"] == issue["type"]
                    and row["target_id"] == issue["target_id"]
                    and row["status"] in {"open", "pending_review"}
                ),
                None,
            )
            if existing:
                touch(existing, **issue, status="open")
                created.append(existing["id"])
            else:
                difference = new(
                    state,
                    "reconciliations",
                    "RECX",
                    **issue,
                    status="open",
                    created_by=user["id"],
                    evidence=None,
                    history=[],
                )
                created.append(difference["id"])
        return {
            "id": f"RUN-{uuid.uuid4().hex[:8]}",
            "status": "completed",
            "difference_count": len(issues),
            "difference_ids": created,
            "message": "无未结差异" if not issues else f"发现{len(issues)}项未结事项",
        }
    if command == "reconciliation.resolve":
        permission(user, {"reviewer"})
        if target["status"] == "resolved":
            return target
        if any(
            issue["type"] == target["type"] and issue["target_id"] == target["target_id"]
            for issue in open_issues(state)
        ):
            raise BusinessError(
                "源业务仍存在差异，请先查单、补收付或完成批准处理", "source_unresolved", 409
            )
        return touch(
            target,
            status="resolved",
            resolved_by=user["id"],
            resolved_at=now(),
            reason=text_field(payload, "reason", required=True),
            evidence=text_field(payload, "reference", required=True),
        )
    if command == "project.close":
        permission(user, {"reviewer"})
        if open_issues(state) or any(r["status"] != "resolved" for r in state["reconciliations"]):
            raise BusinessError("项目仍有收付、交易或对账未结事项，不能结案", "open_items", 409)
        if any(
            a["status"] not in {"issued", "rejected", "withdrawn"} for a in state["applications"]
        ):
            raise BusinessError("尚有投保申请未办结，请办理或撤回后结案", "open_applications", 409)
        final_policies = {
            c["policy_id"] for c in state["claims"] if c["status"] in {"paid", "zero_closed"}
        }
        if any(
            p["status"] == "active" and p["id"] not in final_policies for p in state["policies"]
        ):
            raise BusinessError("尚有有效保单未完成到期核赔", "open_policies", 409)
        return touch(
            target,
            status="closed",
            closed_at=now(),
            closed_by=user["id"],
            close_reason=text_field(payload, "reason", required=True),
        )
    raise BusinessError("不支持的对账命令")


TARGET_COLLECTIONS = {
    "application.update": "applications",
    "application.submit": "applications",
    "application.withdraw": "applications",
    "application.review": "applications",
    "application.premium": "applications",
    "application.import_confirm": "batches",
    "policy.issue": "applications",
    "policy.query": "applications",
    "policy.change": "policies",
    "reinsurance.allocate": "reinsurance",
    "hedge.update": "plans",
    "hedge.quote": "plans",
    "hedge.review": "plans",
    "hedge.submit": "plans",
    "hedge.confirm": "executions",
    "hedge.query": "executions",
    "hedge.allocate": "hedges",
    "fixing.confirm": "fixings",
    "claim.review": "claims",
    "claim.correct": "claims",
    "payment.create": "payables",
    "payment.review": "payments",
    "payment.receipt": "payments",
    "recovery.confirm": "recoveries",
    "recovery.receipt": "recoveries",
    "reconciliation.resolve": "reconciliations",
    "project.close": "projects",
    "premium.adjustment_confirm": "premium_adjustments",
}
CREATE_COMMANDS = {
    "application.create",
    "application.import_preview",
    "hedge.plan",
    "fixing.prepare",
    "claim.calculate",
    "reconciliation.run",
    "decision.record",
}


def dispatch(state, command, target, payload, user):
    if command == "decision.record":
        return record_decision(state, payload, user)
    if command == "premium.adjustment_confirm":
        permission(user, {"operator"})
        amount = number(payload.get("amount"), positive=True)
        reference = text_field(payload, "reference", required=True)
        previous = next((r for r in target["receipts"] if r["reference"] == reference), None)
        if previous:
            if number(previous["amount"]) != amount:
                raise BusinessError("同一批改保费回执内容冲突", "event_conflict", 409)
            return target
        received = number(target["received_amount"]) + amount
        if received > number(target["amount"]):
            raise BusinessError("新增保费回执超过应收余额", "over_allocation", 409)
        target["receipts"].append(
            {
                "amount": money(amount),
                "reference": reference,
                "at": now(),
                "source": "simulation_receipt",
                "actor": user["id"],
            }
        )
        return touch(
            target,
            received_amount=money(received),
            status="confirmed" if received == number(target["amount"]) else "pending_confirmation",
        )
    if command == "application.withdraw":
        permission(user, {"operator", "customer"})
        own_application(user, target)
        if target["status"] in {"issued", "issuing"}:
            raise BusinessError("已出单或出单中申请不能撤回，请走保单变更")
        if number(target["premium_received"]):
            raise BusinessError("申请有已收保费，须先办理经复核退款处理")
        return touch(
            target, status="withdrawn", reason=text_field(payload, "reason", required=True)
        )
    if command.startswith("application.") or command in {"policy.issue", "policy.query"}:
        return application_command(state, command, target, payload, user)
    if command == "policy.change":
        return policy_change(state, target, payload, user)
    if command == "reinsurance.allocate":
        return reinsurance_allocate(state, target, payload, user)
    if command.startswith("hedge."):
        return hedge_command(state, command, target, payload, user)
    if command.startswith(("fixing.", "claim.", "payment.", "recovery.")):
        return settlement_command(state, command, target, payload, user)
    if command.startswith("reconciliation.") or command == "project.close":
        return reconcile_command(state, command, target, payload, user)
    raise BusinessError("未识别的工作台命令", "unknown_command")


def record_decision(state, payload, user):
    """Freeze a human assessment; this does not approve underwriting or trading."""
    permission(user, {"operator", "reviewer"})
    disposition = payload.get("disposition")
    if disposition not in {"proceed", "hold", "review"}:
        raise BusinessError("请选择继续办理、暂缓或补充复核", "invalid_disposition")
    context = payload.get("source_context") or {}
    if not isinstance(context, dict):
        raise BusinessError("数据上下文须为对象", "invalid_context")
    context = copy.deepcopy(context)
    for key in ("market_version", "casde_version", "data_as_of"):
        if key in context and context[key] is not None:
            text_field(context, key)
    if context.get("data_as_of"):
        try:
            datetime.fromisoformat(context["data_as_of"].replace("Z", "+00:00"))
        except ValueError:
            raise BusinessError("数据截止时点须为有效日期或ISO时间", "invalid_context") from None
    status = context.get("source_status")
    if status is not None and (
        not isinstance(status, dict)
        or any(
            not isinstance(key, str)
            or not isinstance(value, str)
            or len(key) > 80
            or len(value) > 120
            for key, value in status.items()
        )
    ):
        raise BusinessError("来源状态须为来源名称和状态文本映射", "invalid_context")
    from app.core.config import get_settings
    from app.repositories.market_cache import MarketCacheError, read_market_snapshot
    from app.platform.data import read_casde
    from app.platform.catalog_store import market_snapshot

    settings = get_settings()
    verified = {"market_version": None, "casde_version": None}
    source_status = {"market": "unavailable", "casde": "unavailable"}
    default_data_as_of = None
    try:
        market_rows, manifest = market_snapshot(
            state["product"]["contract"]
        ) or read_market_snapshot(
            settings.market_cache_dir,
            state["product"]["contract"],
            settings.data_start_date,
            settings.data_end_date,
        )
        verified["market_version"] = manifest["files"]["market.parquet"]["sha256"]
        source_status["market"] = "available"
        default_data_as_of = max(str(row["tradeDate"])[:10] for row in market_rows)
    except (MarketCacheError, KeyError, ValueError):
        pass
    try:
        casde_document = read_casde()
        verified["casde_version"] = casde_document["release_id"]
        source_status["casde"] = "available"
        if default_data_as_of is None:
            default_data_as_of = casde_document.get("source_published_at")
    except (OSError, ValueError, KeyError):
        pass
    # Keep exactly the reviewed context, alongside separately verified local versions.
    # A human record never asserts that unconnected sources have been validated.
    for key, value in verified.items():
        context.setdefault(key, value)
    context.setdefault("data_as_of", default_data_as_of)
    context.setdefault("source_status", source_status)
    return new(
        state,
        "decision_records",
        "DEC",
        status="recorded",
        region=text_field(payload, "region", required=True),
        disposition=disposition,
        reason=text_field(payload, "reason", required=True),
        product_id=state["product"]["id"],
        product_version=state["product"]["version"],
        contract=state["product"]["contract"],
        source_context=context,
        verified_source_versions=verified,
        created_by=user["id"],
        decision_type="human_assessment",
        limitation="人工承保参考意见；不替代核保审批，不改变价格险赔付规则，不自动下单",
    )


def response_result(result, user):
    public_result = copy.deepcopy(result)
    if user["role"] == "customer":
        public_result.pop("decision_id", None)
        public_result.pop("decision_snapshot", None)
    return public_result


def execute_command(request, user):
    project_id = request["project_id"]
    allowed_project(user, project_id)
    request_id = request["request_id"]
    if not request_id or len(request_id) > 150:
        raise BusinessError("请提供有效的幂等请求号", "request_id_required")
    command = request["command"]
    if command not in TARGET_COLLECTIONS and command not in CREATE_COMMANDS:
        raise BusinessError("未识别的工作台命令", "unknown_command")
    try:
        encoded_request = json.dumps(request, sort_keys=True, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        raise BusinessError("请求包含无法处理或非有限的数值", "invalid_payload") from None
    if len(encoded_request) > 1_000_000:
        raise BusinessError("请求资料过大，请减少本批行数", "request_too_large", 413)
    fingerprint = hashlib.sha256(encoded_request.encode()).hexdigest()
    with transaction() as connection:
        ensure_schema(connection)
        state = load(connection, project_id)
        receipt = connection.execute(
            "SELECT * FROM platform_requests WHERE actor_id = ? AND request_id = ?",
            (user["id"], request_id),
        ).fetchone()
        if receipt:
            if receipt["fingerprint"] != fingerprint:
                raise BusinessError(
                    "同一请求编号的内容不一致，请确认原操作结果", "idempotency_conflict", 409
                )
            saved = json.loads(receipt["response"])
            saved["result"] = response_result(saved["result"], user)
            return {**saved, "snapshot": snapshot(state, user), "replayed": True}
        if state["projects"][0]["status"] == "closed":
            raise BusinessError("项目已结案，不能继续修改业务记录", "project_closed", 409)
        target = None
        if command in TARGET_COLLECTIONS:
            target = item(state, TARGET_COLLECTIONS[command], request.get("target_id"))
            if user["role"] == "customer":
                if TARGET_COLLECTIONS[command] not in {"applications", "batches"}:
                    raise BusinessError("客户只能办理本人投保申请", "forbidden", 403)
                if TARGET_COLLECTIONS[command] == "applications":
                    own_application(user, target)
                elif target["created_by"] != user["id"]:
                    raise BusinessError("不能确认其他客户的导入记录", "forbidden", 403)
            check_version(target, request.get("expected_version"))
        payload = request.get("payload", {})
        if not isinstance(payload, dict):
            raise BusinessError("命令参数必须是对象")
        result = dispatch(state, command, target, payload, user)
        state["revision"] += 1
        state["as_of"] = now()
        message = "业务操作已保存"
        new(
            state,
            "audit_events",
            "EVT",
            command=command,
            actor=user["id"],
            actor_name=user["name"],
            actor_role=user["role"],
            target_id=result.get("id"),
            request_id=request_id,
            status="recorded",
            message=message,
            reason=payload.get("reason", ""),
            result_status=result.get("status"),
            before_version=request.get("expected_version"),
            after_version=result.get("version"),
        )
        save(connection, state)
        response = {"result": response_result(result, user), "message": message, "replayed": False}
        connection.execute(
            "INSERT INTO platform_requests VALUES (?, ?, ?, ?)",
            (
                user["id"],
                request_id,
                fingerprint,
                json.dumps(response, ensure_ascii=False, allow_nan=False),
            ),
        )
        return {**response, "snapshot": snapshot(state, user)}


def scenario(project_id, user, settlement_price, delay_days=0):
    permission(user, {"operator", "reviewer"})
    allowed_project(user, project_id)
    price = number(settlement_price)
    if not isinstance(delay_days, int) or not 0 <= delay_days <= 365:
        raise BusinessError("回款延迟应为0至365天")
    with transaction() as connection:
        state = load(connection, project_id)
    rows = []
    for policy in state["policies"]:
        if policy["status"] != "active":
            continue
        gross = number(claim_rule(policy, {"average_price": money(price)})["rule_amount"])
        ri_allocations = [
            a
            for a in state["reinsurance_allocations"]
            if a["policy_id"] == policy["id"] and a["status"] == "confirmed"
        ]
        reinsurance = gross * total(ri_allocations, "ratio")
        ri_cost = total(ri_allocations, "premium")
        hedge_recovery, hedge_cost = Decimal(0), Decimal(0)
        for allocation in state["allocations"]:
            if allocation["policy_id"] != policy["id"] or allocation["status"] != "confirmed":
                continue
            hedge = item(state, "hedges", allocation["hedge_id"])
            hedge_recovery += max(Decimal(0), number(hedge["strike_price"]) - price) * number(
                allocation["tons"]
            )
            hedge_cost += number(hedge["premium_per_ton"]) * number(allocation["tons"])
        net = gross - reinsurance - hedge_recovery + ri_cost + hedge_cost
        funding_gap = gross if delay_days else max(Decimal(0), gross - reinsurance - hedge_recovery)
        rows.append(
            {
                "policy_id": policy["id"],
                "policy_no": policy["policy_no"],
                "gross_claim": money(gross),
                "reinsurance_recovery": money(reinsurance),
                "hedge_recovery": money(hedge_recovery),
                "reinsurance_premium": money(ri_cost),
                "hedge_premium": money(hedge_cost),
                "net_loss": float(net.quantize(Decimal("0.01"))),
                "funding_gap": money(funding_gap),
                "delay_financing_cost": money(funding_gap * Decimal("0.03") * delay_days / 365),
            }
        )
    fields = (
        "gross_claim",
        "reinsurance_recovery",
        "hedge_recovery",
        "reinsurance_premium",
        "hedge_premium",
        "funding_gap",
        "delay_financing_cost",
    )
    totals = {key: money(total(rows, key)) for key in fields}
    totals["net_loss"] = round(sum(r["net_loss"] for r in rows), 2)
    return {
        "project_id": project_id,
        "revision": state["revision"],
        "execution_mode": "simulation",
        "settlement_price": money(price),
        "delay_days": delay_days,
        "calculation_basis": "gross_claim",
        "annual_financing_rate": 0.03,
        "rows": rows,
        "totals": totals,
        "assumptions": [
            "同一结算价格情景作用于保单及匹配场外看跌合同；再保按毛赔款分出",
            "仅计已确认分配；分保保费及已分配期权权利金分别列示",
            "到账延迟仅影响现金缺口与假设资金成本，不改变批准保险赔款",
            "未计保险保费收入、税费及其他经营成本，净损失仅供方案比较",
        ],
        "limitations": [
            "全部合同为产品条款，非正式承保、报价或投资建议",
            "资金成本使用3%示例年率；正式合同及资金时点须另行确认",
        ],
    }
