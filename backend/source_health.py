"""Per-source observations, with honest attempt and evidence timestamps.

The audit is stored in the existing SQLite database. A source with no active
connector and no permitted search service is NOT represented as checked.
"""
from __future__ import annotations
import time

_SCHEMA = """CREATE TABLE IF NOT EXISTS source_checks (
    domain TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    modes TEXT NOT NULL DEFAULT '',
    last_attempt_at REAL,
    last_verified_price_at REAL,
    last_error_at REAL,
    raw_count INTEGER NOT NULL DEFAULT 0,
    accepted_count INTEGER NOT NULL DEFAULT 0,
    detail TEXT NOT NULL DEFAULT ''
)"""


def record_source_results(db_factory, statuses, now=None):
    """Return display-ready copies and persist last real attempts/evidence.

    Source "checked_at" reflects this request only. "last_attempt_at" and
    "last_verified_price_at" are retained from previous successful requests.
    All dates are UTC unix seconds. No external network call happens here.
    """
    now = float(time.time() if now is None else now)
    result = []
    with db_factory() as conn:
        conn.execute(_SCHEMA)
        for input_status in statuses:
            st = dict(input_status)
            domain = str(st['domain'])
            previous = conn.execute(
                'SELECT last_attempt_at,last_verified_price_at,last_error_at FROM source_checks WHERE domain=?',
                (domain,)
            ).fetchone()
            attempted = bool(st.get('attempted'))
            accepted = max(0, int(st.get('accepted_count') or 0))
            error = st.get('status') in ('connector_error','rate_limited','error')
            last_attempt = now if attempted else (previous['last_attempt_at'] if previous else None)
            last_verified = now if accepted else (previous['last_verified_price_at'] if previous else None)
            last_error = now if error else (previous['last_error_at'] if previous else None)
            st['checked_at'] = now if attempted else None
            st['last_attempt_at'] = last_attempt
            st['last_verified_price_at'] = last_verified
            st['last_error_at'] = last_error
            conn.execute(
                '''INSERT INTO source_checks
                   (domain,name,status,modes,last_attempt_at,last_verified_price_at,
                    last_error_at,raw_count,accepted_count,detail)
                   VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(domain) DO UPDATE SET
                     name=excluded.name,status=excluded.status,modes=excluded.modes,
                     last_attempt_at=excluded.last_attempt_at,
                     last_verified_price_at=excluded.last_verified_price_at,
                     last_error_at=excluded.last_error_at,
                     raw_count=excluded.raw_count,accepted_count=excluded.accepted_count,
                     detail=excluded.detail''',
                (domain,str(st.get('name') or domain),str(st.get('status') or 'not_checked'),
                 ','.join(st.get('modes') or []),last_attempt,last_verified,last_error,
                 int(st.get('raw_count') or 0),accepted,str(st.get('detail') or '')[:240])
            )
            result.append(st)
        conn.commit()
    return result


def read_source_results(db_factory):
    with db_factory() as conn:
        conn.execute(_SCHEMA)
        return [
            {'domain':row['domain'],'name':row['name'],'status':row['status'],
             'modes':row['modes'].split(',') if row['modes'] else [],
             'last_attempt_at':row['last_attempt_at'],
             'last_verified_price_at':row['last_verified_price_at'],
             'last_error_at':row['last_error_at'],
             'raw_count':row['raw_count'],'accepted_count':row['accepted_count'],
             'detail':row['detail']}
            for row in conn.execute('SELECT * FROM source_checks ORDER BY domain').fetchall()
        ]
