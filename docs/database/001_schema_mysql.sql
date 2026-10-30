-- Grain insurance platform; MySQL >= 8.0.16. Select the grain_guard database first.
-- Additive schema: no DROP, TRUNCATE or privilege changes.

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS schema_migrations (version VARCHAR(80) PRIMARY KEY, applied_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS platform_locks (name VARCHAR(40) PRIMARY KEY) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS platform_users (id VARCHAR(80) PRIMARY KEY, username VARCHAR(80) NOT NULL UNIQUE, name VARCHAR(200) NOT NULL, role VARCHAR(30) NOT NULL, salt CHAR(32) NOT NULL, password_hash CHAR(64) NOT NULL) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS platform_sessions (token_hash CHAR(64) PRIMARY KEY, user_id VARCHAR(80) NOT NULL, expires_at VARCHAR(40) NOT NULL, KEY idx_sessions_user(user_id), CONSTRAINT fk_sessions_user FOREIGN KEY(user_id) REFERENCES platform_users(id)) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS platform_workspaces (id VARCHAR(80) PRIMARY KEY, revision BIGINT NOT NULL, document JSON NOT NULL) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS platform_requests (actor_id VARCHAR(80) NOT NULL, request_id VARCHAR(150) NOT NULL, fingerprint CHAR(64) NOT NULL, response JSON NOT NULL, PRIMARY KEY(actor_id, request_id)) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS research_objects (id VARCHAR(80) PRIMARY KEY, kind VARCHAR(40) NOT NULL, payload JSON NOT NULL, sequence_no BIGINT UNSIGNED NOT NULL AUTO_INCREMENT UNIQUE, KEY idx_research_kind(kind,sequence_no)) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS research_test_exposures (signature CHAR(64) PRIMARY KEY, run_id VARCHAR(80) NOT NULL, exposed_at VARCHAR(40) NOT NULL) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS `insurance_projects` (
  `id` VARCHAR(180) PRIMARY KEY,
  `project_id` VARCHAR(80) NULL,
  `version` BIGINT NULL,
  `status` VARCHAR(40) NULL,
  `name` VARCHAR(200) NULL,
  `region` VARCHAR(200) NULL,
  `product_id` VARCHAR(80) NULL,
  `hedge_budget` DECIMAL(20,2) NULL,
  `origin_type` VARCHAR(20) NOT NULL,
  `seed_batch` VARCHAR(80) NULL,
  `payload` JSON NOT NULL,
  KEY `idx_project_status` (`project_id`,`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `insurance_applications` (
  `id` VARCHAR(180) PRIMARY KEY,
  `project_id` VARCHAR(80) NULL,
  `version` BIGINT NULL,
  `status` VARCHAR(40) NULL,
  `insured_name` VARCHAR(200) NULL,
  `customer_id` VARCHAR(80) NULL,
  `policy_id` VARCHAR(80) NULL,
  `tons` DECIMAL(20,2) NULL,
  `premium_due` DECIMAL(20,2) NULL,
  `premium_received` DECIMAL(20,2) NULL,
  `origin_type` VARCHAR(20) NOT NULL,
  `seed_batch` VARCHAR(80) NULL,
  `payload` JSON NOT NULL,
  KEY `idx_project_status` (`project_id`,`status`),
  KEY `idx_policy_id` (`policy_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `insurance_policies` (
  `id` VARCHAR(180) PRIMARY KEY,
  `project_id` VARCHAR(80) NULL,
  `version` BIGINT NULL,
  `status` VARCHAR(40) NULL,
  `application_id` VARCHAR(80) NULL,
  `policy_no` VARCHAR(100) NULL,
  `customer_id` VARCHAR(80) NULL,
  `contract` VARCHAR(30) NULL,
  `tons` DECIMAL(20,2) NULL,
  `guarantee_price` DECIMAL(20,2) NULL,
  `premium` DECIMAL(20,2) NULL,
  `origin_type` VARCHAR(20) NOT NULL,
  `seed_batch` VARCHAR(80) NULL,
  `payload` JSON NOT NULL,
  KEY `idx_project_status` (`project_id`,`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `application_batches` (
  `id` VARCHAR(180) PRIMARY KEY,
  `project_id` VARCHAR(80) NULL,
  `version` BIGINT NULL,
  `status` VARCHAR(40) NULL,
  `created_by` VARCHAR(80) NULL,
  `row_count` INT NULL,
  `error_count` INT NULL,
  `origin_type` VARCHAR(20) NOT NULL,
  `seed_batch` VARCHAR(80) NULL,
  `payload` JSON NOT NULL,
  KEY `idx_project_status` (`project_id`,`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `issuance_requests` (
  `id` VARCHAR(180) PRIMARY KEY,
  `project_id` VARCHAR(80) NULL,
  `version` BIGINT NULL,
  `status` VARCHAR(40) NULL,
  `application_id` VARCHAR(80) NULL,
  `external_no` VARCHAR(100) NULL,
  `origin_type` VARCHAR(20) NOT NULL,
  `seed_batch` VARCHAR(80) NULL,
  `payload` JSON NOT NULL,
  KEY `idx_project_status` (`project_id`,`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `reinsurance_contracts` (
  `id` VARCHAR(180) PRIMARY KEY,
  `project_id` VARCHAR(80) NULL,
  `version` BIGINT NULL,
  `status` VARCHAR(40) NULL,
  `contract_no` VARCHAR(100) NULL,
  `counterparty` VARCHAR(200) NULL,
  `ratio` DECIMAL(10,6) NULL,
  `limit` DECIMAL(20,2) NULL,
  `origin_type` VARCHAR(20) NOT NULL,
  `seed_batch` VARCHAR(80) NULL,
  `payload` JSON NOT NULL,
  KEY `idx_project_status` (`project_id`,`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `reinsurance_allocations` (
  `id` VARCHAR(180) PRIMARY KEY,
  `project_id` VARCHAR(80) NULL,
  `version` BIGINT NULL,
  `status` VARCHAR(40) NULL,
  `policy_id` VARCHAR(80) NULL,
  `reinsurance_id` VARCHAR(80) NULL,
  `ratio` DECIMAL(10,6) NULL,
  `origin_type` VARCHAR(20) NOT NULL,
  `seed_batch` VARCHAR(80) NULL,
  `payload` JSON NOT NULL,
  KEY `idx_project_status` (`project_id`,`status`),
  KEY `idx_policy_id` (`policy_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `hedge_plans` (
  `id` VARCHAR(180) PRIMARY KEY,
  `project_id` VARCHAR(80) NULL,
  `version` BIGINT NULL,
  `status` VARCHAR(40) NULL,
  `name` VARCHAR(200) NULL,
  `contract` VARCHAR(30) NULL,
  `tool` VARCHAR(40) NULL,
  `tons` DECIMAL(20,2) NULL,
  `strike_price` DECIMAL(20,2) NULL,
  `budget` DECIMAL(20,2) NULL,
  `origin_type` VARCHAR(20) NOT NULL,
  `seed_batch` VARCHAR(80) NULL,
  `payload` JSON NOT NULL,
  KEY `idx_project_status` (`project_id`,`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `trade_orders` (
  `id` VARCHAR(180) PRIMARY KEY,
  `project_id` VARCHAR(80) NULL,
  `version` BIGINT NULL,
  `status` VARCHAR(40) NULL,
  `plan_id` VARCHAR(80) NULL,
  `external_no` VARCHAR(100) NULL,
  `requested_tons` DECIMAL(20,2) NULL,
  `confirmed_tons` DECIMAL(20,2) NULL,
  `reserved_tons` DECIMAL(20,2) NULL,
  `origin_type` VARCHAR(20) NOT NULL,
  `seed_batch` VARCHAR(80) NULL,
  `payload` JSON NOT NULL,
  KEY `idx_project_status` (`project_id`,`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `hedge_contracts` (
  `id` VARCHAR(180) PRIMARY KEY,
  `project_id` VARCHAR(80) NULL,
  `version` BIGINT NULL,
  `status` VARCHAR(40) NULL,
  `execution_id` VARCHAR(80) NULL,
  `tons` DECIMAL(20,2) NULL,
  `strike_price` DECIMAL(20,2) NULL,
  `total_premium` DECIMAL(20,2) NULL,
  `origin_type` VARCHAR(20) NOT NULL,
  `seed_batch` VARCHAR(80) NULL,
  `payload` JSON NOT NULL,
  KEY `idx_project_status` (`project_id`,`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `hedge_allocations` (
  `id` VARCHAR(180) PRIMARY KEY,
  `project_id` VARCHAR(80) NULL,
  `version` BIGINT NULL,
  `status` VARCHAR(40) NULL,
  `policy_id` VARCHAR(80) NULL,
  `hedge_id` VARCHAR(80) NULL,
  `tons` DECIMAL(20,2) NULL,
  `origin_type` VARCHAR(20) NOT NULL,
  `seed_batch` VARCHAR(80) NULL,
  `payload` JSON NOT NULL,
  KEY `idx_project_status` (`project_id`,`status`),
  KEY `idx_policy_id` (`policy_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `price_fixings` (
  `id` VARCHAR(180) PRIMARY KEY,
  `project_id` VARCHAR(80) NULL,
  `version` BIGINT NULL,
  `status` VARCHAR(40) NULL,
  `policy_id` VARCHAR(80) NULL,
  `contract` VARCHAR(30) NULL,
  `source_version` VARCHAR(150) NULL,
  `average_price` DECIMAL(20,2) NULL,
  `actual_count` INT NULL,
  `expected_count` INT NULL,
  `origin_type` VARCHAR(20) NOT NULL,
  `seed_batch` VARCHAR(80) NULL,
  `payload` JSON NOT NULL,
  KEY `idx_project_status` (`project_id`,`status`),
  KEY `idx_policy_id` (`policy_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `insurance_claims` (
  `id` VARCHAR(180) PRIMARY KEY,
  `project_id` VARCHAR(80) NULL,
  `version` BIGINT NULL,
  `status` VARCHAR(40) NULL,
  `policy_id` VARCHAR(80) NULL,
  `fixing_id` VARCHAR(80) NULL,
  `rule_amount` DECIMAL(20,2) NULL,
  `assessed_amount` DECIMAL(20,2) NULL,
  `approved_amount` DECIMAL(20,2) NULL,
  `origin_type` VARCHAR(20) NOT NULL,
  `seed_batch` VARCHAR(80) NULL,
  `payload` JSON NOT NULL,
  KEY `idx_project_status` (`project_id`,`status`),
  KEY `idx_policy_id` (`policy_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `cash_payables` (
  `id` VARCHAR(180) PRIMARY KEY,
  `project_id` VARCHAR(80) NULL,
  `version` BIGINT NULL,
  `status` VARCHAR(40) NULL,
  `kind` VARCHAR(40) NULL,
  `source_id` VARCHAR(80) NULL,
  `counterparty` VARCHAR(200) NULL,
  `amount` DECIMAL(20,2) NULL,
  `paid_amount` DECIMAL(20,2) NULL,
  `reserved_amount` DECIMAL(20,2) NULL,
  `origin_type` VARCHAR(20) NOT NULL,
  `seed_batch` VARCHAR(80) NULL,
  `payload` JSON NOT NULL,
  KEY `idx_project_status` (`project_id`,`status`),
  KEY `idx_kind` (`kind`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `cash_payments` (
  `id` VARCHAR(180) PRIMARY KEY,
  `project_id` VARCHAR(80) NULL,
  `version` BIGINT NULL,
  `status` VARCHAR(40) NULL,
  `payable_id` VARCHAR(80) NULL,
  `kind` VARCHAR(40) NULL,
  `amount` DECIMAL(20,2) NULL,
  `paid_amount` DECIMAL(20,2) NULL,
  `reserved_amount` DECIMAL(20,2) NULL,
  `origin_type` VARCHAR(20) NOT NULL,
  `seed_batch` VARCHAR(80) NULL,
  `payload` JSON NOT NULL,
  KEY `idx_project_status` (`project_id`,`status`),
  KEY `idx_payable_id` (`payable_id`),
  KEY `idx_kind` (`kind`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `risk_recoveries` (
  `id` VARCHAR(180) PRIMARY KEY,
  `project_id` VARCHAR(80) NULL,
  `version` BIGINT NULL,
  `status` VARCHAR(40) NULL,
  `claim_id` VARCHAR(80) NULL,
  `kind` VARCHAR(40) NULL,
  `expected_amount` DECIMAL(20,2) NULL,
  `confirmed_amount` DECIMAL(20,2) NULL,
  `received_amount` DECIMAL(20,2) NULL,
  `origin_type` VARCHAR(20) NOT NULL,
  `seed_batch` VARCHAR(80) NULL,
  `payload` JSON NOT NULL,
  KEY `idx_project_status` (`project_id`,`status`),
  KEY `idx_kind` (`kind`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `reconciliation_items` (
  `id` VARCHAR(180) PRIMARY KEY,
  `project_id` VARCHAR(80) NULL,
  `version` BIGINT NULL,
  `status` VARCHAR(40) NULL,
  `target_id` VARCHAR(80) NULL,
  `type` VARCHAR(80) NULL,
  `amount` DECIMAL(20,2) NULL,
  `origin_type` VARCHAR(20) NOT NULL,
  `seed_batch` VARCHAR(80) NULL,
  `payload` JSON NOT NULL,
  KEY `idx_project_status` (`project_id`,`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `business_audit_events` (
  `id` VARCHAR(180) PRIMARY KEY,
  `project_id` VARCHAR(80) NULL,
  `version` BIGINT NULL,
  `status` VARCHAR(40) NULL,
  `command` VARCHAR(100) NULL,
  `actor` VARCHAR(80) NULL,
  `target_id` VARCHAR(80) NULL,
  `request_id` VARCHAR(150) NULL,
  `origin_type` VARCHAR(20) NOT NULL,
  `seed_batch` VARCHAR(80) NULL,
  `payload` JSON NOT NULL,
  KEY `idx_project_status` (`project_id`,`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `premium_adjustments` (
  `id` VARCHAR(180) PRIMARY KEY,
  `project_id` VARCHAR(80) NULL,
  `version` BIGINT NULL,
  `status` VARCHAR(40) NULL,
  `policy_id` VARCHAR(80) NULL,
  `amount` DECIMAL(20,2) NULL,
  `received_amount` DECIMAL(20,2) NULL,
  `origin_type` VARCHAR(20) NOT NULL,
  `seed_batch` VARCHAR(80) NULL,
  `payload` JSON NOT NULL,
  KEY `idx_project_status` (`project_id`,`status`),
  KEY `idx_policy_id` (`policy_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `business_decisions` (
  `id` VARCHAR(180) PRIMARY KEY,
  `project_id` VARCHAR(80) NULL,
  `version` BIGINT NULL,
  `status` VARCHAR(40) NULL,
  `region` VARCHAR(200) NULL,
  `disposition` VARCHAR(40) NULL,
  `created_by` VARCHAR(80) NULL,
  `origin_type` VARCHAR(20) NOT NULL,
  `seed_batch` VARCHAR(80) NULL,
  `payload` JSON NOT NULL,
  KEY `idx_project_status` (`project_id`,`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `insurance_products` (
  `id` VARCHAR(180) PRIMARY KEY,
  `project_id` VARCHAR(80) NULL,
  `rule_version` VARCHAR(80) NULL,
  `name` VARCHAR(200) NULL,
  `contract` VARCHAR(30) NULL,
  `guarantee_price` DECIMAL(20,2) NULL,
  `premium_per_ton` DECIMAL(20,2) NULL,
  `origin_type` VARCHAR(20) NOT NULL,
  `seed_batch` VARCHAR(80) NULL,
  `payload` JSON NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `data_sources` (
  `id` VARCHAR(180) PRIMARY KEY,
  `name` VARCHAR(200) NULL,
  `status` VARCHAR(40) NULL,
  `origin_type` VARCHAR(20) NOT NULL,
  `seed_batch` VARCHAR(80) NULL,
  `payload` JSON NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `data_series` (
  `id` VARCHAR(180) PRIMARY KEY,
  `source_id` VARCHAR(80) NULL,
  `name` VARCHAR(200) NULL,
  `kind` VARCHAR(40) NULL,
  `unit` VARCHAR(30) NULL,
  `origin_type` VARCHAR(20) NOT NULL,
  `seed_batch` VARCHAR(80) NULL,
  `payload` JSON NOT NULL,
  KEY `idx_kind` (`kind`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `data_observations` (
  `id` VARCHAR(180) PRIMARY KEY,
  `series_id` VARCHAR(180) NULL,
  `observation_date` DATE NULL,
  `value` DECIMAL(24,8) NULL,
  `published_at` VARCHAR(40) NULL,
  `origin_type` VARCHAR(20) NOT NULL,
  `seed_batch` VARCHAR(80) NULL,
  `payload` JSON NOT NULL,
  KEY `idx_series_id` (`series_id`),
  KEY `idx_series_date` (`series_id`,`observation_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `market_contracts` (
  `id` VARCHAR(180) PRIMARY KEY,
  `ticker` VARCHAR(30) NULL,
  `exchange_code` VARCHAR(20) NULL,
  `last_trade_date` DATE NULL,
  `origin_type` VARCHAR(20) NOT NULL,
  `seed_batch` VARCHAR(80) NULL,
  `payload` JSON NOT NULL,
  KEY `idx_ticker` (`ticker`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `market_daily_bars` (
  `id` VARCHAR(180) PRIMARY KEY,
  `ticker` VARCHAR(30) NULL,
  `trade_date` DATE NULL,
  `open_price` DECIMAL(20,2) NULL,
  `high_price` DECIMAL(20,2) NULL,
  `low_price` DECIMAL(20,2) NULL,
  `close_price` DECIMAL(20,2) NULL,
  `settle_price` DECIMAL(20,2) NULL,
  `volume` BIGINT NULL,
  `open_interest` BIGINT NULL,
  `origin_type` VARCHAR(20) NOT NULL,
  `seed_batch` VARCHAR(80) NULL,
  `payload` JSON NOT NULL,
  KEY `idx_ticker` (`ticker`),
  UNIQUE KEY `uq_contract_date` (`ticker`,`trade_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `supply_balances` (
  `id` VARCHAR(180) PRIMARY KEY,
  `country_code` VARCHAR(8) NULL,
  `marketing_year` VARCHAR(12) NULL,
  `production` DECIMAL(24,2) NULL,
  `domestic_consumption` DECIMAL(24,2) NULL,
  `imports_my` DECIMAL(24,2) NULL,
  `exports_my` DECIMAL(24,2) NULL,
  `ending_stocks` DECIMAL(24,2) NULL,
  `origin_type` VARCHAR(20) NOT NULL,
  `seed_batch` VARCHAR(80) NULL,
  `payload` JSON NOT NULL,
  KEY `idx_country_code` (`country_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `trade_monthly` (
  `id` VARCHAR(180) PRIMARY KEY,
  `reporter_code` VARCHAR(8) NULL,
  `partner_code` VARCHAR(8) NULL,
  `flow` VARCHAR(12) NULL,
  `period_start` DATE NULL,
  `quantity_tons` DECIMAL(24,2) NULL,
  `hs_code` VARCHAR(12) NULL,
  `origin_type` VARCHAR(20) NOT NULL,
  `seed_batch` VARCHAR(80) NULL,
  `payload` JSON NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `environment_daily` (
  `id` VARCHAR(180) PRIMARY KEY,
  `project_id` VARCHAR(80) NULL,
  `region_code` VARCHAR(12) NULL,
  `observation_date` DATE NULL,
  `temperature_c` DECIMAL(8,2) NULL,
  `rainfall_mm` DECIMAL(10,2) NULL,
  `wind_speed_ms` DECIMAL(8,2) NULL,
  `soil_water_content` DECIMAL(8,6) NULL,
  `soil_saturation` DECIMAL(8,6) NULL,
  `origin_type` VARCHAR(20) NOT NULL,
  `seed_batch` VARCHAR(80) NULL,
  `payload` JSON NOT NULL,
  UNIQUE KEY `uq_region_date` (`region_code`,`observation_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `hazard_assessments` (
  `id` VARCHAR(180) PRIMARY KEY,
  `project_id` VARCHAR(80) NULL,
  `region_code` VARCHAR(12) NULL,
  `hazard_type` VARCHAR(30) NULL,
  `as_of` VARCHAR(40) NULL,
  `valid_until` VARCHAR(40) NULL,
  `risk_level` VARCHAR(20) NULL,
  `probability` DECIMAL(8,6) NULL,
  `model_id` VARCHAR(80) NULL,
  `origin_type` VARCHAR(20) NOT NULL,
  `seed_batch` VARCHAR(80) NULL,
  `payload` JSON NOT NULL,
  KEY `idx_hazard_type` (`hazard_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `policy_events` (
  `id` VARCHAR(180) PRIMARY KEY,
  `project_id` VARCHAR(80) NULL,
  `country_code` VARCHAR(8) NULL,
  `category` VARCHAR(40) NULL,
  `published_at` VARCHAR(40) NULL,
  `effective_at` VARCHAR(40) NULL,
  `title` VARCHAR(250) NULL,
  `origin_type` VARCHAR(20) NOT NULL,
  `seed_batch` VARCHAR(80) NULL,
  `payload` JSON NOT NULL,
  KEY `idx_country_code` (`country_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO schema_migrations(version) VALUES ('grain-platform-v3');

INSERT IGNORE INTO platform_locks(name) VALUES ('business'),('research'),('catalog');
