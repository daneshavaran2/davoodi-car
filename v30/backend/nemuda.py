"""Attribution-safe Nemuda aggregate prices, separate from individual listings.

Source documentation: https://nemuda.com/data ; CC BY 4.0. Values represent
used, healthy-body cars, not zero-km cars or identifiable listings.
The API cannot be verified inside this build environment. Parsing is fail-closed.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
import json
import os
from urllib.request import Request, urlopen
from urllib.parse import urlparse, quote
from urllib.error import HTTPError, URLError

from .domain import normalize

API_ROOT='https://api.nemuda.com/api/market/vehicles/'
PUBLIC_ROOT='https://nemuda.com/'

class NemudaError(RuntimeError):
    def __init__(self,code,message): super().__init__(message);self.code=code

def _load_json(url, timeout=12):
    if not url.startswith(API_ROOT): raise NemudaError('UNSAFE_URL','Unknown upstream URL')
    try:
        with urlopen(Request(url,headers={'Accept':'application/json','User-Agent':'DavoodiCar/30.4 (CC BY attribution client)'}),timeout=timeout) as response:
            if 'json' not in response.headers.get('content-type','').lower():raise NemudaError('PARSER_CHANGED','Unexpected response type')
            data=response.read(3_000_001)
            if len(data)>3_000_000:raise NemudaError('TOO_LARGE','Upstream JSON exceeds limit')
            return json.loads(data)
    except HTTPError as e:raise NemudaError('HTTP_'+str(e.code),'Upstream HTTP error') from e
    except (URLError,TimeoutError) as e:raise NemudaError('NETWORK_ERROR','Unable to reach Nemuda API') from e
    except (ValueError,UnicodeError) as e:raise NemudaError('PARSER_CHANGED','Invalid JSON response') from e

def _instant(value):
    try:
        d=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return d.replace(tzinfo=timezone.utc) if not d.tzinfo else d.astimezone(timezone.utc)
    except (ValueError,TypeError):return None

def _number(value):
    if isinstance(value,bool):return None
    if isinstance(value,int):return value
    if isinstance(value,float) and value.is_integer():return int(value)
    return None

def parse_aggregate(item, *, catalog_id, name, path, now=None):
    """Reject non-leaf, low-coverage, unknown-year or inconsistent values."""
    if not isinstance(item,dict):return None
    price=_number(item.get('price'))
    rng=item.get('priceRange')
    low=_number(rng.get('low')) if isinstance(rng,dict) else None
    high=_number(rng.get('high')) if isinstance(rng,dict) else None
    points=_number(item.get('dataPoints'))
    year=_number(item.get('modelYear'))
    display_year=_number(item.get('displayYear'))
    calendar=item.get('yearCalendar')
    computed=_instant(item.get('computedAt'))
    coverage=item.get('coverage')
    if coverage not in ('solid','limited') or not all(isinstance(v,int) for v in (price,low,high,points)):
        return None
    if not 0<low<=price<=high or points<10:return None
    if calendar not in ('jalali','gregorian') or not isinstance(year,int) or not isinstance(display_year,int):return None
    if calendar=='jalali' and not 1300<=year<=1500:return None
    if calendar=='gregorian' and not 1900<=display_year<=2100:return None
    if not computed or computed>(now or datetime.now(timezone.utc))+timedelta(hours=1):return None
    if (now or datetime.now(timezone.utc))-computed>timedelta(hours=48):return None
    if not path.startswith('car/') or any(p in ('.','..','') for p in path.split('/')):return None
    # This is a source page link, not a per-ad link. The exact endpoint is
    # retrieved using a documented category/brand/model/year path.
    url=PUBLIC_ROOT+path
    return dict(source_code='nemuda',source_key=path,vehicle_catalog_id=catalog_id,
        vehicle_label=name,trim_name=str(item.get('name') or item.get('title') or ''),
        model_year=display_year,year_system=calendar,
        low_toman=low,median_toman=price,high_toman=high,
        data_points=points,total_count=_number(item.get('totalCount')),
        coverage=coverage,window_days=_number(item.get('windowDays')),
        source_url=url,computed_at=computed)

def _walk(obj, path=()):
    """Conservative discovery: only leaves with explicit year + price fields."""
    if isinstance(obj,list):
        for v in obj:yield from _walk(v,path)
    elif isinstance(obj,dict):
        if isinstance(obj.get('priceRange'),dict) and obj.get('modelYear') is not None:
            yield obj,path
        for k,v in obj.items():
            if isinstance(v,(dict,list)):
                yield from _walk(v,path+(k,))

def _match_catalog(label,cars,aliases):
    """Require a unique exact car name or its alias; do not fuzzy-match trims."""
    label=normalize(label or '')
    if not label:return None
    names={}
    for c in cars:
        for v in (c['display_name'],c['brand']+' '+c['model'],c['model']):
            n=normalize(v)
            if n and len(n)>=6 and (label==n or label.startswith(n+' ') or label.endswith(' '+n)):
                names[c['catalog_id']]=c
    for a in aliases:
        alias=normalize(a['alias_text'])
        if len(alias)>=5 and (alias==label or label.startswith(alias+' ') or label.endswith(' '+alias)):
            cid=a['vehicle_catalog_id']
            for c in cars:
                if c['catalog_id']==cid:names[cid]=c;break
    if not names:return None
    ranked=sorted(names.values(),key=lambda x:len(normalize(x['display_name'])),reverse=True)
    if len(ranked)>1 and len(normalize(ranked[0]['display_name']))==len(normalize(ranked[1]['display_name'])):return None
    return ranked[0]

def _paths_from_index(index,max_paths=60):
    """Only use URLs explicitly supplied by the index; never invent slugs."""
    found=[]
    def visit(o,trail=()):
        if isinstance(o,list):
            for i in o:visit(i,trail)
        elif isinstance(o,dict):
            slug=o.get('slug')
            if isinstance(slug,str) and 0<len(slug)<100 and '/' not in slug and slug not in ('.','..'):
                trail=trail+(slug,)
            year=o.get('displayYear') or o.get('modelYear')
            if isinstance(year,int) and len(trail)>=3 and trail[0]=='car' and 1300<=year<=2100:
                found.append('/'.join(trail[:3])+'/'+str(year))
            for k,v in o.items():
                if k in ('apiUrl','api_url','url','path','href') and isinstance(v,str):
                    if v.startswith(API_ROOT):p=v[len(API_ROOT):]
                    elif v.startswith('/api/market/vehicles/'):p=v[len('/api/market/vehicles/'):]
                    else:continue
                    if p.startswith('car/') and p.count('/')>=3 and all(x not in ('..','.') for x in p.split('/')):
                        found.append(p)
                if isinstance(v,(dict,list)):visit(v,trail)
    visit(index)
    return list(dict.fromkeys(found))[:max_paths]

def collect_records(*, fetch=_load_json, max_paths=60):
    index=fetch(API_ROOT+'index')
    # A published index might contain leaf figures, or link to year endpoints.
    paths=_paths_from_index(index,max_paths)
    explicit=os.getenv('NEMUDA_TARGET_PATHS','').strip()
    if explicit:
        paths=list(dict.fromkeys([p.strip().strip('/') for p in explicit.split(',') if p.strip()]))[:max_paths]
    results=[]
    for path in paths:
        if not path.startswith('car/') or path.count('/')<3 or '?' in path or '#' in path:continue
        data=fetch(API_ROOT+quote(path,safe='/'))
        for item,_ in _walk(data):
            results.append((path,item))
    if not paths:
        raise NemudaError('INDEX_SHAPE_UNVERIFIED','Index did not expose documented year-level paths; configure NEMUDA_TARGET_PATHS using verified API paths')
    return results

def save_records(db,cars,aliases,records,*,now=None):
    now=now or datetime.now(timezone.utc)
    saved=0;skipped=0
    for path,item in records:
        # Source must supply a descriptive car name, not merely a generic brand.
        label=item.get('displayName') or item.get('fullName') or item.get('name') or item.get('title')
        car=_match_catalog(label,cars,aliases)
        if not car:skipped+=1;continue
        row=parse_aggregate(item,catalog_id=car['catalog_id'],name=car['display_name'],path=path,now=now)
        if not row:skipped+=1;continue
        with db.cursor() as cur:
            cur.execute('''INSERT INTO aggregate_vehicle_prices(source_code,source_key,vehicle_catalog_id,vehicle_label,
            trim_name,model_year,year_system,low_toman,median_toman,high_toman,data_points,total_count,
            coverage,window_days,source_url,computed_at)
            VALUES (%(source_code)s,%(source_key)s,%(vehicle_catalog_id)s,%(vehicle_label)s,%(trim_name)s,
            %(model_year)s,%(year_system)s,%(low_toman)s,%(median_toman)s,%(high_toman)s,%(data_points)s,
            %(total_count)s,%(coverage)s,%(window_days)s,%(source_url)s,%(computed_at)s)
            ON CONFLICT(source_code,source_key) DO UPDATE SET
            low_toman=EXCLUDED.low_toman,median_toman=EXCLUDED.median_toman,high_toman=EXCLUDED.high_toman,
            data_points=EXCLUDED.data_points,total_count=EXCLUDED.total_count,coverage=EXCLUDED.coverage,
            window_days=EXCLUDED.window_days,source_url=EXCLUDED.source_url,computed_at=EXCLUDED.computed_at,
            fetched_at=NOW(),trim_name=EXCLUDED.trim_name''',row)
        saved+=1
    return saved,skipped

def refresh(db,cars,aliases,fetch=_load_json):
    """Fail closed; prior successful snapshots survive all upstream failures."""
    now=datetime.now(timezone.utc)
    with db.cursor() as cur:
        cur.execute("SELECT enabled FROM aggregate_market_sources WHERE code='nemuda'")
        state=cur.fetchone()
        if not state or not state['enabled']:return {'status':'disabled'}
        cur.execute("UPDATE aggregate_market_sources SET last_attempt_at=%s WHERE code='nemuda'",(now,))
    db.commit()
    try:
        records=collect_records(fetch=fetch,max_paths=int(os.getenv('NEMUDA_MAX_PATHS','60')))
        saved,skipped=save_records(db,cars,aliases,records,now=now)
        with db.cursor() as cur:
            cur.execute('''UPDATE aggregate_market_sources SET rows_saved=%s,last_error_code=%s,last_error_detail=%s,
                last_success_at=CASE WHEN %s>0 THEN NOW() ELSE last_success_at END
                WHERE code='nemuda' ''',(saved,None if saved else 'NO_MATCHED_AGGREGATES',None if saved else 'No verified model/year could be mapped',saved))
        db.commit()
        return {'status':'ok' if saved else 'no_matches','saved':saved,'skipped':skipped}
    except Exception as exc:
        db.rollback()
        code=exc.code if isinstance(exc,NemudaError) else 'PARSER_CHANGED'
        with db.cursor() as cur:
            cur.execute("UPDATE aggregate_market_sources SET last_error_code=%s,last_error_detail=%s WHERE code='nemuda'",
                (code,str(exc)[:150] if isinstance(exc,NemudaError) else 'Unexpected upstream schema'))
        db.commit()
        return {'status':'error','error_code':code}