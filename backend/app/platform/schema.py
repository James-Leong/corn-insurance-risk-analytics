"""MySQL 8 schema and the common relational projections used by both stores."""

from __future__ import annotations

import json

SCHEMA_VERSION = "grain-platform-v3"
SEED_BATCH = "corn-initial-20261029-v3"
# The aggregate remains the transactional authority; these rows are atomic query projections.
BUSINESS_TABLES = {
    "projects": (
        "insurance_projects",
        {
            "name": "VARCHAR(200)",
            "region": "VARCHAR(200)",
            "product_id": "VARCHAR(80)",
            "hedge_budget": "DECIMAL(20,2)",
        },
    ),
    "applications": (
        "insurance_applications",
        {
            "insured_name": "VARCHAR(200)",
            "customer_id": "VARCHAR(80)",
            "policy_id": "VARCHAR(80)",
            "tons": "DECIMAL(20,2)",
            "premium_due": "DECIMAL(20,2)",
            "premium_received": "DECIMAL(20,2)",
        },
    ),
    "policies": (
        "insurance_policies",
        {
            "application_id": "VARCHAR(80)",
            "policy_no": "VARCHAR(100)",
            "customer_id": "VARCHAR(80)",
            "contract": "VARCHAR(30)",
            "tons": "DECIMAL(20,2)",
            "guarantee_price": "DECIMAL(20,2)",
            "premium": "DECIMAL(20,2)",
        },
    ),
    "batches": (
        "application_batches",
        {"created_by": "VARCHAR(80)", "row_count": "INT", "error_count": "INT"},
    ),
    "issuance_requests": (
        "issuance_requests",
        {"application_id": "VARCHAR(80)", "external_no": "VARCHAR(100)"},
    ),
    "reinsurance": (
        "reinsurance_contracts",
        {
            "contract_no": "VARCHAR(100)",
            "counterparty": "VARCHAR(200)",
            "ratio": "DECIMAL(10,6)",
            "limit": "DECIMAL(20,2)",
        },
    ),
    "reinsurance_allocations": (
        "reinsurance_allocations",
        {"policy_id": "VARCHAR(80)", "reinsurance_id": "VARCHAR(80)", "ratio": "DECIMAL(10,6)"},
    ),
    "plans": (
        "hedge_plans",
        {
            "name": "VARCHAR(200)",
            "contract": "VARCHAR(30)",
            "tool": "VARCHAR(40)",
            "tons": "DECIMAL(20,2)",
            "strike_price": "DECIMAL(20,2)",
            "budget": "DECIMAL(20,2)",
        },
    ),
    "executions": (
        "trade_orders",
        {
            "plan_id": "VARCHAR(80)",
            "external_no": "VARCHAR(100)",
            "requested_tons": "DECIMAL(20,2)",
            "confirmed_tons": "DECIMAL(20,2)",
            "reserved_tons": "DECIMAL(20,2)",
        },
    ),
    "hedges": (
        "hedge_contracts",
        {
            "execution_id": "VARCHAR(80)",
            "tons": "DECIMAL(20,2)",
            "strike_price": "DECIMAL(20,2)",
            "total_premium": "DECIMAL(20,2)",
        },
    ),
    "allocations": (
        "hedge_allocations",
        {"policy_id": "VARCHAR(80)", "hedge_id": "VARCHAR(80)", "tons": "DECIMAL(20,2)"},
    ),
    "fixings": (
        "price_fixings",
        {
            "policy_id": "VARCHAR(80)",
            "contract": "VARCHAR(30)",
            "source_version": "VARCHAR(150)",
            "average_price": "DECIMAL(20,2)",
            "actual_count": "INT",
            "expected_count": "INT",
        },
    ),
    "claims": (
        "insurance_claims",
        {
            "policy_id": "VARCHAR(80)",
            "fixing_id": "VARCHAR(80)",
            "rule_amount": "DECIMAL(20,2)",
            "assessed_amount": "DECIMAL(20,2)",
            "approved_amount": "DECIMAL(20,2)",
        },
    ),
    "payables": (
        "cash_payables",
        {
            "kind": "VARCHAR(40)",
            "source_id": "VARCHAR(80)",
            "counterparty": "VARCHAR(200)",
            "amount": "DECIMAL(20,2)",
            "paid_amount": "DECIMAL(20,2)",
            "reserved_amount": "DECIMAL(20,2)",
        },
    ),
    "payments": (
        "cash_payments",
        {
            "payable_id": "VARCHAR(80)",
            "kind": "VARCHAR(40)",
            "amount": "DECIMAL(20,2)",
            "paid_amount": "DECIMAL(20,2)",
            "reserved_amount": "DECIMAL(20,2)",
        },
    ),
    "recoveries": (
        "risk_recoveries",
        {
            "claim_id": "VARCHAR(80)",
            "kind": "VARCHAR(40)",
            "expected_amount": "DECIMAL(20,2)",
            "confirmed_amount": "DECIMAL(20,2)",
            "received_amount": "DECIMAL(20,2)",
        },
    ),
    "reconciliations": (
        "reconciliation_items",
        {"target_id": "VARCHAR(80)", "type": "VARCHAR(80)", "amount": "DECIMAL(20,2)"},
    ),
    "audit_events": (
        "business_audit_events",
        {
            "command": "VARCHAR(100)",
            "actor": "VARCHAR(80)",
            "target_id": "VARCHAR(80)",
            "request_id": "VARCHAR(150)",
        },
    ),
    "premium_adjustments": (
        "premium_adjustments",
        {"policy_id": "VARCHAR(80)", "amount": "DECIMAL(20,2)", "received_amount": "DECIMAL(20,2)"},
    ),
    "decision_records": (
        "business_decisions",
        {"region": "VARCHAR(200)", "disposition": "VARCHAR(40)", "created_by": "VARCHAR(80)"},
    ),
}
DATA_TABLES = {
    "data_sources": {"name": "VARCHAR(200)", "status": "VARCHAR(40)"},
    "data_series": {
        "source_id": "VARCHAR(80)",
        "name": "VARCHAR(200)",
        "kind": "VARCHAR(40)",
        "unit": "VARCHAR(30)",
    },
    "data_observations": {
        "series_id": "VARCHAR(180)",
        "observation_date": "DATE",
        "value": "DECIMAL(24,8)",
        "published_at": "VARCHAR(40)",
    },
    "market_contracts": {
        "ticker": "VARCHAR(30)",
        "exchange_code": "VARCHAR(20)",
        "last_trade_date": "DATE",
    },
    "market_daily_bars": {
        "ticker": "VARCHAR(30)",
        "trade_date": "DATE",
        "open_price": "DECIMAL(20,2)",
        "high_price": "DECIMAL(20,2)",
        "low_price": "DECIMAL(20,2)",
        "close_price": "DECIMAL(20,2)",
        "settle_price": "DECIMAL(20,2)",
        "volume": "BIGINT",
        "open_interest": "BIGINT",
    },
    "supply_balances": {
        "country_code": "VARCHAR(8)",
        "marketing_year": "VARCHAR(12)",
        "production": "DECIMAL(24,2)",
        "domestic_consumption": "DECIMAL(24,2)",
        "imports_my": "DECIMAL(24,2)",
        "exports_my": "DECIMAL(24,2)",
        "ending_stocks": "DECIMAL(24,2)",
    },
    "trade_monthly": {
        "reporter_code": "VARCHAR(8)",
        "partner_code": "VARCHAR(8)",
        "flow": "VARCHAR(12)",
        "period_start": "DATE",
        "quantity_tons": "DECIMAL(24,2)",
        "hs_code": "VARCHAR(12)",
    },
    "environment_daily": {
        "project_id": "VARCHAR(80)",
        "region_code": "VARCHAR(12)",
        "observation_date": "DATE",
        "temperature_c": "DECIMAL(8,2)",
        "rainfall_mm": "DECIMAL(10,2)",
        "wind_speed_ms": "DECIMAL(8,2)",
        "soil_water_content": "DECIMAL(8,6)",
        "soil_saturation": "DECIMAL(8,6)",
    },
    "hazard_assessments": {
        "project_id": "VARCHAR(80)",
        "region_code": "VARCHAR(12)",
        "hazard_type": "VARCHAR(30)",
        "as_of": "VARCHAR(40)",
        "valid_until": "VARCHAR(40)",
        "risk_level": "VARCHAR(20)",
        "probability": "DECIMAL(8,6)",
        "model_id": "VARCHAR(80)",
    },
    "policy_events": {
        "project_id": "VARCHAR(80)",
        "country_code": "VARCHAR(8)",
        "category": "VARCHAR(40)",
        "published_at": "VARCHAR(40)",
        "effective_at": "VARCHAR(40)",
        "title": "VARCHAR(250)",
    },
}


