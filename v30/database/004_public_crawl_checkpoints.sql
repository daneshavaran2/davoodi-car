-- Durable checkpoint for bounded, resumable multi-page public car crawling.
-- This does not alter or delete any historical price snapshots.
BEGIN;
CREATE TABLE IF NOT EXISTS public_crawl_checkpoints (
  source_code TEXT PRIMARY KEY REFERENCES data_sources(code) ON DELETE CASCADE,
  catalog_index INTEGER NOT NULL DEFAULT 0 CHECK(catalog_index>=0),
  vehicle_catalog_id VARCHAR(32) REFERENCES vehicle_models(catalog_id) ON DELETE SET NULL,
  next_url TEXT,
  page_depth INTEGER NOT NULL DEFAULT 0 CHECK(page_depth>=0),
  total_pages BIGINT NOT NULL DEFAULT 0,
  total_listings BIGINT NOT NULL DEFAULT 0,
  last_attempt_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT public_crawl_next_url_length CHECK (next_url IS NULL OR length(next_url)<=600)
);
INSERT INTO public_crawl_checkpoints(source_code)
SELECT code FROM data_sources WHERE code IN ('bama','divar','hamrah')
ON CONFLICT (source_code) DO NOTHING;
CREATE TABLE IF NOT EXISTS public_crawl_history (
  id BIGSERIAL PRIMARY KEY,
  source_code TEXT NOT NULL REFERENCES data_sources(code),
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  pages_crawled INTEGER NOT NULL DEFAULT 0,
  cards_seen INTEGER NOT NULL DEFAULT 0,
  details_visited INTEGER NOT NULL DEFAULT 0,
  models_scanned INTEGER NOT NULL DEFAULT 0,
  priority_models INTEGER NOT NULL DEFAULT 0,
  skipped_models INTEGER NOT NULL DEFAULT 0,
  error_codes JSONB NOT NULL DEFAULT '{}'::jsonb,
  accepted_listings INTEGER NOT NULL DEFAULT 0,
  checkpoint_index INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_public_crawl_history_time
  ON public_crawl_history(source_code,finished_at DESC);
CREATE TABLE IF NOT EXISTS public_listing_extras (
  source_code TEXT NOT NULL REFERENCES data_sources(code),
  external_id TEXT NOT NULL,
  url TEXT NOT NULL,
  public_fields JSONB NOT NULL DEFAULT '{}'::jsonb,
  observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (source_code,external_id)
);
CREATE INDEX IF NOT EXISTS idx_public_listing_extras_observed
  ON public_listing_extras(source_code,observed_at DESC);
COMMIT;
