"""DavoodiCar v30 HTTP service: PostgreSQL reads only on user search."""
from __future__ import annotations
from datetime import datetime,timezone
from functools import lru_cache
from pathlib import Path
import hashlib
import hmac
import os
import re
import time
from typing import Optional

from fastapi import FastAPI,HTTPException,Depends,Header,Query,Request
from fastapi.responses import FileResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field

from . import storage
from .domain import find_vehicle,query_year,query_trim,query_condition,normalize

app=FastAPI(title='DavoodiCar Offline-First',version='30.0.0')
DIST=Path(os.getenv('FRONTEND_DIST','/app/frontend/dist'))


def admin_only(authorization:Optional[str]=Header(None)):
    expected=os.environ.get('ADMIN_TOKEN','')
    if not expected or len(expected)<32:
        raise HTTPException(status_code=503,detail='Admin credentials not configured')
    supplied=(authorization or '').removeprefix('Bearer ').strip()
    if not hmac.compare_digest(expected,supplied):raise HTTPException(status_code=401,detail='Access denied')
    return True


# Basic in-process protection for unknown clients; production installations
# should also enforce edge rate limits at Liara / gateway.
_seen={}

def public_limit(request:Request):
    key=request.client.host if request.client else 'unknown'
    now=time.monotonic()
    recent=[x for x in _seen.get(key,[]) if now-x<60]
    if len(recent)>=100:raise HTTPException(429,detail='کمی بعد دوباره تلاش کنید.')
    recent.append(now);_seen[key]=recent
    if len(_seen)>1000:
        for old in list(_seen)[:200]:_seen.pop(old,None)


def iso(v):return v.astimezone(timezone.utc).isoformat() if isinstance(v,datetime) else None


@app.get('/api/v1/health')
def health():
    # The web process stays available while PostgreSQL is down; readiness
    # remains 503 JSON until both schema and catalog are initialized.
    error_code = 'DATABASE_URL_MISSING' if not os.getenv('DATABASE_URL', '').strip() else 'DATABASE_UNAVAILABLE'
    if error_code == 'DATABASE_URL_MISSING':
        return JSONResponse(status_code=503,content={'status':'unavailable',
            'version':'30.1.0','database':'unavailable','error_code':error_code})
    try:
        with storage.connection() as db:
            with db.cursor() as cur:
                cur.execute("SELECT to_regclass('public.vehicle_models') AS table_name")
                if not cur.fetchone()['table_name']:
                    error_code='SCHEMA_NOT_READY'
                else:
                    cur.execute('SELECT COUNT(*) AS n FROM vehicle_models')
                    error_code='CATALOG_NOT_READY' if cur.fetchone()['n'] < 660 else None
        if error_code is None:
            return {'status':'ok','version':'30.1.0','database':'ok',
                    'search_mode':'postgresql_only','scheduler':'independent_worker'}
    except Exception:
        error_code='DATABASE_UNAVAILABLE'
    return JSONResponse(status_code=503,content={'status':'unavailable',
        'version':'30.1.0','database':'unavailable','error_code':error_code})


@app.middleware('http')
async def sanitized_database_error(request, call_next):
    try:
        return await call_next(request)
    except Exception as exc:
        module=type(exc).__module__
        is_db_error=module.startswith('psycopg') or (
            isinstance(exc,RuntimeError) and 'DATABASE_URL' in str(exc))
        if not is_db_error:
            raise
        return JSONResponse(status_code=503,content={
            'status':'unavailable','error_code':'DATABASE_UNAVAILABLE',
            'detail':'پایگاه داده قیمت‌ها موقتاً در دسترس نیست. تنظیمات PostgreSQL در Liara بررسی شود.'})


# Compatibility with the former Liara monitoring URLs.
@app.get('/api/health')
def old_health():return health()


@app.get('/api/v1/vehicles/search')
def search_vehicles(q:str=Query(min_length=2,max_length=100),_:None=Depends(public_limit)):
    cars,aliases=storage.vehicles()
    resolution=find_vehicle(q,cars,aliases)
    if resolution['status']=='not_found':
        # Supplemental autocomplete: safe candidate suggestions, never a quote.
        needle=normalize(q)
        candidates=[r for r in cars if needle in normalize(r['display_name'])]
        resolution={'status':'needs_selection' if candidates else 'not_found',
                    'matches':candidates[:12],'corrected':False}
    return {'status':resolution['status'],
            'suggestions':[{'id':x['catalog_id'],'brand':x['brand'],'model':x['model'],
                            'name':x['display_name']} for x in resolution['matches'][:12]],
            'requires_confirmation':bool(resolution['corrected'])}


