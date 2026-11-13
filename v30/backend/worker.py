"""Independent hourly worker. Run using `python -m backend.worker --loop`.

Production scheduler runs in its own process/container, NEVER on a web request.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
from datetime import datetime,timezone,timedelta
import hashlib
import json
import logging
import os
import time
from zoneinfo import ZoneInfo

from .storage import connection
from .domain import normalize, clean_listing, grouping_key, quote, mileage_band
from .connectors import SOURCE_CODES, SourceUnavailable, collect_source
from . import nemuda
from .legacy_bridge import pilot_mode, collect_public

log=logging.getLogger('davoodicar.worker')
ADVISORY_LOCK_ID=7428343991011


def _now():return datetime.now(timezone.utc)


def _audit(cur,code,started,status,err_code=None,detail='',fetched=0,valid=0,rejected=0):
    cur.execute('''INSERT INTO fetch_runs(source_code,started_at,finished_at,status,
       error_code,error_detail,fetched_count,valid_count,rejected_count)
       VALUES(%s,%s,NOW(),%s,%s,%s,%s,%s,%s)''',
       (code,started,status,err_code,detail[:250],fetched,valid,rejected))
    cur.execute('''UPDATE data_sources SET last_attempt_at=%s,
       last_error_code=%s,last_error_detail=%s WHERE code=%s''',
       (started,err_code,detail[:250] if err_code else None,code))
    if valid:
        cur.execute('''UPDATE data_sources SET last_success_at=NOW(),
         access_verified_at=COALESCE(access_verified_at,NOW()),
         last_error_code=NULL,last_error_detail=NULL WHERE code=%s''',(code,))


def _variant(cur,listing):
    # A missing trim is rejected by strict validator; transmission is kept
    # separate from trim, avoiding e.g. Dena Turbo automatic/manual mixing.
    raw='|'.join((listing['catalog_id'],listing['trim'],listing['transmission'],listing.get('fuel_type','unknown')))
    key=hashlib.sha256(raw.encode()).hexdigest()[:32]
    cur.execute('''INSERT INTO vehicle_variants(vehicle_catalog_id,trim_name,transmission,fuel_type,canonical_key)
        VALUES(%s,%s,%s,%s,%s) ON CONFLICT(canonical_key) DO UPDATE SET
        trim_name=EXCLUDED.trim_name RETURNING id''',
        (listing['catalog_id'],listing['trim'],listing['transmission'],listing.get('fuel_type','unknown'),key))
    return cur.fetchone()['id']


def _save_ad(cur,x):
    variant=_variant(cur,x)
    cur.execute('''INSERT INTO car_listings(
        source_code,external_id,url,vehicle_catalog_id,variant_id,
        model_year,year_system,vehicle_condition,mileage_km,body_condition,
        transmission,fuel_type,city,price_toman,price_kind,published_at,observed_at,last_seen_at,
        expires_at,listing_fingerprint,validation_status,validation_reason,title,trim_name)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'asking',%s,%s,%s,%s,%s,'valid',NULL,%s,%s)
        ON CONFLICT(source_code,external_id) DO UPDATE SET
        url=EXCLUDED.url,vehicle_catalog_id=EXCLUDED.vehicle_catalog_id,
        variant_id=EXCLUDED.variant_id,model_year=EXCLUDED.model_year,
        year_system=EXCLUDED.year_system,vehicle_condition=EXCLUDED.vehicle_condition,
        mileage_km=EXCLUDED.mileage_km,body_condition=EXCLUDED.body_condition,
        transmission=EXCLUDED.transmission,fuel_type=EXCLUDED.fuel_type,city=EXCLUDED.city,
        price_toman=EXCLUDED.price_toman,published_at=EXCLUDED.published_at,
        observed_at=EXCLUDED.observed_at,last_seen_at=EXCLUDED.last_seen_at,
        expires_at=EXCLUDED.expires_at,validation_status='valid',
        title=EXCLUDED.title,trim_name=EXCLUDED.trim_name,updated_at=NOW()''',
        (x['source'],x['external_id'],x['url'],x['catalog_id'],variant,
         x['year'],x['year_system'],x['condition'],x['mileage_km'],x['body_condition'],
         x['transmission'],x['fuel_type'],x['city'],x['price_toman'],x['published_at'],
         x['observed_at'],x['observed_at'],x['observed_at']+timedelta(days=14),
         hashlib.sha256((normalize(x['title'])+str(x['price_toman'])+str(x['mileage_km'])+x['city']).encode()).hexdigest(),
         x['title'],x['trim']))


def _recompute(cur,run_started):
    # Preserve previous successful snapshots: only update groups with >=5
    # fresh valid ads. In a source outage, nothing is overwritten with zero.
    cur.execute('''SELECT l.source_code AS source,l.external_id,l.url,
       l.vehicle_catalog_id AS catalog_id,l.model_year AS year,
       l.year_system,l.trim_name AS trim,l.vehicle_condition AS condition,
       l.mileage_km,l.transmission,l.fuel_type,l.body_condition,l.price_toman,l.observed_at,
       l.title,l.city
       FROM car_listings l JOIN data_sources s ON s.code=l.source_code
       WHERE s.enabled AND l.validation_status='valid' AND l.price_kind='asking'
       AND l.expires_at>NOW() AND l.last_seen_at>NOW()-INTERVAL '14 days'
       ORDER BY l.observed_at DESC LIMIT 200000''')
    rows=cur.fetchall()
    # Cross-source dedup is conservative: a title+price+km+city match; for this
    # first MVP keep same-site ID primary; same car crossposting may remain.
    groups=defaultdict(list)
    seen_fingerprints=set()
    for ad in rows:
        # Only deduplicate across different providers with strong indicators:
        # identical descriptive title, asking price, odometer and city.
        title=normalize(ad.get('title'))
        city=normalize(ad.get('city'))
        fp=(grouping_key(ad),title,ad['price_toman'],ad.get('mileage_km'),city)
        if len(title)>=15 and city and ad.get('mileage_km') is not None:
            if fp in seen_fingerprints:continue
            seen_fingerprints.add(fp)
        groups[grouping_key(ad)].append(ad)
    refreshed=0
    for key,ads in groups.items():
        # Freshness is earned only if this run actually fetched at least one
        # valid ad from this precise group. A response from an unrelated source
        # must not make all old cached price ranges appear freshly updated.
        if not any(a['observed_at']>=run_started for a in ads):
            continue
        q=quote(ads)
        if not q:continue
        catalog_id,year,system,trim,condition,transmission,fuel,body,band=key
        segment=hashlib.sha256(json.dumps(key,ensure_ascii=False).encode()).hexdigest()[:40]
        variant=_variant(cur,ads[0])
        now=_now()
        cur.execute('''INSERT INTO price_estimates(
         segment_key,vehicle_catalog_id,variant_id,model_year,year_system,
         vehicle_condition,mileage_band,body_condition,region,sample_count,
         source_count,low_toman,median_toman,high_toman,confidence,
         computed_at,freshest_listing_at,stale_after,calculation_version)
         VALUES(%s,%s,%s,%s,%s,%s,%s,%s,NULL,%s,%s,%s,%s,%s,%s,%s,%s,%s,'v30.1')
         ON CONFLICT(segment_key) DO UPDATE SET
         sample_count=EXCLUDED.sample_count,source_count=EXCLUDED.source_count,
         low_toman=EXCLUDED.low_toman,median_toman=EXCLUDED.median_toman,
         high_toman=EXCLUDED.high_toman,confidence=EXCLUDED.confidence,
         computed_at=EXCLUDED.computed_at,freshest_listing_at=EXCLUDED.freshest_listing_at,
         stale_after=EXCLUDED.stale_after,calculation_version=EXCLUDED.calculation_version''',
         (segment,catalog_id,variant,year,system,condition,band,body,
          q['count'],len(q['sources']),q['low'],q['median'],q['high'],q['confidence'],
          now,max(a['observed_at'] for a in ads),now+timedelta(hours=2)))
        cur.execute('''INSERT INTO price_estimate_history(segment_key,computed_at,sample_count,
            source_count,low_toman,median_toman,high_toman,confidence,calculation_version)
            VALUES(%s,NOW(),%s,%s,%s,%s,%s,%s,'v30.1')''',
            (segment,q['count'],len(q['sources']),q['low'],q['median'],q['high'],q['confidence']))
        cur.execute('DELETE FROM price_samples WHERE segment_key=%s',(segment,))
        for ad in ads:
            cur.execute('''INSERT INTO price_samples(segment_key,source_code,external_id,
                 price_toman,url,observed_at) VALUES(%s,%s,%s,%s,%s,%s)
                 ON CONFLICT(segment_key,source_code,external_id) DO NOTHING''',
                 (segment,ad['source'],ad['external_id'],ad['price_toman'],ad['url'],ad['observed_at']))
        refreshed+=1
    return refreshed


def run_once(scheduled_for=None):
    """A single scheduler tick. Advisory lock and hour key prevent overlap."""
    if scheduled_for is None:
        zone=ZoneInfo(os.getenv('SCHEDULER_TZ','Asia/Tehran'))
        scheduled_for=_now().astimezone(zone).replace(minute=0,second=0,microsecond=0).astimezone(timezone.utc)
    with connection(worker=True) as db:
        with db.cursor() as cur:
            cur.execute('SELECT pg_try_advisory_lock(%s) AS locked',(ADVISORY_LOCK_ID,))
            if not cur.fetchone()['locked']:
                log.warning('Another worker holds the scheduler lock')
                return {'status':'already_running'}
            db.commit()
            try:
                cur.execute('''INSERT INTO scheduler_runs(scheduled_for,status)
                    VALUES(%s,'running') ON CONFLICT(scheduled_for) DO NOTHING RETURNING scheduled_for''',(scheduled_for,))
                if not cur.fetchone():
                    db.rollback()
                    return {'status':'duplicate_hour'}
                db.commit()
                cur.execute('''SELECT catalog_id,brand,model,display_name FROM vehicle_models''')
                catalog=cur.fetchall()
                mapping={(normalize(x['brand']),normalize(x['model'])):x['catalog_id'] for x in catalog}
                cur.execute('SELECT code,enabled FROM data_sources ORDER BY code')
                sources=cur.fetchall()
                good=0;failed=0
                run_started=_now()
                for source in sources:
                    code=source['code']; started=_now()
                    if not source['enabled']:
                        # Skipping an inactive source is not a network attempt.
                        cur.execute('''INSERT INTO fetch_runs(source_code,started_at,finished_at,status,
                          error_code,error_detail) VALUES(%s,%s,NOW(),'skipped',%s,%s)''',
                          (code,started,'TERMS_NOT_PERMITTED','Source disabled by administrator'))
                        db.commit();continue
                    try:
                        # Licensed source adapters may serve all catalog models in one feed.
                        items=(collect_public(code,catalog) if pilot_mode(code) else
                               collect_source(code,{'catalog_version':'v30','locale':'fa-IR'},max_pages=int(os.getenv('MAX_PAGES_PER_SOURCE','8'))))
                        valid=[]; reasons=defaultdict(int)
                        for raw in items:
                            x,reason=clean_listing(raw,code,mapping,now=started)
                            if x:valid.append(x)
                            else:reasons[reason]+=1
                        # Network and parser fully succeeded before data is written.
                        with db.transaction():
                            for x in valid:_save_ad(cur,x)
                            status='success' if valid else 'partial'
                            err='NO_MATCHING_CARS' if items and not valid else 'NO_RESULTS' if not items else None
                            _audit(cur,code,started,status,err,
                                   json.dumps(dict(reasons),ensure_ascii=False),len(items),len(valid),len(items)-len(valid))
                        db.commit();good+=1
                    except SourceUnavailable as exc:
                        db.rollback();failed+=1
                        _audit(cur,code,started,'failed',exc.code,str(exc)[:230]);db.commit()
                    except Exception as exc:
                        db.rollback();failed+=1
                        log.exception('Source %s failed',code)
                        _audit(cur,code,started,'failed','PARSER_CHANGED',str(exc)[:230]);db.commit()
                # External aggregate prices remain in a separate table.
                # A failed Nemuda request never clears earlier successful rows.
                with db.cursor() as catalog_cur:
                    catalog_cur.execute('SELECT catalog_id,brand,model,display_name FROM vehicle_models')
                    nemuda_cars=catalog_cur.fetchall()
                    catalog_cur.execute('SELECT vehicle_catalog_id,alias_text FROM vehicle_aliases')
                    nemuda_aliases=catalog_cur.fetchall()
                aggregate_status=nemuda.refresh(db,nemuda_cars,nemuda_aliases)
                if aggregate_status['status']=='ok':good+=1
                elif aggregate_status['status'] in ('error','no_matches'):failed+=1
                with db.transaction():
                    n=_recompute(cur,run_started) if good else 0
                    cur.execute('UPDATE scheduler_runs SET finished_at=NOW(),status=%s,source_ok=%s,source_failed=%s,error_summary=%s WHERE scheduled_for=%s',
                                ('success' if good and not failed else 'partial' if good else 'failed',
                                 good,failed,'No verified sources' if not good else None,scheduled_for))
                    cur.execute('UPDATE refresh_requests SET status=%s,completed_at=NOW() WHERE status=%s',('attempted','pending'))
                db.commit()
                return {'status':'completed','sources_successful':good,'sources_failed':failed,'estimates_recomputed':n}
            finally:
                cur.execute('SELECT pg_advisory_unlock(%s)',(ADVISORY_LOCK_ID,))
                db.commit()


def next_hour(tz_name='Asia/Tehran'):
    tz=ZoneInfo(tz_name)
    local=_now().astimezone(tz)
    return (local.replace(minute=0,second=0,microsecond=0)+timedelta(hours=1)).astimezone(timezone.utc)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--loop',action='store_true')
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.loop:
        # A long-running independent worker wakes briefly to handle manual
        # admin jobs and also runs at every whole hour without user traffic.
        last_tick=None
        while True:
            try:
                local_zone=ZoneInfo(os.getenv('SCHEDULER_TZ','Asia/Tehran'))
                current=_now().astimezone(local_zone).replace(minute=0,second=0,microsecond=0).astimezone(timezone.utc)
                if current!=last_tick:
                    last_tick=current
                    log.info('Scheduled collection: %s',run_once(current))
                with connection(worker=True) as db:
                    with db.cursor() as cur:
                        cur.execute("SELECT id FROM refresh_requests WHERE status='pending' ORDER BY created_at LIMIT 1")
                        pending=cur.fetchone()
                if pending:
                    manual=_now().replace(microsecond=0)
                    log.info('Manual collection %s: %s',pending['id'],run_once(manual))
            except Exception:
                log.exception('Scheduled collection failed')
            time.sleep(20)
    else:print(run_once())

if __name__=='__main__':main()

