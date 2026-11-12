-- Starter SQL for DavoodiCar MVP; adapt using the project's migration framework.
-- PostgreSQL 13+. All monetary columns are integer TOMAN; NEVER mix with rials.
BEGIN;
CREATE TABLE IF NOT EXISTS vehicle_models (
  catalog_id VARCHAR(32) PRIMARY KEY,
  brand TEXT NOT NULL,
  model TEXT NOT NULL,
  display_name TEXT NOT NULL,
  search_text TEXT NOT NULL,
  brand_origin TEXT,
  supply_type TEXT,
  manufacturer_or_importer TEXT,
  body_type TEXT,
  fuel_type TEXT,
  production_start_year_ce_approx SMALLINT,
  production_end_year_ce_approx SMALLINT,
  start_year_shamsi_approx SMALLINT,
  market_status_as_listed TEXT,
  source_excel_row_numbers TEXT,
  requires_trim_year_and_condition_for_price BOOLEAN NOT NULL DEFAULT TRUE,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (brand, model)
);
CREATE INDEX IF NOT EXISTS idx_vehicle_models_search ON vehicle_models (search_text);

CREATE TABLE IF NOT EXISTS vehicle_aliases (
  id BIGSERIAL PRIMARY KEY,
  vehicle_catalog_id VARCHAR(32) NOT NULL REFERENCES vehicle_models(catalog_id) ON DELETE CASCADE,
  alias_text TEXT NOT NULL,
  alias_normalized TEXT NOT NULL,
  UNIQUE(vehicle_catalog_id, alias_normalized)
);
CREATE INDEX IF NOT EXISTS idx_vehicle_alias_norm ON vehicle_aliases(alias_normalized);

CREATE TABLE IF NOT EXISTS vehicle_variants (
  id BIGSERIAL PRIMARY KEY,
  vehicle_catalog_id VARCHAR(32) NOT NULL REFERENCES vehicle_models(catalog_id),
  trim_name TEXT NOT NULL DEFAULT '',
  transmission TEXT NOT NULL DEFAULT 'unknown',
  fuel_type TEXT NOT NULL DEFAULT 'unknown',
  canonical_key TEXT NOT NULL UNIQUE,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS data_sources (
  code TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  homepage TEXT,
  access_method TEXT, -- official_api / permitted_html / permitted_browser / manual
  access_verified_at TIMESTAMPTZ,
  enabled BOOLEAN NOT NULL DEFAULT FALSE,
  last_attempt_at TIMESTAMPTZ,
  last_success_at TIMESTAMPTZ,
  last_error_code TEXT,
  last_error_detail TEXT
);

CREATE TABLE IF NOT EXISTS fetch_runs (
  id BIGSERIAL PRIMARY KEY,
  source_code TEXT NOT NULL REFERENCES data_sources(code),
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'running' CHECK(status IN ('running','success','partial','failed','skipped')),
  error_code TEXT,
  error_detail TEXT,
  fetched_count INTEGER NOT NULL DEFAULT 0,
  valid_count INTEGER NOT NULL DEFAULT 0,
  rejected_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_fetch_runs_started ON fetch_runs (source_code, started_at DESC);

CREATE TABLE IF NOT EXISTS car_listings (
  id BIGSERIAL PRIMARY KEY,
  source_code TEXT NOT NULL REFERENCES data_sources(code),
  external_id TEXT,
  url TEXT NOT NULL,
  vehicle_catalog_id VARCHAR(32) REFERENCES vehicle_models(catalog_id),
  variant_id BIGINT REFERENCES vehicle_variants(id),
  model_year INTEGER,
  year_system TEXT CHECK(year_system IN ('jalali','gregorian')),
  vehicle_condition TEXT CHECK(vehicle_condition IN ('new','used','unknown')),
  mileage_km INTEGER CHECK(mileage_km >= 0),
  body_condition TEXT,
  transmission TEXT,
  city TEXT,
  price_toman BIGINT CHECK(price_toman > 0),
  price_kind TEXT NOT NULL DEFAULT 'asking' CHECK(price_kind IN ('asking','estimated','other')),
  published_at TIMESTAMPTZ,
  observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at TIMESTAMPTZ,
  listing_fingerprint TEXT,
  validation_status TEXT NOT NULL DEFAULT 'pending' CHECK(validation_status IN ('pending','valid','rejected','uncertain')),
  validation_reason TEXT,
  extraction_confidence NUMERIC(4,3),
  UNIQUE (source_code, external_id)
);
CREATE INDEX IF NOT EXISTS idx_car_listings_match ON car_listings(vehicle_catalog_id, model_year, year_system, vehicle_condition, validation_status);
CREATE INDEX IF NOT EXISTS idx_car_listings_seen ON car_listings(last_seen_at DESC);

-- One record per comparable car segment, updated atomically after a successful refresh.
-- segment_key is a stable hash generated from normalized model / trim / year / condition / mileage band / body / region.
CREATE TABLE IF NOT EXISTS price_estimates (
  segment_key TEXT PRIMARY KEY,
  vehicle_catalog_id VARCHAR(32) NOT NULL REFERENCES vehicle_models(catalog_id),
  variant_id BIGINT REFERENCES vehicle_variants(id),
  model_year INTEGER,
  year_system TEXT,
  vehicle_condition TEXT,
  mileage_band TEXT,
  body_condition TEXT,
  region TEXT,
  sample_count INTEGER NOT NULL DEFAULT 0,
  source_count INTEGER NOT NULL DEFAULT 0,
  low_toman BIGINT,
  median_toman BIGINT,
  high_toman BIGINT,
  confidence TEXT NOT NULL DEFAULT 'insufficient' CHECK(confidence IN ('high','medium','low','insufficient')),
  computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  freshest_listing_at TIMESTAMPTZ,
  stale_after TIMESTAMPTZ NOT NULL,
  calculation_version TEXT NOT NULL,
  CHECK(low_toman IS NULL OR high_toman IS NULL OR low_toman <= high_toman),
  CHECK(median_toman IS NULL OR low_toman IS NULL OR median_toman >= low_toman),
  CHECK(median_toman IS NULL OR high_toman IS NULL OR median_toman <= high_toman)
);
CREATE INDEX IF NOT EXISTS idx_estimate_match ON price_estimates(vehicle_catalog_id, model_year, year_system, vehicle_condition);

CREATE TABLE IF NOT EXISTS price_estimate_history (
  id BIGSERIAL PRIMARY KEY,
  segment_key TEXT NOT NULL,
  computed_at TIMESTAMPTZ NOT NULL,
  sample_count INTEGER NOT NULL,
  source_count INTEGER NOT NULL,
  low_toman BIGINT,
  median_toman BIGINT,
  high_toman BIGINT,
  confidence TEXT NOT NULL,
  calculation_version TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_price_history_key_time ON price_estimate_history(segment_key, computed_at DESC);
COMMIT;
