"""Idempotent production bootstrap with a cross-container PostgreSQL lock."""
from backend.storage import connection,migrate,ensure_catalog

LOCK=7428343991012

def main():
    with connection(worker=True) as db:
        with db.cursor() as cur:
            cur.execute('SELECT pg_advisory_lock(%s)',(LOCK,))
            db.commit()
            try:
                migrate()
                count=ensure_catalog()
                print(f'PostgreSQL schema ready. Catalog upserted: {count} vehicles.',flush=True)
            finally:
                cur.execute('SELECT pg_advisory_unlock(%s)',(LOCK,))
                db.commit()

if __name__=='__main__':main()