def mysql_ddl() -> str:
    statements = [
        "SET NAMES utf8mb4;",
        "CREATE TABLE IF NOT EXISTS schema_migrations (version VARCHAR(80) PRIMARY KEY, applied_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)) ENGINE=InnoDB;",
        "CREATE TABLE IF NOT EXISTS platform_locks (name VARCHAR(40) PRIMARY KEY) ENGINE=InnoDB;",
        "CREATE TABLE IF NOT EXISTS platform_users (id VARCHAR(80) PRIMARY KEY, username VARCHAR(80) NOT NULL UNIQUE, name VARCHAR(200) NOT NULL, role VARCHAR(30) NOT NULL, salt CHAR(32) NOT NULL, password_hash CHAR(64) NOT NULL) ENGINE=InnoDB;",
        "CREATE TABLE IF NOT EXISTS platform_sessions (token_hash CHAR(64) PRIMARY KEY, user_id VARCHAR(80) NOT NULL, expires_at VARCHAR(40) NOT NULL, KEY idx_sessions_user(user_id), CONSTRAINT fk_sessions_user FOREIGN KEY(user_id) REFERENCES platform_users(id)) ENGINE=InnoDB;",
        "CREATE TABLE IF NOT EXISTS platform_workspaces (id VARCHAR(80) PRIMARY KEY, revision BIGINT NOT NULL, document JSON NOT NULL) ENGINE=InnoDB;",
        "CREATE TABLE IF NOT EXISTS platform_requests (actor_id VARCHAR(80) NOT NULL, request_id VARCHAR(150) NOT NULL, fingerprint CHAR(64) NOT NULL, response JSON NOT NULL, PRIMARY KEY(actor_id, request_id)) ENGINE=InnoDB;",
        "CREATE TABLE IF NOT EXISTS research_objects (id VARCHAR(80) PRIMARY KEY, kind VARCHAR(40) NOT NULL, payload JSON NOT NULL, sequence_no BIGINT UNSIGNED NOT NULL AUTO_INCREMENT UNIQUE, KEY idx_research_kind(kind,sequence_no)) ENGINE=InnoDB;",
        "CREATE TABLE IF NOT EXISTS research_test_exposures (signature CHAR(64) PRIMARY KEY, run_id VARCHAR(80) NOT NULL, exposed_at VARCHAR(40) NOT NULL) ENGINE=InnoDB;",
    ]
    for name, fields in projection_tables().items():
        lines = [
            "`id` VARCHAR(180) PRIMARY KEY",
            *[f"`{key}` {kind} NULL" for key, kind in fields.items()],
            "`origin_type` VARCHAR(20) NOT NULL",
            "`seed_batch` VARCHAR(80) NULL",
            "`payload` JSON NOT NULL",
        ]
        if "project_id" in fields and "status" in fields:
            lines.append("KEY `idx_project_status` (`project_id`,`status`)")
        for key in (
            "series_id",
            "ticker",
            "policy_id",
            "payable_id",
            "hazard_type",
            "country_code",
            "kind",
        ):
            if key in fields:
                lines.append(f"KEY `idx_{key}` (`{key}`)")
        if name == "data_observations":
            lines.append("KEY `idx_series_date` (`series_id`,`observation_date`)")
        if name == "market_daily_bars":
            lines.append("UNIQUE KEY `uq_contract_date` (`ticker`,`trade_date`)")
        if name == "environment_daily":
            lines.append("UNIQUE KEY `uq_region_date` (`region_code`,`observation_date`)")
        statements.append(
            f"CREATE TABLE IF NOT EXISTS `{name}` (\n  "
            + ",\n  ".join(lines)
            + "\n) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;"
        )
    # Only the DDL owner writes schema readiness; the application never performs DDL.
    statements.append(f"INSERT IGNORE INTO schema_migrations(version) VALUES ('{SCHEMA_VERSION}');")
    statements.append(
        "INSERT IGNORE INTO platform_locks(name) VALUES ('business'),('research'),('catalog');"
    )
    return (
        "-- Grain insurance platform; MySQL >= 8.0.16. Select the grain_guard database first.\n-- Additive schema: no DROP, TRUNCATE or privilege changes.\n\n"
        + "\n\n".join(statements)
        + "\n"
    )


