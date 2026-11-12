-- Safe, additive migration on top of the supplied handoff schema (PostgreSQL 13+).
BEGIN;
ALTER TABLE car_listings ADD COLUMN IF NOT EXISTS title TEXT;
ALTER TABLE car_listings ADD COLUMN IF NOT EXISTS fuel_type TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE car_listings ADD COLUMN IF NOT EXISTS trim_name TEXT;
ALTER TABLE car_listings ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS last_error_code TEXT;
CREATE TABLE IF NOT EXISTS scheduler_runs (
  scheduled_for TIMESTAMPTZ PRIMARY KEY,
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'running',
  source_ok INTEGER NOT NULL DEFAULT 0,
  source_failed INTEGER NOT NULL DEFAULT 0,
  error_summary TEXT
);
CREATE TABLE IF NOT EXISTS price_samples (
  segment_key TEXT NOT NULL REFERENCES price_estimates(segment_key) ON DELETE CASCADE,
  source_code TEXT NOT NULL,
  external_id TEXT NOT NULL,
  price_toman BIGINT NOT NULL,
  url TEXT NOT NULL,
  observed_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (segment_key,source_code,external_id)
);
CREATE TABLE IF NOT EXISTS refresh_requests (
  id BIGSERIAL PRIMARY KEY,
  vehicle_catalog_id VARCHAR(32) REFERENCES vehicle_models(catalog_id),
  model_year INTEGER,
  trim_name TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  status TEXT NOT NULL DEFAULT 'pending',
  completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_refresh_pending ON refresh_requests(status,created_at);
CREATE INDEX IF NOT EXISTS idx_price_samples_segment ON price_samples(segment_key);
CREATE INDEX IF NOT EXISTS idx_listing_current ON car_listings(validation_status,expires_at,vehicle_catalog_id,model_year);
INSERT INTO data_sources(code,name,homepage,access_method,enabled) VALUES
 ('divar','دیوار','https://divar.ir','official_api',FALSE),
 ('bama','باما','https://bama.ir','official_api',FALSE),
 ('sheypoor','شیپور','https://www.sheypoor.com','official_api',FALSE),
 ('hamrah','همراه مکانیک','https://www.hamrah-mechanic.com','official_api',FALSE),
 ('karnameh','کارنامه','https://karnameh.com','official_api',FALSE),
 ('khodro45','خودرو۴۵','https://khodro45.com','official_api',FALSE)
ON CONFLICT(code) DO NOTHING;
COMMIT;
