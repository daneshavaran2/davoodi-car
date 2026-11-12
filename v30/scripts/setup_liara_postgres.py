"""Safe, idempotent DavoodiCar PostgreSQL setup for an existing Liara DB.

Usage in the *deployed* Liara web/worker container:
    python -m scripts.setup_liara_postgres --apply

- Requires DATABASE_URL from Liara's private PostgreSQL connection info.
- Does not create or purchase a Liara database resource.
- Does not DROP/TRUNCATE tables or overwrite valid market price snapshots.
- Calls the existing advisory-locked bootstrap and verifies catalog count.
- Never writes database credentials into stdout/logs.
"""
from __future__ import annotations
import argparse
import os
from urllib.parse import urlsplit


def _configuration_ok():
    dsn = os.getenv('DATABASE_URL', '').strip()
    if not dsn:
        return False, 'DATABASE_URL_MISSING'
    try:
        url = urlsplit(dsn)
        if url.scheme not in ('postgres', 'postgresql') or not url.hostname:
            return False, 'DATABASE_URL_INVALID'
        if any(flag in dsn for flag in ('CHANGE_THIS_PASSWORD','LIARA_PRIVATE_DB_HOST','DB_USER:')):
            return False, 'DATABASE_URL_PLACEHOLDER'
    except (ValueError, TypeError):
        return False, 'DATABASE_URL_INVALID'
    return True, None


def run(apply=False):
    configured, error = _configuration_ok()
    if not configured:
        print('NOT_READY: '+error, flush=True)
        return 2
    try:
        from backend.storage import connection
        # Health probe occurs before any write or schema manipulation.
        with connection(worker=True) as db:
            with db.cursor() as cur:
                cur.execute('SELECT current_database() AS db, 1 AS ok')
                if cur.fetchone()['ok'] != 1:
                    raise RuntimeError('PostgreSQL query verification failed')
        print('CONNECTED: PostgreSQL replied to an authenticated query.', flush=True)
        if apply:
            from scripts.bootstrap import main as bootstrap
            bootstrap()
        else:
            print('READ_ONLY: pass --apply to run idempotent migrations/catalog import.', flush=True)
        with connection(worker=True) as db:
            with db.cursor() as cur:
                cur.execute("SELECT to_regclass('public.vehicle_models') AS tbl")
                if not cur.fetchone()['tbl']:
                    print('SCHEMA_MISSING: run again with --apply.', flush=True)
                    return 3
                cur.execute('SELECT COUNT(*) AS n FROM vehicle_models')
                vehicle_count = int(cur.fetchone()['n'])
                cur.execute("SELECT to_regclass('public.vehicle_aliases') AS tbl")
                if not cur.fetchone()['tbl']:
                    print('SCHEMA_MISSING: vehicle_aliases does not exist.', flush=True)
                    return 3
                cur.execute('SELECT COUNT(*) AS n FROM vehicle_aliases')
                alias_count = int(cur.fetchone()['n'])
                cur.execute("SELECT to_regclass('public.data_sources') AS tbl")
                if not cur.fetchone()['tbl']:
                    print('SCHEMA_MISSING: data_sources does not exist.', flush=True)
                    return 3
                cur.execute('SELECT COUNT(*) AS n FROM data_sources')
                source_count = int(cur.fetchone()['n'])
        print(f'CATALOG: vehicles={vehicle_count}, aliases={alias_count}, sources={source_count}', flush=True)
        if vehicle_count < 660 or source_count < 6:
            print('INCOMPLETE: expected at least 660 catalog cars and 6 source definitions.', flush=True)
            return 4
        print('READY: database schema and initial car catalog available.', flush=True)
        return 0
    except Exception as exc:
        # psycopg exceptions can contain the DSN/host. Never print str(exc).
        print('FAILED: PostgreSQL setup failed ('+type(exc).__name__+'). Review Liara DB logs.', flush=True)
        return 1


def main():
    parser = argparse.ArgumentParser(description='DavoodiCar Liara PostgreSQL bootstrap verification')
    parser.add_argument('--apply', action='store_true', help='Apply existing idempotent migrations and upsert catalog')
    args = parser.parse_args()
    return run(apply=args.apply)


if __name__ == '__main__':
    raise SystemExit(main())
