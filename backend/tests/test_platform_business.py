"""Business invariants for policy, execution and cash operations."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.platform_routes import router


@pytest.fixture
def workspace(platform_accounts):
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    headers = {}
    for role in ("operator", "reviewer", "customer"):
        response = client.post(
            "/api/v2/session",
            json={"username": f"fixture-{role}", "password": platform_accounts},
        )
        assert response.status_code == 200
        headers[role] = {"Authorization": f"Bearer {response.json()['token']}"}

    class Workspace:
        def get(self, role="operator"):
            response = client.get("/api/v2/workspace", headers=headers[role])
            assert response.status_code == 200, response.text
            return response.json()

        def entity(self, identity, role="operator"):
            for value in self.get(role).values():
                if isinstance(value, list):
                    for entity in value:
                        if isinstance(entity, dict) and entity.get("id") == identity:
                            return entity
            raise AssertionError(identity)

        def request(self, command, target=None, payload=None, role="operator", **overrides):
            body = {
                "request_id": uuid.uuid4().hex,
                "project_id": "PRJ-001",
                "command": command,
                "payload": payload or {},
            }
            if target:
                body.update(target_id=target, expected_version=self.entity(target, role)["version"])
            body.update(overrides)
            return client.post("/api/v2/workspace/commands", headers=headers[role], json=body)

        def command(self, command, target=None, payload=None, role="operator", **overrides):
            response = self.request(command, target, payload, role, **overrides)
            assert response.status_code == 200, response.text
            return response.json()["result"]

        def claim(self, price=2300, policy_id="POL-001"):
            dates = self.entity(policy_id)["fixing_dates"]
            fixing = self.command(
                "fixing.prepare",
                payload={
                    "policy_id": policy_id,
                    "prices": [{"date": day, "value": price} for day in dates],
                    "reason": "测试用人工模拟样例",
                },
            )
            self.command("fixing.confirm", fixing["id"], {"reason": "逐日核对完整"}, "reviewer")
            return self.command(
                "claim.calculate", payload={"policy_id": policy_id, "fixing_id": fixing["id"]}
            )

    result = Workspace()
    result.client, result.headers = client, headers
    return result


def application_payload(**extra):
    return {
        "applicant_name": "测试合作社",
        "insured_name": "测试被保险人",
        "tons": 100,
        "area_mu": 200,
        "region": "黑龙江省",
        "phone": "13800000000",
        "period_start": "2026-07-01",
        "period_end": "2026-10-23",
        "terms_confirmed": True,
        "materials": ["种植证明"],
        **extra,
    }


def approved_plan(workspace, tons=700):
    plan = workspace.command("hedge.plan", payload={"policy_ids": ["POL-001"], "tons": tons})
    workspace.command("hedge.quote", plan["id"])
    return workspace.command("hedge.review", plan["id"], {"reason": "测试审批"}, "reviewer")


def test_auth_customer_scope_and_server_owned_roles(workspace):
    client = workspace.client
    assert client.get("/api/v2/workspace").status_code == 401
    assert (
        client.post("/api/v2/session", json={"username": "operator", "password": "bad"}).status_code
        == 401
    )
    customer = workspace.get("customer")
    assert {a["id"] for a in customer["applications"]} == {"APP-001", "APP-004"}
    assert customer["reinsurance"] == [] and customer["audit_events"] == []
    assert (
        workspace.request(
            "application.review", "APP-003", {"decision": "approved", "reason": "越权"}
        ).status_code
        == 403
    )
    response = client.post(
        "/api/v2/workspace/commands",
        headers=workspace.headers["customer"],
        json={
            "request_id": "cross-customer",
            "command": "application.submit",
            "target_id": "APP-003",
            "expected_version": 1,
            "payload": {},
        },
    )
    assert response.status_code == 403
    assert (
        client.get(
            "/api/v2/workspace?project_id=OTHER", headers=workspace.headers["operator"]
        ).status_code
        == 403
    )


def test_application_review_premium_issuance_and_retry(workspace):
    app = workspace.command("application.create", payload=application_payload())
    workspace.command("application.submit", app["id"])
    workspace.command(
        "application.review", app["id"], {"decision": "approved", "reason": "材料齐全"}, "reviewer"
    )
    assert workspace.request("policy.issue", app["id"]).status_code == 422
    workspace.command("application.premium", app["id"], {"amount": 3000, "reference": "PREM-1"})
    workspace.command("application.premium", app["id"], {"amount": 3000, "reference": "PREM-2"})
    workspace.command("policy.issue", app["id"])
    workspace.command("policy.query", app["id"], {"outcome": "unknown"})
    assert workspace.request("policy.issue", app["id"]).status_code == 409
    policy = workspace.command("policy.query", app["id"])
    assert policy["policy_no"].startswith("SIM-")
    assert workspace.command("policy.query", app["id"])["id"] == policy["id"]
    assert len([p for p in workspace.get()["policies"] if p["application_id"] == app["id"]]) == 1


def test_import_preview_errors_and_approval_invalidation(workspace):
    preview = workspace.command(
        "application.import_preview",
        payload={"rows": [application_payload(), application_payload(tons=-1)]},
    )
    assert preview["error_count"] == 1
    assert workspace.request("application.import_confirm", preview["id"]).status_code == 422
    workspace.command(
        "application.review", "APP-003", {"decision": "approved", "reason": "符合"}, "reviewer"
    )
    updated = workspace.command("application.update", "APP-003", {"tons": 700})
    assert updated["status"] == "draft" and updated["reviewed_by"] is None


def test_request_replay_returns_current_snapshot_and_detects_conflicts(workspace):
    body = {
        "request_id": "durable-id",
        "project_id": "PRJ-001",
        "command": "application.create",
        "payload": application_payload(),
    }
    first = workspace.client.post(
        "/api/v2/workspace/commands", headers=workspace.headers["operator"], json=body
    ).json()
    workspace.command("application.submit", first["result"]["id"])
    second = workspace.client.post(
        "/api/v2/workspace/commands", headers=workspace.headers["operator"], json=body
    ).json()
    assert second["replayed"] is True
    assert second["snapshot"]["revision"] > first["snapshot"]["revision"]
    assert (
        len([a for a in second["snapshot"]["applications"] if a["id"] == first["result"]["id"]])
        == 1
    )
    body["payload"]["tons"] = 200
    assert (
        workspace.client.post(
            "/api/v2/workspace/commands", headers=workspace.headers["operator"], json=body
        ).status_code
        == 409
    )
    assert (
        workspace.request("application.submit", "APP-004", expected_version=900).status_code == 409
    )


def test_expired_quote_and_plan_modification_invalidate_approval(workspace):
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    workspace.command("hedge.quote", "HPL-001", {"quote_expires_at": past})
    assert (
        workspace.request("hedge.review", "HPL-001", {"reason": "过期"}, "reviewer").status_code
        == 409
    )
    workspace.command("hedge.quote", "HPL-001")
    workspace.command("hedge.review", "HPL-001", {"reason": "批准"}, "reviewer")
    workspace.command("hedge.update", "HPL-001", {"tons": 900})
    assert workspace.request("hedge.submit", "HPL-001").status_code == 409


def test_concurrent_executions_reserve_and_unknown_does_not_release(workspace):
    first = approved_plan(workspace)
    second = approved_plan(workspace)
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(lambda p: workspace.request("hedge.submit", p["id"]), [first, second])
        )
    assert sorted(r.status_code for r in responses) == [200, 409]
    execution = next(r.json()["result"] for r in responses if r.status_code == 200)
    workspace.command("hedge.query", execution["id"], {"outcome": "unknown"})
    assert workspace.entity(execution["id"])["reserved_tons"] == 700
    assert workspace.get()["summary"]["hedged_tons"] == 0
    workspace.command(
        "hedge.confirm", execution["id"], {"cumulative_tons": 300, "event_id": "fill-1"}, "reviewer"
    )
    execution = workspace.entity(execution["id"])
    assert execution["reserved_tons"] == 400 and execution["confirmed_tons"] == 300
    hedge = workspace.get()["hedges"][0]
    workspace.command("hedge.allocate", hedge["id"], {"policy_id": "POL-001", "tons": 300})
    assert (
        workspace.request(
            "hedge.allocate", hedge["id"], {"policy_id": "POL-001", "tons": 1}
        ).status_code
        == 409
    )
    assert workspace.get()["summary"]["hedged_tons"] == 300
    workspace.command(
        "hedge.confirm",
        execution["id"],
        {"cumulative_tons": 300, "event_id": "final-1", "final": True},
        "reviewer",
    )
    assert workspace.entity(execution["id"])["reserved_tons"] == 0


def test_fixing_missing_and_approved_payable_only(workspace):
    fixing = workspace.command(
        "fixing.prepare",
        payload={
            "policy_id": "POL-001",
            "prices": [{"date": "2026-10-19", "value": 2300}],
            "reason": "缺失样例",
        },
    )
    assert fixing["status"] == "missing" and len(fixing["missing_dates"]) == 4
    assert (
        workspace.request(
            "fixing.confirm", fixing["id"], {"reason": "不完整"}, "reviewer"
        ).status_code
        == 422
    )
    claim = workspace.claim()
    assert claim["rule_amount"] == 120000
    assert workspace.get()["payables"] == []
    workspace.command("claim.review", claim["id"], {"reason": "核定通过"}, "reviewer")
    assert workspace.get()["payables"][0]["amount"] == 120000
    fixing_id = claim["fixing_id"]
    workspace.command("claim.calculate", payload={"policy_id": "POL-001", "fixing_id": fixing_id})
    assert len(workspace.get()["claims"]) == 1


def test_zero_claim_closes_without_creating_payment_or_payable(workspace):
    claim = workspace.claim(price=2500)
    workspace.command("claim.review", claim["id"], {"reason": "无触发赔款"}, "reviewer")
    assert workspace.entity(claim["id"])["status"] == "zero_closed"
    assert workspace.get()["payables"] == [] and workspace.get()["payments"] == []


def test_partial_unknown_duplicate_payment_and_recovery_are_independent(workspace):
    workspace.command(
        "reinsurance.allocate",
        "RI-001",
        {"policy_id": "POL-001", "reference": "SIM-RI"},
        "reviewer",
    )
    claim = workspace.claim()
    workspace.command("claim.review", claim["id"], {"reason": "同意核定"}, "reviewer")
    payable = next(p for p in workspace.get()["payables"] if p.get("kind") == "claim")
    payment = workspace.command(
        "payment.create", payable["id"], {"amount": 120000, "reference": "PAY-1"}
    )
    assert (
        workspace.request(
            "payment.receipt",
            payment["id"],
            {"event_id": "before-approval", "reference": "bank", "outcome": "success"},
        ).status_code
        == 409
    )
    workspace.command("payment.review", payment["id"], {"reason": "批准"}, "reviewer")
    workspace.command(
        "payment.receipt",
        payment["id"],
        {"outcome": "unknown", "event_id": "bank-unknown", "reference": "bank"},
    )
    assert workspace.entity(payable["id"])["reserved_amount"] == 120000
    assert (
        workspace.request(
            "payment.create", payable["id"], {"amount": 1, "reference": "pay2"}
        ).status_code
        == 409
    )
    partial = {
        "outcome": "partial",
        "cumulative_amount": 50000,
        "event_id": "bank-partial",
        "reference": "bank",
    }
    workspace.command("payment.receipt", payment["id"], partial)
    workspace.command("payment.receipt", payment["id"], partial)
    assert workspace.entity(payable["id"])["paid_amount"] == 50000
    assert workspace.entity(payable["id"])["reserved_amount"] == 70000
    workspace.command(
        "payment.receipt",
        payment["id"],
        {"outcome": "success", "event_id": "bank-final", "reference": "bank"},
    )
    assert workspace.entity(claim["id"])["status"] == "paid"
    recovery = workspace.get()["recoveries"][0]
    assert recovery["expected_amount"] == 36000 and recovery["received_amount"] == 0
    workspace.command("recovery.confirm", recovery["id"], {"reference": "RI-confirm"}, "reviewer")
    receipt = {"amount": 10000, "event_id": "RI-bank-1", "reference": "bank"}
    workspace.command("recovery.receipt", recovery["id"], receipt)
    workspace.command("recovery.receipt", recovery["id"], receipt)
    assert workspace.entity(recovery["id"])["received_amount"] == 10000
    assert workspace.entity(recovery["id"])["status"] == "partially_received"
    run = workspace.command("reconciliation.run")
    assert run["difference_count"] > 0
    difference = workspace.get()["reconciliations"][0]
    assert (
        workspace.request(
            "reconciliation.resolve",
            difference["id"],
            {"reason": "未到账不能关闭", "reference": "evidence"},
            "reviewer",
        ).status_code
        == 409
    )


def test_claim_correction_is_delta_not_second_full_liability(workspace):
    claim = workspace.claim()
    workspace.command("claim.review", claim["id"], {"reason": "批准"}, "reviewer")
    workspace.command(
        "claim.correct", claim["id"], {"assessed_amount": 130000, "reason": "经复核的模拟更正"}
    )
    workspace.command("claim.review", claim["id"], {"reason": "更正批准"}, "reviewer")
    assert len(workspace.get()["payables"]) == 1
    assert workspace.get()["payables"][0]["amount"] == 130000
    assert len(workspace.entity(claim["id"])["history"]) == 1


def test_rejected_claim_can_be_corrected_and_resubmitted_without_duplicate_payable(workspace):
    claim = workspace.claim()
    workspace.command(
        "claim.review", claim["id"], {"decision": "rejected", "reason": "补充核定依据"}, "reviewer"
    )
    revised = workspace.command(
        "claim.correct", claim["id"], {"assessed_amount": 125000, "reason": "已核对补充材料"}
    )
    assert revised["status"] == "pending_review"
    assert revised["history"][-1]["status"] == "rejected"
    assert revised["history"][-1]["review_reason"] == "补充核定依据"
    assert workspace.get()["payables"] == []
    workspace.command("claim.review", claim["id"], {"reason": "重提核定通过"}, "reviewer")
    state = workspace.get()
    assert len(state["claims"]) == len(state["payables"]) == 1
    assert state["payables"][0]["amount"] == 125000


def test_rejected_claim_recalculation_reuses_claim_and_keeps_original_fixing_history(workspace):
    claim = workspace.claim()
    workspace.command(
        "claim.review",
        claim["id"],
        {"decision": "rejected", "reason": "采价需重新核对"},
        "reviewer",
    )
    dates = workspace.entity("POL-001")["fixing_dates"]
    fixing = workspace.command(
        "fixing.prepare",
        payload={
            "policy_id": "POL-001",
            "prices": [{"date": day, "value": 2310} for day in dates],
            "reason": "补充价格依据",
        },
    )
    workspace.command("fixing.confirm", fixing["id"], {"reason": "补充复核"}, "reviewer")
    revised = workspace.command(
        "claim.calculate",
        payload={"policy_id": "POL-001", "fixing_id": fixing["id"], "reason": "按重核价格提交"},
    )
    assert revised["id"] == claim["id"]
    assert revised["status"] == "pending_review"
    assert revised["fixing_id"] == fixing["id"]
    assert revised["rule_amount"] == 108000
    assert revised["history"][-1]["fixing_id"] == claim["fixing_id"]
    assert revised["history"][-1]["review_reason"] == "采价需重新核对"
    assert workspace.get()["payables"] == []
    workspace.command("claim.review", claim["id"], {"reason": "复核通过"}, "reviewer")
    assert len(workspace.get()["claims"]) == len(workspace.get()["payables"]) == 1


def test_rejected_correction_recalculation_keeps_existing_fund_reservations(workspace):
    claim = workspace.claim()
    workspace.command("claim.review", claim["id"], {"reason": "批准"}, "reviewer")
    payable = workspace.get()["payables"][0]
    workspace.command("payment.create", payable["id"], {"amount": 10000, "reference": "reserved"})
    workspace.command(
        "claim.correct", claim["id"], {"assessed_amount": 130000, "reason": "补充核定"}
    )
    workspace.command(
        "claim.review", claim["id"], {"decision": "rejected", "reason": "需补充依据"}, "reviewer"
    )
    request = {"policy_id": "POL-001", "fixing_id": claim["fixing_id"], "assessed_amount": 500}
    response = workspace.request("claim.calculate", payload=request)
    assert response.status_code == 409 and response.json()["detail"]["code"] == "cash_conflict"
    response = workspace.request(
        "claim.correct", claim["id"], {"assessed_amount": 500, "reason": "不得冲减在途资金"}
    )
    assert response.status_code == 409
    revised = workspace.command(
        "claim.calculate", payload={**request, "assessed_amount": 125000, "reason": "依据补齐"}
    )
    assert revised["approved_amount"] == 120000
    assert workspace.entity(payable["id"])["amount"] == 120000
    workspace.command("claim.review", claim["id"], {"reason": "重新批准"}, "reviewer")
    state = workspace.get()
    assert len(state["payables"]) == 1
    assert state["payables"][0]["amount"] == 125000
    assert state["payables"][0]["reserved_amount"] == 10000
    assert state["payables"][0]["paid_amount"] == 0


def test_reinsurance_reconfirmation_checks_total_ratio_after_policy_change(workspace):
    import copy

    from app.platform.business import load, save
    from app.platform.store import transaction

    first = workspace.command(
        "reinsurance.allocate", "RI-001", {"policy_id": "POL-001", "reference": "first"}, "reviewer"
    )
    with transaction() as conn:
        state = load(conn, "PRJ-001")
        second = copy.deepcopy(state["reinsurance"][0])
        second.update(id="RI-SECOND", ratio=0.8, contract_no="RI-SECOND-CONTRACT")
        state["reinsurance"].append(second)
        save(conn, state)
    workspace.command("policy.change", "POL-001", {"tons": 1250, "reason": "核准新增种植量"})
    workspace.command(
        "policy.change", "POL-001", {"action": "approve", "reason": "批改通过"}, "reviewer"
    )
    second_allocation = workspace.command(
        "reinsurance.allocate",
        "RI-SECOND",
        {"policy_id": "POL-001", "reference": "second"},
        "reviewer",
    )
    repeated = workspace.command(
        "reinsurance.allocate",
        "RI-SECOND",
        {"policy_id": "POL-001", "reference": "same"},
        "reviewer",
    )
    assert repeated["id"] == second_allocation["id"]
    response = workspace.request(
        "reinsurance.allocate",
        "RI-001",
        {"policy_id": "POL-001", "reference": "reconfirm"},
        "reviewer",
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "over_allocation"
    state = workspace.get()
    assert workspace.entity(first["id"])["status"] == "needs_review"
    assert (
        sum(a["ratio"] for a in state["reinsurance_allocations"] if a["status"] == "confirmed")
        == 0.8
    )
    assert state["summary"]["retained_tons"] == 1050


def test_business_state_persists_and_scenario_delay_never_changes_claim(workspace):
    workspace.command(
        "reinsurance.allocate", "RI-001", {"policy_id": "POL-001", "reference": "ri"}, "reviewer"
    )
    first = workspace.client.post(
        "/api/v2/workspace/scenarios",
        headers=workspace.headers["operator"],
        json={"settlement_price": 2300, "delay_days": 0},
    ).json()
    second = workspace.client.post(
        "/api/v2/workspace/scenarios",
        headers=workspace.headers["operator"],
        json={"settlement_price": 2300, "delay_days": 30},
    ).json()
    assert first["totals"]["gross_claim"] == second["totals"]["gross_claim"] == 200000
    assert second["totals"]["funding_gap"] > first["totals"]["funding_gap"]
    assert second["totals"]["reinsurance_recovery"] == 36000
    report = workspace.client.get("/api/v2/workspace/report", headers=workspace.headers["operator"])
    assert report.status_code == 200 and report.json()["execution_mode"] == "simulation"
    assert "attachment" in report.headers["Content-Disposition"]


def test_premiums_and_policy_refunds_use_distinct_approved_payables(workspace):
    workspace.command(
        "reinsurance.allocate",
        "RI-001",
        {"policy_id": "POL-001", "reference": "RI-ACCEPTED"},
        "reviewer",
    )
    ri = next(p for p in workspace.get()["payables"] if p.get("kind") == "reinsurance_premium")
    assert ri["amount"] == 21600 and ri["claim_id"] is None
    plan = approved_plan(workspace, 700)
    execution = workspace.command("hedge.submit", plan["id"])
    workspace.command(
        "hedge.confirm",
        execution["id"],
        {"cumulative_tons": 300, "event_id": "otc-premium-1"},
        "reviewer",
    )
    workspace.command(
        "hedge.confirm",
        execution["id"],
        {"cumulative_tons": 700, "event_id": "otc-premium-2", "final": True},
        "reviewer",
    )
    premiums = [p for p in workspace.get()["payables"] if p.get("kind") == "hedge_premium"]
    assert len(premiums) == 1 and premiums[0]["amount"] == 31500
    payment = workspace.command(
        "payment.create", premiums[0]["id"], {"amount": 31500, "reference": "premium-payment"}
    )
    workspace.command("payment.review", payment["id"], {"reason": "权利金审核"}, "reviewer")
    workspace.command(
        "payment.receipt",
        payment["id"],
        {"outcome": "success", "event_id": "premium-bank-1", "reference": "bank"},
    )
    assert workspace.entity(premiums[0]["id"])["status"] == "paid"
    assert workspace.get()["claims"] == []
    workspace.command("policy.change", "POL-002", {"tons": 600, "reason": "模拟减量批改"})
    workspace.command(
        "policy.change", "POL-002", {"action": "approve", "reason": "批准减量"}, "reviewer"
    )
    refund = next(p for p in workspace.get()["payables"] if p.get("kind") == "premium_refund")
    assert refund["amount"] == 12000 and refund["claim_id"] is None
    assert workspace.entity("POL-002")["history"][0]["before"]["tons"] == 800


def test_policy_period_must_cover_the_product_fixing_window(workspace):
    response = workspace.request(
        "application.create",
        payload=application_payload(period_start="2027-01-01", period_end="2027-10-23"),
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "fixing_period_mismatch"


def test_project_close_is_reachable_after_all_business_and_cash_are_resolved(workspace):
    workspace.command(
        "reinsurance.allocate",
        "RI-001",
        {"policy_id": "POL-001", "reference": "ri-for-close"},
        "reviewer",
    )
    plan = approved_plan(workspace, 300)
    execution = workspace.command("hedge.submit", plan["id"])
    workspace.command(
        "hedge.confirm",
        execution["id"],
        {"cumulative_tons": 300, "event_id": "close-trade", "final": True},
        "reviewer",
    )
    hedge = workspace.get()["hedges"][0]
    workspace.command("hedge.allocate", hedge["id"], {"policy_id": "POL-001", "tons": 300})
    for policy_id in ("POL-001", "POL-002"):
        claim = workspace.claim(price=2300, policy_id=policy_id)
        workspace.command("claim.review", claim["id"], {"reason": "核定"}, "reviewer")
    workspace.command("reconciliation.run")
    assert (
        workspace.request(
            "project.close", "PRJ-001", {"reason": "尚未结清"}, "reviewer"
        ).status_code
        == 409
    )
    for payable in workspace.get()["payables"]:
        payment = workspace.command(
            "payment.create",
            payable["id"],
            {"amount": payable["amount"], "reference": f"close-pay-{payable['id']}"},
        )
        assert workspace.entity(payable["id"])["available_amount"] == 0
        workspace.command("payment.review", payment["id"], {"reason": "付款批准"}, "reviewer")
        workspace.command(
            "payment.receipt",
            payment["id"],
            {"outcome": "success", "event_id": f"paid-{payable['id']}", "reference": "bank"},
        )
    for recovery in workspace.get()["recoveries"]:
        workspace.command(
            "recovery.confirm", recovery["id"], {"reference": "confirmed"}, "reviewer"
        )
        workspace.command(
            "recovery.receipt",
            recovery["id"],
            {
                "amount": recovery["expected_amount"],
                "event_id": f"received-{recovery['id']}",
                "reference": "bank",
            },
        )
    for app_id in ("APP-003", "APP-004"):
        workspace.command("application.withdraw", app_id, {"reason": "本批不承接，撤回"})
    workspace.command("reconciliation.run")
    for difference in workspace.get()["reconciliations"]:
        workspace.command(
            "reconciliation.resolve",
            difference["id"],
            {"reason": "逐项核对业务与银行回执后关闭", "reference": "close-evidence"},
            "reviewer",
        )
    project = workspace.command(
        "project.close", "PRJ-001", {"reason": "全部事项已结清"}, "reviewer"
    )
    assert project["status"] == "closed"
    assert workspace.get()["tasks"] == []


def test_customer_payment_progress_includes_only_own_claim_cash(workspace):
    workspace.command(
        "reinsurance.allocate",
        "RI-001",
        {"policy_id": "POL-001", "reference": "ri-personal-progress"},
        "reviewer",
    )
    own_claim = workspace.claim(policy_id="POL-001")
    other_claim = workspace.claim(policy_id="POL-002")
    for claim in (own_claim, other_claim):
        workspace.command("claim.review", claim["id"], {"reason": "核定通过"}, "reviewer")
    own_payable = next(
        p for p in workspace.get()["payables"] if p.get("claim_id") == own_claim["id"]
    )
    payment = workspace.command(
        "payment.create", own_payable["id"], {"amount": 120000, "reference": "own-claim-payment"}
    )
    workspace.command("payment.review", payment["id"], {"reason": "付款批准"}, "reviewer")
    workspace.command(
        "payment.receipt",
        payment["id"],
        {
            "outcome": "partial",
            "cumulative_amount": 30000,
            "event_id": "own-partial",
            "reference": "bank",
        },
    )
    workspace.command(
        "payment.receipt",
        payment["id"],
        {"outcome": "unknown", "event_id": "own-unknown", "reference": "bank-query"},
    )
    ri_payable = next(
        p for p in workspace.get()["payables"] if p.get("kind") == "reinsurance_premium"
    )
    ri_payment = workspace.command(
        "payment.create",
        ri_payable["id"],
        {"amount": ri_payable["amount"], "reference": "ri-payment"},
    )
    workspace.command("payment.review", ri_payment["id"], {"reason": "分保保费批准"}, "reviewer")
    workspace.command(
        "payment.receipt",
        ri_payment["id"],
        {"outcome": "success", "event_id": "ri-paid", "reference": "bank"},
    )
    customer = workspace.get("customer")
    assert len(customer["claims"]) == 1
    claim = customer["claims"][0]
    assert claim["id"] == own_claim["id"]
    assert claim["paid_amount"] == 30000 and claim["unpaid_amount"] == 90000
    assert claim["in_transit_amount"] == 90000 and claim["payment_status"] == "unknown"
    assert claim["payment_progress"]["approved_amount"] == 120000
    assert customer["payables"] == [] and customer["payments"] == []
    assert other_claim["id"] not in str(customer)


def test_fixing_keeps_actual_snapshot_provenance_without_inventing_publication_time(
    workspace, monkeypatch
):
    from app.repositories import market_cache

    checksum = "b" * 64
    created_at = "2026-10-23T16:28:20.171278+00:00"
    dates = workspace.entity("POL-001")["fixing_dates"]
    monkeypatch.setattr(
        market_cache,
        "read_market_snapshot",
        lambda *args: (
            [{"tradeDate": day, "settlePrice": 2300} for day in dates],
            {
                "files": {"market.parquet": {"sha256": checksum}},
                "created_at": created_at,
                "requested_start": "2025-12-31",
                "requested_end": "2026-10-23",
            },
        ),
    )
    fixing = workspace.command("fixing.prepare", payload={"policy_id": "POL-001"})
    assert fixing["source_version"] == checksum
    assert fixing["source_snapshot"]["created_at"] == created_at
    for observation in fixing["observations"]:
        assert observation["published_at"] is None and observation["source_published_at"] is None
        assert observation["publication_time_precision"] == "unavailable"
        assert observation["snapshot_created_at"] == created_at


def test_human_decision_is_immutable_and_linked_snapshot_is_hidden_from_customer(workspace):
    from app.platform.store import transaction
    import json

    source_context = {
        "market_version": "reviewed-market-version",
        "casde_version": "CASDE-reviewed",
        "data_as_of": "2026-10-23",
        "source_status": {"weather": "not_connected"},
    }
    decision = workspace.command(
        "decision.record",
        payload={
            "region": "黑龙江省",
            "disposition": "review",
            "reason": "内部判断：补充区域信息后核保",
            "source_context": source_context,
            "product_id": "forged-product",
            "contract": "c9999",
        },
    )
    assert decision["product_id"] == "PROD-CORN-DEMO" and decision["contract"] == "c2701"
    assert decision["decision_type"] == "human_assessment"
    assert decision["source_context"] == source_context
    app = workspace.command(
        "application.create", payload=application_payload(decision_id=decision["id"])
    )
    assert app["decision_snapshot"] == decision
    workspace.command(
        "decision.record",
        payload={"region": "黑龙江省", "disposition": "proceed", "reason": "新增复核意见"},
        role="reviewer",
    )
    assert workspace.entity(app["id"])["decision_snapshot"] == decision
    assert workspace.request("decision.update", payload={"reason": "覆盖原意见"}).status_code == 422
    assert (
        workspace.request(
            "decision.record",
            payload={"region": "黑龙江省", "disposition": "proceed", "reason": "越权"},
            role="customer",
        ).status_code
        == 403
    )
    assert (
        workspace.request(
            "application.create",
            payload=application_payload(decision_id=decision["id"]),
            role="customer",
        ).status_code
        == 403
    )
    assert (
        workspace.request(
            "application.create", payload=application_payload(decision_id="DEC-NOT-IN-PROJECT")
        ).status_code
        == 404
    )
    customer = workspace.get("customer")
    visible_app = next(row for row in customer["applications"] if row["id"] == app["id"])
    assert "decision_snapshot" not in visible_app and "decision_id" not in visible_app
    assert customer["decision_records"] == []
    updated = workspace.command("application.update", app["id"], {"tons": 110}, role="customer")
    assert "decision_snapshot" not in updated and "decision_id" not in updated
    # An older persisted workspace without the new collection remains readable.
    with transaction() as connection:
        row = connection.execute(
            "SELECT document FROM platform_workspaces WHERE id='PRJ-001'"
        ).fetchone()
        legacy = json.loads(row["document"])
        legacy.pop("decision_records")
        connection.execute(
            "UPDATE platform_workspaces SET document=? WHERE id='PRJ-001'", (json.dumps(legacy),)
        )
    assert workspace.get()["decision_records"] == []
