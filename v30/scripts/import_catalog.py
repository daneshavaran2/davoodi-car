"""Idempotent catalog import to PostgreSQL.

Install: pip install 'psycopg[binary]>=3,<4'
Prepare DB: psql "$DATABASE_URL" -f db/schema.sql
Run: python scripts/import_catalog.py --file data/vehicle_catalog.csv
Does not import prices or scrape any source.
"""
import argparse
import csv
import os
from pathlib import Path

import psycopg

FIELDS = [
    'catalog_id', 'brand', 'model', 'display_name', 'search_text',
    'brand_origin', 'supply_type', 'manufacturer_or_importer', 'body_type', 'fuel_type',
    'production_start_year_ce_approx', 'production_end_year_ce_approx',
    'start_year_shamsi_approx', 'market_status_as_listed',
    'source_excel_row_numbers', 'requires_trim_year_and_condition_for_price'
]

INSERT = f"""
INSERT INTO vehicle_models ({', '.join(FIELDS)})
VALUES ({', '.join(['%s'] * len(FIELDS))})
ON CONFLICT (catalog_id) DO UPDATE SET
  brand=EXCLUDED.brand,
  model=EXCLUDED.model,
  display_name=EXCLUDED.display_name,
  search_text=EXCLUDED.search_text,
  brand_origin=EXCLUDED.brand_origin,
  supply_type=EXCLUDED.supply_type,
  manufacturer_or_importer=EXCLUDED.manufacturer_or_importer,
  body_type=EXCLUDED.body_type,
  fuel_type=EXCLUDED.fuel_type,
  production_start_year_ce_approx=EXCLUDED.production_start_year_ce_approx,
  production_end_year_ce_approx=EXCLUDED.production_end_year_ce_approx,
  start_year_shamsi_approx=EXCLUDED.start_year_shamsi_approx,
  market_status_as_listed=EXCLUDED.market_status_as_listed,
  source_excel_row_numbers=EXCLUDED.source_excel_row_numbers,
  requires_trim_year_and_condition_for_price=EXCLUDED.requires_trim_year_and_condition_for_price,
  updated_at=NOW()
"""

def maybe_int(value):
    return int(value.strip()) if value and value.strip() else None

def values(row):
    return (
        row['id'], row['brand'], row['model'], row['display_name'], row['search_text'],
        row['brand_origin'], row['supply_type'], row['manufacturer_or_importer'],
        row['body_type'], row['fuel_type'],
        maybe_int(row['production_start_year_ce_approx']),
        maybe_int(row['production_end_year_ce_approx']),
        maybe_int(row['start_year_shamsi_approx']),
        row['market_status_as_listed'], row['source_excel_row_numbers'],
        row['requires_trim_year_and_condition_for_price'].strip().lower() == 'true',
    )

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--file', required=True, type=Path)
    args = parser.parse_args()
    dsn = os.environ.get('DATABASE_URL')
    if not dsn:
        raise SystemExit('DATABASE_URL env var is required')
    with args.file.open(encoding='utf-8-sig', newline='') as fp:
        rows = list(csv.DictReader(fp))
    if len(rows) != 660:
        raise SystemExit(f'Unexpected catalog count: {len(rows)}; expected 660')
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.executemany(INSERT, (values(row) for row in rows))
            cur.execute('SELECT COUNT(*) FROM vehicle_models')
            print(f'Upserted {len(rows)} catalog records; total vehicles in DB: {cur.fetchone()[0]}')

if __name__ == '__main__':
    main()
