"""Pure car-name matching, asking-price validation and robust pricing.

No price is ever generated from the catalog, an LLM, or a search snippet.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import hashlib
import ipaddress
import math
import re
import statistics
from urllib.parse import urlsplit

_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')
EN_ALIASES = {
    'santa fe': 'سانتافه', 'santafe': 'سانتافه', 'hyundai santa fe':'هیوندای سانتافه',
    'lifan 820':'لیفان 820', 'toyota camry':'تویوتا کمری',
    'peugeot 207':'پژو 207i', 'peugeot 207i':'پژو 207i',
    'fidelity prime':'فیدلیتی پرایم', 'fidelity':'فیدلیتی',
}
TRIM_TERMS = {
    'توربو اتومات':'توربو اتومات', 'توربو اتوماتیک':'توربو اتومات',
    'توربو دستی':'توربو دستی', 'اتوماتیک':'اتومات', 'اتومات':'اتومات',
    'دنده ای':'دستی', 'دنده‌ای':'دستی', 'دستی':'دستی',
    'پرستیژ':'پرستیژ', 'پرایم':'پرایم', 'الیت':'الیت',
    'پانوراما':'پانوراما', 'تیپ ۲':'تیپ 2', 'تیپ ۳':'تیپ 3', 'تیپ ۵':'تیپ 5',
    'type 2':'تیپ 2', 'type 5':'تیپ 5',
}
UNPRICED = ('توافقی','تماس بگیرید','تماس بگيريد','قیمت توافقی','اقساط',
            'پیش پرداخت','پیش‌پرداخت','بیعانه','ودیعه','قسط','رهن','اجاره',
            'لوازم یدکی','قطعات')
GOOD_HOSTS = {
    'divar': ('divar.ir',), 'bama': ('bama.ir',),
    'sheypoor': ('sheypoor.com',), 'hamrah': ('hamrah-mechanic.com',),
    'karnameh': ('karnameh.com',), 'khodro45': ('khodro45.com',),
}


def normalize(value):
    text=str(value or '').translate(_DIGITS).casefold().replace('ي','ی').replace('ك','ک').replace('‌',' ')
    text=re.sub(r'[^\w\s]+',' ',text)
    return re.sub(r'\s+',' ',text).strip()


def normalize_query(value):
    q=normalize(value)
    for en,fa in sorted(EN_ALIASES.items(), key=lambda p:-len(p[0])):
        q=re.sub(r'(?<!\w)'+re.escape(normalize(en))+r'(?!\w)',normalize(fa),q)
    return q


def query_year(q):
    # A year is a request filter only, never an inferred ad year.
    ys=[int(v) for v in re.findall(r'(?<!\d)(?:13\d{2}|14\d{2}|19\d{2}|20\d{2})(?!\d)',normalize(q))]
    return ys[0] if ys else None


def query_trim(q):
    nq=normalize(q)
    for raw,canonical in sorted(TRIM_TERMS.items(), key=lambda kv:-len(kv[0])):
        if re.search(r'(?<!\w)'+re.escape(normalize(raw))+r'(?!\w)',nq):
            return canonical
    return None


def query_condition(q):
    nq=normalize(q)
    if any(v in nq for v in ('صفر کیلومتر','صفر کيلومتر','صفر','آکبند')):return 'new'
    if any(v in nq for v in ('کارکرده','دست دوم')):return 'used'
    return None


def _inside(haystack,needle):
    return bool(needle and re.search(r'(?<!\w)'+re.escape(needle)+r'(?!\w)',haystack))


def find_vehicle(q, catalog, aliases=()):
    """Return selection candidates; do not silently merge distinct catalog models.

    The longest explicit catalog match wins. When fuzzy suggestions are
    possible, they are suggestions rather than accepted vehicle IDs.
    """
    from difflib import get_close_matches
    text=normalize_query(q)
    text=re.sub(r'(?<!\d)(?:13\d{2}|14\d{2}|19\d{2}|20\d{2})(?!\d)', ' ', text)
    text=re.sub(r'\s+',' ',text).strip()
    candidates=[]
    alias_by_id={}
    for item in aliases:
        alias_by_id.setdefault(str(item['vehicle_catalog_id']),[]).append(item['alias_text'])
    for car in catalog:
        names={normalize(car.get('display_name')),normalize(car.get('search_text')),
               normalize(f"{car.get('brand','')} {car.get('model','')}"),
               normalize(car.get('model'))}
        names.update(normalize(a) for a in alias_by_id.get(str(car['catalog_id']),[]))
        matched=[s for s in names if s and _inside(text,s)]
        if matched:
            score=max(len(s) for s in matched)
            # standalone model-only terms like '820' are unsafe if another
            # model uses the same number. Resolve ties, never choose randomly.
            candidates.append((score,car))
    if candidates:
        max_score=max(score for score,_ in candidates)
        matches=[row for score,row in candidates if score==max_score]
        return {'status':'matched' if len(matches)==1 else 'needs_selection',
                'matches':matches[:10], 'corrected':False}
    choices=[(car['display_name'],car) for car in catalog]
    close=get_close_matches(text,[normalize(n) for n,_ in choices],n=5,cutoff=.77)
    suggestions=[car for n,car in choices if normalize(n) in close]
    return {'status':'needs_selection' if suggestions else 'not_found',
            'matches':suggestions[:5], 'corrected':bool(suggestions)}


def normalized_trim(raw):
    if raw is None:return None
    s=normalize(raw)
    if not s or s in ('نامشخص','unknown','سایر'):return None
    for candidate,canonical in sorted(TRIM_TERMS.items(),key=lambda kv:-len(kv[0])):
        if normalize(candidate)==s:return canonical
    return s


def valid_ad_url(url,source):
    try:
        u=urlsplit(str(url or '').strip())
        host=(u.hostname or '').lower().removeprefix('www.')
        return u.scheme=='https' and not u.username and not u.password and u.port in (None,443) and (
            any(host==allowed or host.endswith('.'+allowed) for allowed in GOOD_HOSTS[source]))
    except (ValueError,KeyError,TypeError):return False


def classify_error(exc):
    import socket
    from urllib.error import HTTPError, URLError
    if isinstance(exc,HTTPError):
        return 'HTTP_403' if exc.code==403 else 'HTTP_429' if exc.code==429 else 'HTTP_5XX' if exc.code>=500 else 'HTTP_ERROR'
    if isinstance(exc,(TimeoutError,)):return 'TIMEOUT'
    if isinstance(exc,(socket.gaierror, URLError, OSError)):return 'DNS_TLS'
    msg=str(exc).casefold()
    if 'captcha' in msg or 'challenge' in msg:return 'CAPTCHA_OR_CHALLENGE'
    if 'timeout' in msg:return 'TIMEOUT'
    return 'PARSER_CHANGED' if isinstance(exc,(ValueError,KeyError)) else 'ERROR'


def clean_listing(payload,source,catalog_lookup,now=None):
    """Strict adapter contract; returns (normalized, reject reason)."""
    now=now or datetime.now(timezone.utc)
    if not isinstance(payload,dict):return None,'MALFORMED_ITEM'
    url=payload.get('url')
    if not valid_ad_url(url,source):return None,'INVALID_URL'
    title=str(payload.get('title') or '')[:200]
    if payload.get('raw_type')!='listing':return None,'NOT_A_SALE_LISTING'
    if any(word in normalize(title+' '+str(payload.get('price_text') or '')) for word in map(normalize,UNPRICED)):
        return None,'NON_CASH_PRICE'
    price=payload.get('price_toman')
    if price is None and payload.get('price') is not None:
        price=payload.get('price')
    # Explicit unit required: ambiguity between toman/rial is not acceptable.
    unit=normalize(payload.get('currency') or ('toman' if payload.get('price_toman') is not None else ''))
    if unit not in ('toman','irt','تومان','irr','ریال'):return None,'UNKNOWN_CURRENCY'
    if payload.get('price_toman') is not None and unit in ('irr','ریال'):
        return None,'CURRENCY_FIELD_CONFLICT'
    try:
        if isinstance(price,bool):raise ValueError
        numeric=int(str(price).translate(_DIGITS).replace(',','').replace('٬',''))
    except (ValueError,TypeError):return None,'INVALID_PRICE'
    if unit in ('irr','ریال'):
        if numeric%10:return None,'RIAL_CONVERSION_UNCERTAIN'
        numeric//=10
    if not 50_000_000 <= numeric <= 100_000_000_000:return None,'PRICE_OUT_OF_RANGE'
    year=payload.get('model_year')
    try:
        year=int(str(year).translate(_DIGITS))
    except (ValueError,TypeError):return None,'MISSING_YEAR'
    if not (1350<=year<=1450 or 1950<=year<=2036):return None,'INVALID_YEAR'
    year_system='jalali' if year<1500 else 'gregorian'
    if payload.get('year_system') and payload['year_system']!=year_system:return None,'YEAR_SYSTEM_CONFLICT'
    raw_model=str(payload.get('model') or '').strip()
    raw_brand=str(payload.get('brand') or '').strip()
    if not raw_model or not raw_brand:return None,'MISSING_MODEL'
    title_model=normalize(raw_model)
    title_normalized=normalize(title)
    model_words=title_model.split()
    if not title_normalized or not all(_inside(title_normalized,w) for w in model_words):
        return None,'MODEL_TITLE_CONFLICT'
    catalog_id=catalog_lookup.get((normalize(raw_brand),normalize(raw_model)))
    if catalog_id is None:return None,'UNRECOGNIZED_MODEL'
    # Compare explicitly stated title year to the structured year without
    # accepting partial CE/Shamsi arithmetic as definitive model year.
    title_year=query_year(title)
    if title_year is not None and title_year!=year:
        return None,'YEAR_TITLE_CONFLICT'
    title_trim=query_trim(title)
    trim=normalized_trim(payload.get('trim'))
    if title_trim and trim and title_trim!=trim:return None,'TRIM_TITLE_CONFLICT'
    trim=trim or title_trim
    if not trim:
        return None,'MISSING_TRIM'  # do not pool unknown variants
    cond=str(payload.get('condition') or '').lower()
    if cond not in ('new','used'):return None,'UNKNOWN_CONDITION'
    km=payload.get('mileage_km')
    try:km=int(str(km).translate(_DIGITS)) if km is not None else None
    except ValueError:return None,'INVALID_MILEAGE'
    if cond=='new' and km not in (None,0):return None,'CONFLICTING_CONDITION'
    if cond=='used' and (km is None or not 0<km<=2_000_000):return None,'UNKNOWN_MILEAGE'
    fuel=normalize(payload.get('fuel_type') or '') or 'unknown'
    fuel_alias={'بنزینی':'petrol','بنزین':'petrol','petrol':'petrol',
                'گازوئیلی':'diesel','diesel':'diesel','دیزل':'diesel',
                'برقی':'electric','electric':'electric','هیبرید':'hybrid',
                'hybrid':'hybrid','دوگانه سوز':'dual','cng':'dual'}
    fuel=fuel_alias.get(fuel,'unknown')
    trans=normalize(payload.get('transmission') or '') or 'unknown'
    if trans in ('اتوماتیک','اتومات','automatic','at'):trans='automatic'
    if trans in ('دستی','manual','mt'):trans='manual'
    if trans not in ('automatic','manual'):return None,'UNKNOWN_TRANSMISSION'
    body=normalize(payload.get('body_condition') or '') or 'unknown'
    if body in ('سالم','بدون رنگ','factory'):body='original'
    if body in ('رنگ','رنگ شده','painted'):body='painted'
    if body in ('تصادفی','damaged'):body='damaged'
    if body not in ('original','painted','damaged','unknown'):body='unknown'
    published=payload.get('published_at')
    if published:
        try:
            dt=datetime.fromisoformat(str(published).replace('Z','+00:00'))
            if dt.tzinfo is None:raise ValueError
            if dt<now-timedelta(days=14) or dt>now+timedelta(hours=1):return None,'STALE_OR_FUTURE_LISTING'
            published=dt.astimezone(timezone.utc)
        except ValueError:return None,'INVALID_PUBLICATION_DATE'
    else:published=None
    external_id=str(payload.get('external_id') or hashlib.sha256(url.encode()).hexdigest()[:24])
    return {'source':source,'external_id':external_id,'url':url,'title':title,
            'catalog_id':catalog_id,'brand':raw_brand,'model':raw_model,'year':year,
            'year_system':year_system,'trim':trim,'condition':cond,'mileage_km':km,
            'transmission':trans,'fuel_type':fuel,'body_condition':body,'price_toman':numeric,
            'published_at':published,'observed_at':now,
            'city':str(payload.get('city') or '')[:64]},None


def mileage_band(km,condition):
    if condition=='new':return 'zero'
    if km is None:return 'unknown'
    if km<50000:return '0-49k'
    if km<100000:return '50-99k'
    if km<150000:return '100-149k'
    return '150k+'


def grouping_key(a):
    return (a['catalog_id'],a['year'],a['year_system'],a['trim'],a['condition'],
            a['transmission'],a['fuel_type'],a['body_condition'],mileage_band(a['mileage_km'],a['condition']))


def _nearest(values,q):
    # Exact nearest-rank percentile, with no interpolated/invented price.
    index=max(0,min(len(values)-1, math.ceil(q*len(values))-1))
    return values[index]


def quote(adverts,min_ads=5):
    """Return None for insufficient evidence, otherwise 20th–80th if >=10."""
    by_url={}
    for x in adverts:
        if x['price_toman']>0:by_url[(x['source'],x['external_id'])]=x
    ads=list(by_url.values())
    if len(ads)<min_ads:return None
    keys={grouping_key(x) for x in ads}
    if len(keys)!=1:raise ValueError('mixed vehicle groups')
    prices=sorted(int(x['price_toman']) for x in ads)
    if len(prices)>=10:
        low=_nearest(prices,.20); high=_nearest(prices,.80)
    else:
        low,high=prices[0],prices[-1]
    med=round(statistics.median(prices))
    sources=sorted({x['source'] for x in ads})
    confidence='high' if len(prices)>=10 and len(sources)>=2 else 'medium' if len(prices)>=10 else 'low'
    return {'low':low,'median':med,'high':high,'count':len(prices),'sources':sources,
            'confidence':confidence,'group_key':next(iter(keys))}