@app.get('/api/v1/prices/estimate')
def estimate(q:str=Query(min_length=2,max_length=100),
             vehicle_id:Optional[str]=Query(default=None,max_length=32),
             year:Optional[int]=Query(default=None,ge=1350,le=2100),
             trim:Optional[str]=Query(default=None,max_length=80),
             condition:Optional[str]=Query(default=None,pattern='^(new|used)$'),
             _:None=Depends(public_limit)):
    t0=time.monotonic()
    cars,aliases=storage.vehicles()
    found=find_vehicle(q,cars,aliases)
    if vehicle_id:
        selected=[r for r in cars if r['catalog_id']==vehicle_id]
    else:
        selected=found['matches']
    if not selected:
        return {'status':'no_data','message':'خودرو شناسایی نشد؛ نام مدل را دقیق‌تر وارد کنید.',
                'groups':[],'duration_ms':round((time.monotonic()-t0)*1000)}
    if len(selected)>1 or (not vehicle_id and found.get('corrected')):
        return {'status':'needs_selection','message':'مدل دقیق خودرو را انتخاب کنید.',
                'options':[{'id':x['catalog_id'],'name':x['display_name']} for x in selected[:8]],
                'groups':[],'duration_ms':round((time.monotonic()-t0)*1000)}
    car=selected[0]
    y=year if year is not None else query_year(q)
    tr=trim or query_trim(q)
    co=condition or query_condition(q)
    # Query is intentionally DB-only. Never invoke a connector here.
    rows=storage.price_rows(car['catalog_id'],y,tr,co)
    now=datetime.now(timezone.utc)
    groups=[]
    for r in rows:
        age=(now-r['computed_at']).total_seconds() if r['computed_at'] else 999999999
        # Old prices cannot silently masquerade as current prices.
        if age>86400:continue
        status='fresh' if age<=7200 else 'stale'
        groups.append({
          'segment_key':r['segment_key'],
          'vehicle':car['display_name'],'year':r['model_year'],
          'year_system':r['year_system'],'trim':r['trim_name'],
          'transmission':r['transmission'], 'fuel_type':r['fuel_type'], 'condition':r['vehicle_condition'],
          'mileage_band':r['mileage_band'],'body_condition':r['body_condition'],
          'low_toman':r['low_toman'],'median_toman':r['median_toman'],
          'high_toman':r['high_toman'],'sample_count':r['sample_count'],
          'source_count':r['source_count'],'confidence':r['confidence'],
          'updated_at':iso(r['computed_at']),'status':status,
          'sources':sorted({a['source_code'] for a in r['ads']}),
          'ads':[{'source':a['source_code'],'url':a['url'],'price_toman':a['price_toman']}
                  for a in r['ads'] if str(a['url']).startswith('https://')]
        })
    if not groups:
        # Queue the request for next independent worker tick. A pending job
        # does NOT block the user while scraping and has no invented price.
        try:storage.request_refresh(car['catalog_id'],y,tr)
        except Exception:pass
        return {'status':'no_data','vehicle':car['display_name'],
                'message':'هنوز آگهی معتبر کافی برای این خودرو نداریم. درخواست بررسی ثبت شد.',
                'groups':[], 'duration_ms':round((time.monotonic()-t0)*1000)}
    return {'status':'ok','vehicle':car['display_name'],
            'groups':groups[:12],'message':'قیمت‌های پیشنهادی آگهی‌ها؛ نه قیمت قطعی معامله.',
            'duration_ms':round((time.monotonic()-t0)*1000)}


@app.get('/api/v1/sources/status')
def sources_status(_=Depends(admin_only)):
    rows,schedule,coverage=storage.source_statuses()
    return {'sources':[{**r,'access_verified_at':iso(r['access_verified_at']),
                         'last_attempt_at':iso(r['last_attempt_at']),
                         'last_success_at':iso(r['last_success_at'])} for r in rows],
            'last_scheduler_run':{**schedule,'scheduled_for':iso(schedule['scheduled_for']),
                                  'started_at':iso(schedule['started_at']),
                                  'finished_at':iso(schedule['finished_at'])} if schedule else None,
            'priced_segments':coverage}


class SourceState(BaseModel):
    enabled:bool


@app.post('/api/v1/admin/sources/{code}')
def admin_source(code:str,data:SourceState,_=Depends(admin_only)):
    try:storage.set_source(code,data.enabled)
    except KeyError:raise HTTPException(404,'Source not found')
    return {'status':'ok','code':code,'enabled':data.enabled}


@app.post('/api/v1/admin/refresh',status_code=202)
def admin_refresh(_=Depends(admin_only)):
    # Worker polls this queue; web API never executes collection.
    with storage.connection() as db:
        with db.cursor() as cur:
            cur.execute('INSERT INTO refresh_requests(vehicle_catalog_id,model_year,trim_name) VALUES(NULL,NULL,NULL) RETURNING id')
            request_id=cur.fetchone()['id']
        db.commit()
    return {'status':'queued','request_id':request_id}


class CatalogItem(BaseModel):
    brand:str=Field(min_length=2,max_length=100)
    model:str=Field(min_length=1,max_length=120)
    display_name:str=Field(min_length=2,max_length=150)
    aliases:list[str]=Field(default_factory=list,max_length=12)


@app.post('/api/v1/admin/vehicles',status_code=201)
def admin_vehicle(item:CatalogItem,_=Depends(admin_only)):
    # Admin additions only; never assigned a guessed model-year or daily price.
    ident=hashlib.sha256((normalize(item.brand)+'|'+normalize(item.model)).encode()).hexdigest()[:16]
    with storage.connection() as db:
        with db.cursor() as cur:
            cur.execute('''INSERT INTO vehicle_models(catalog_id,brand,model,display_name,search_text)
               VALUES(%s,%s,%s,%s,%s) ON CONFLICT(catalog_id) DO UPDATE SET
               display_name=EXCLUDED.display_name,search_text=EXCLUDED.search_text
               RETURNING catalog_id''',
               (ident,item.brand,item.model,item.display_name,item.display_name))
            for alias in [item.display_name,*item.aliases]:
                cur.execute('''INSERT INTO vehicle_aliases(vehicle_catalog_id,alias_text,alias_normalized)
                  VALUES(%s,%s,%s) ON CONFLICT(vehicle_catalog_id,alias_normalized) DO NOTHING''',
                  (ident,alias[:150],normalize(alias)[:150]))
        db.commit()
    return {'id':ident,'name':item.display_name}


@app.get('/')
def index():
    path=DIST/'index.html'
    if not path.is_file():
        return JSONResponse(status_code=503,content={'status':'frontend_not_built',
              'message':'The frontend build output is missing from this deployment.'})
    return FileResponse(path)


if (DIST/'assets').is_dir():
    app.mount('/assets',StaticFiles(directory=str(DIST/'assets')),name='assets')
