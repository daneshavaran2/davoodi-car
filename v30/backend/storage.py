"""PostgreSQL-only read/write layer; never fetches external websites."""
import os
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path


def connection(*,worker=False):
    import psycopg
    from psycopg.rows import dict_row
    dsn=os.environ.get('DATABASE_URL','')
    if not dsn:raise RuntimeError('DATABASE_URL must point to a PostgreSQL instance')
    return psycopg.connect(dsn,row_factory=dict_row,connect_timeout=4,options='-c statement_timeout='+('60000' if worker else '2500'))


def migrate():
    root=Path(__file__).resolve().parent.parent/'database'
    with connection() as db:
        for p in sorted(root.glob('*.sql')):
            with db.cursor() as cur:
                cur.execute(p.read_text(encoding='utf-8'))
        db.commit()


def ensure_catalog():
    import csv
    from scripts.import_catalog import values, INSERT
    file=Path(__file__).resolve().parent.parent/'data/vehicle_catalog.csv'
    with file.open(encoding='utf-8-sig',newline='') as handle:
        rows=list(csv.DictReader(handle))
    if len(rows)!=660 or len({r['id'] for r in rows})!=660:raise ValueError('Invalid catalog')
    with connection() as db:
        with db.cursor() as cur:
            cur.executemany(INSERT,(values(r) for r in rows))
            for r in rows:
                from .domain import normalize
                options={r['display_name'],r['search_text'],f"{r['brand']} {r['model']}"}
                for a in options:
                    if a.strip():
                        cur.execute('''INSERT INTO vehicle_aliases(vehicle_catalog_id,alias_text,alias_normalized)
                           VALUES(%s,%s,%s) ON CONFLICT(vehicle_catalog_id,alias_normalized) DO NOTHING''',
                            (r['id'],a,normalize(a)))
            for alias,display in {'Santa Fe':'هیوندای سانتافه','Hyundai Santa Fe':'هیوندای سانتافه',
                                  'Lifan 820':'لیفان 820','Toyota Camry':'تویوتا کمری',
                                  'Peugeot 207':'پژو 207i','Fidelity Prime':'بهمن فیدلیتی پرایم'}.items():
                cur.execute('SELECT catalog_id FROM vehicle_models WHERE display_name=%s LIMIT 1',(display,))
                found=cur.fetchone()
                if found:
                    cur.execute('''INSERT INTO vehicle_aliases(vehicle_catalog_id,alias_text,alias_normalized)
                      VALUES(%s,%s,%s) ON CONFLICT(vehicle_catalog_id,alias_normalized) DO NOTHING''',
                      (found['catalog_id'],alias,normalize(alias)))
        db.commit()
    return len(rows)


def vehicles():
    with connection() as db:
        with db.cursor() as cur:
            cur.execute('SELECT catalog_id,brand,model,display_name,search_text FROM vehicle_models')
            cars=cur.fetchall()
            cur.execute('SELECT vehicle_catalog_id,alias_text FROM vehicle_aliases')
            aliases=cur.fetchall()
    return cars,aliases


def price_rows(catalog_id,year=None,trim=None,condition=None):
    params=[catalog_id]
    sql='''SELECT p.segment_key,p.model_year,p.year_system,p.vehicle_condition,p.mileage_band,
       v.fuel_type,p.body_condition,p.sample_count,p.source_count,p.low_toman,p.median_toman,
       p.high_toman,p.confidence,p.computed_at,p.stale_after,v.trim_name,v.transmission
       FROM price_estimates p LEFT JOIN vehicle_variants v ON v.id=p.variant_id
       WHERE p.vehicle_catalog_id=%s AND p.sample_count>=5 AND p.stale_after>NOW()'''
    if year is not None:
        sql+=' AND p.model_year=%s';params.append(year)
    if condition is not None:
        sql+=' AND p.vehicle_condition=%s';params.append(condition)
    if trim:
        # Generic Prime/Elite queries show separately priced 5/7-seat variants.
        if trim in ('پرایم','پرستیژ','الیت'):
            sql+=' AND (v.trim_name=%s OR v.trim_name LIKE %s)'
            params.extend((trim,trim+' %'))
        else:
            sql+=' AND v.trim_name=%s';params.append(trim)
    sql+=' ORDER BY p.sample_count DESC,p.computed_at DESC LIMIT 30'
    with connection() as db:
        with db.cursor() as cur:
            cur.execute(sql,params);rows=cur.fetchall()
            for row in rows:
                cur.execute('''SELECT source_code,price_toman,url,observed_at FROM price_samples
                       WHERE segment_key=%s ORDER BY observed_at DESC LIMIT 5''',(row['segment_key'],))
                row['ads']=cur.fetchall()
    return rows


def request_refresh(catalog_id,year,trim):
    with connection() as db:
        with db.cursor() as cur:
            cur.execute('''SELECT id FROM refresh_requests WHERE vehicle_catalog_id=%s
                AND model_year IS NOT DISTINCT FROM %s AND trim_name IS NOT DISTINCT FROM %s
                AND status='pending' AND created_at>NOW()-INTERVAL '4 hours' LIMIT 1''',(catalog_id,year,trim))
            found=cur.fetchone()
            if not found:
                cur.execute('INSERT INTO refresh_requests(vehicle_catalog_id,model_year,trim_name) VALUES(%s,%s,%s)',
                            (catalog_id,year,trim))
        db.commit()


def source_statuses():
    with connection() as db:
        with db.cursor() as cur:
            cur.execute('''SELECT s.code,s.name,s.enabled,s.access_method,s.access_verified_at,
                s.last_attempt_at,s.last_success_at,s.last_error_code,s.last_error_detail,
                (SELECT fetched_count FROM fetch_runs f WHERE f.source_code=s.code ORDER BY started_at DESC LIMIT 1) AS fetched_count,
                (SELECT valid_count FROM fetch_runs f WHERE f.source_code=s.code ORDER BY started_at DESC LIMIT 1) AS valid_count
                FROM data_sources s ORDER BY code''')
            sources=cur.fetchall()
            cur.execute('SELECT * FROM scheduler_runs ORDER BY scheduled_for DESC LIMIT 1')
            schedule=cur.fetchone()
            cur.execute('SELECT COUNT(*) AS n FROM price_estimates WHERE sample_count>=5')
            prices=cur.fetchone()['n']
    return sources,schedule,prices


def set_source(source,enabled):
    with connection() as db:
        with db.cursor() as cur:
            cur.execute('UPDATE data_sources SET enabled=%s WHERE code=%s RETURNING code',(enabled,source))
            if not cur.fetchone():raise KeyError('unknown source')
        db.commit()
