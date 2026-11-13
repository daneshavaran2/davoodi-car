-- Quality instrumentation: additive, never removes pricing or stored listings.
BEGIN;
ALTER TABLE public_crawl_history
  ADD COLUMN IF NOT EXISTS evidence_rejected INTEGER NOT NULL DEFAULT 0;
ALTER TABLE public_crawl_history
  ADD COLUMN IF NOT EXISTS detail_conflicts INTEGER NOT NULL DEFAULT 0;
COMMIT;
