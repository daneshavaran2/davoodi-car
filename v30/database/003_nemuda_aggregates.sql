-- Independent third-party aggregate price estimates; never insert into car_listings or price_estimates.
BEGIN;
CREATE TABLE IF NOT EXISTS aggregate_market_sources (
 code TEXT PRIMARY KEY, display_name TEXT NOT NULL, enabled BOOLEAN NOT NULL DEFAULT FALSE,
 last_attempt_at TIMESTAMPTZ, last_success_at TIMESTAMPTZ,
 last_error_code TEXT, last_error_detail TEXT, rows_saved INTEGER NOT NULL DEFAULT 0,
 last_source_computed_at TIMESTAMPTZ
);
INSERT INTO aggregate_market_sources(code,display_name,enabled) VALUES ('nemuda','نمودا',TRUE)
ON CONFLICT(code) DO NOTHING;
CREATE TABLE IF NOT EXISTS aggregate_vehicle_prices (
 source_code TEXT NOT NULL REFERENCES aggregate_market_sources(code),
 source_key TEXT NOT NULL,
 vehicle_catalog_id VARCHAR(32) NOT NULL REFERENCES vehicle_models(catalog_id),
 vehicle_label TEXT NOT NULL, trim_name TEXT NOT NULL DEFAULT '',
 model_year INTEGER NOT NULL, year_system TEXT NOT NULL,
 vehicle_condition TEXT NOT NULL DEFAULT 'used', body_condition TEXT NOT NULL DEFAULT 'healthy',
 low_toman BIGINT NOT NULL, median_toman BIGINT NOT NULL, high_toman BIGINT NOT NULL,
 data_points INTEGER NOT NULL, total_count INTEGER, coverage TEXT,
 window_days INTEGER, source_url TEXT NOT NULL,
 computed_at TIMESTAMPTZ NOT NULL, fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 PRIMARY KEY(source_code,source_key),
 CHECK(low_toman>0 AND low_toman<=median_toman AND median_toman<=high_toman),
 CHECK(data_points>=10), CHECK(year_system IN ('jalali','gregorian')),
 CHECK(vehicle_condition='used'), CHECK(body_condition='healthy')
);
CREATE INDEX IF NOT EXISTS idx_aggregate_vehicle_lookup ON aggregate_vehicle_prices(vehicle_catalog_id,model_year,computed_at DESC);
COMMIT;