def projection_tables():
    result = {
        name: {"project_id": "VARCHAR(80)", "version": "BIGINT", "status": "VARCHAR(40)", **fields}
        for name, fields in BUSINESS_TABLES.values()
    }
    result["insurance_products"] = {
        "project_id": "VARCHAR(80)",
        "rule_version": "VARCHAR(80)",
        "name": "VARCHAR(200)",
        "contract": "VARCHAR(30)",
        "guarantee_price": "DECIMAL(20,2)",
        "premium_per_ton": "DECIMAL(20,2)",
    }
    return {**result, **DATA_TABLES}


def row_values(table, payload, *, project_id=None):
    fields = projection_tables()[table]
    values = {key: payload.get(key) for key in fields}
    if project_id is not None:
        values["project_id"] = project_id
    if table == "insurance_products":
        values["rule_version"] = str(payload.get("version", ""))
    return {
        "id": payload["id"],
        **values,
        "origin_type": payload.get("origin_type", "synthetic"),
        "seed_batch": payload.get("seed_batch"),
        "payload": json.dumps(payload, ensure_ascii=False, allow_nan=False),
    }


def workspace_rows(state):
    product = {**state["product"], "seed_batch": state.get("seed_batch")}
    yield "insurance_products", row_values("insurance_products", product, project_id=state["id"])
    for collection, (table, _) in BUSINESS_TABLES.items():
        for payload in state.get(collection, []):
            yield (
                table,
                row_values(
                    table,
                    {**payload, "seed_batch": payload.get("seed_batch", state.get("seed_batch"))},
                    project_id=state["id"],
                ),
            )
