"""Read-only Liara PostgreSQL connectivity and catalog check.

Does NOT print secrets or create a database. Invoke from the running Liara
container: python -m scripts.check_liara_db
"""
import os
import sys
from urllib.parse import urlsplit


def main() -> int:
    dsn = os.getenv("DATABASE_URL", "")
    if not dsn:
        print("FAIL: DATABASE_URL is missing in Liara environment.", flush=True)
        return 2
    try:
        url = urlsplit(dsn)
        if url.scheme not in ("postgres", "postgresql"):
            print("FAIL: DATABASE_URL must use postgresql:// protocol.", flush=True)
            return 2
        if not url.hostname:
            print("FAIL: PostgreSQL hostname is missing.", flush=True)
            return 2
        if url.hostname in ("postgres", "localhost", "127.0.0.1") and os.getenv("LIARA_DEPLOYMENT", "1") == "1":
            print("FAIL: Host is a local Docker Compose hostname, not the private Liara database endpoint.", flush=True)
            return 2
    except (TypeError, ValueError):
        print("FAIL: DATABASE_URL has invalid syntax.", flush=True)
        return 2
    try:
        from backend.storage import connection
        with connection() as db:
            with db.cursor() as cur:
                cur.execute("SELECT current_database() AS name, current_user AS role, 1 AS ok")
                row = cur.fetchone()
                if row["ok"] != 1:
                    raise RuntimeError("Unexpected PostgreSQL response")
                print("OK: PostgreSQL connection established. Database:", row["name"], flush=True)
                cur.execute("SELECT to_regclass('public.vehicle_models') AS table_name")
                table = cur.fetchone()["table_name"]
                if table:
                    cur.execute("SELECT count(*) AS total FROM vehicle_models")
                    count = cur.fetchone()["total"]
                    print("OK: vehicle_models table exists; rows:", count, flush=True)
                    if count != 660:
                        print("INFO: Catalog row count is not 660. Bootstrap/import may be required.", flush=True)
                else:
                    print("INFO: Database connected, schema not installed yet; run bootstrap.", flush=True)
        return 0
    except Exception as exc:
        # Avoid printing a database URL from low-level errors.
        print("FAIL: PostgreSQL connection/query failed (" + type(exc).__name__ + ").", flush=True)
        print("Check the database status, private network, host, port, password and SSL mode in Liara.", flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
