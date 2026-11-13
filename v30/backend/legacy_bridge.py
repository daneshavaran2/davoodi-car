"""Bounded public-page adapters imported from v29 into the v30 hourly worker.

For Bama, Divar and Hamrah the adapter uses ordinary public pages when an
approved JSON feed URL is not configured. No CAPTCHA bypass, proxy rotation,
authentication, or retry after 403/429. A site is not marked successful until
a real listing has passed strict v30 evidence checks.
"""
from __future__ import annotations
import os
import re
from urllib.parse import urlsplit
from .domain import normalize, query_trim, query_year, query_condition
from .connectors import SourceUnavailable
from .quality import explicit_price_matches

PILOT=('bama','divar','hamrah')
HOSTS={'bama':'bama.ir','divar':'divar.ir','hamrah':'hamrah-mechanic.com'}
DEFAULT_MODELS=('فیدلیتی پرایم','سانتافه','دنا پلاس توربو')

def pilot_mode(code):
    # Use the already implemented v29 public-page connectors automatically
    # for Bama, Divar and Hamrah when no licensed feed URL is configured.
    # Set SOURCE_*_MODE=feed to override with a provider's JSON API.
    if code not in PILOT:return False
    default='feed' if os.getenv('SOURCE_'+code.upper()+'_API_URL') else 'legacy_public'
    return os.getenv('SOURCE_'+code.upper()+'_MODE',default).strip().lower()=='legacy_public'

def _targets(catalog):
    wanted=[normalize(v) for v in os.getenv('PUBLIC_PILOT_MODELS',','.join(DEFAULT_MODELS)).split(',') if v.strip()]
    limit=max(1,min(6,int(os.getenv('PUBLIC_PILOT_CAR_LIMIT','2'))))
    seen=set();out=[]
    for target in wanted:
        options=[]
        for car in catalog:
            label=normalize(car.get('display_name',''))
            model=normalize(car.get('model',''))
            # Never search an unrelated vehicle due to a fuzzy name.
            if target==model or target==label or (target and label.endswith(' '+target)):
                options.append(car)
        if len(options)!=1:continue
        car=options[0]
        if car['catalog_id'] not in seen:
            seen.add(car['catalog_id']);out.append(car)
        if len(out)>=limit:break
    return out

def _check_runtime(code):
    # Ordinary public HTML and JavaScript pages only: no login, proxies,
    # CAPTCHA solver, CAPTCHA workarounds, or retries after 403/429.
    mode=os.getenv('MARKET_FETCH_MODE','playwright').strip().lower()
    if mode not in ('http','playwright'):
        raise SourceUnavailable('INVALID_MODE','Use MARKET_FETCH_MODE=http or playwright')
    return mode

def _translate_error(exc):
    txt=str(exc).lower()
    if '403' in txt or '401' in txt:return 'HTTP_403'
    if '429' in txt:return 'HTTP_429'
    if 'captcha' in txt or 'کپچا' in txt or 'verify you are human' in txt:return 'CAPTCHA_OR_CHALLENGE'
    if 'timeout' in txt or 'timed out' in txt:return 'TIMEOUT'
    if any(t in txt for t in ('name resolution','dns','connection','ارتباط')):return 'NETWORK_ERROR'
    if 'browser' in txt or 'playwright' in txt or 'مرورگر' in txt:return 'BROWSER_ERROR'
    return 'PARSER_CHANGED'

def _explicit_gear(text):
    n=normalize(text)
    automatic=any(x in n for x in ('اتوماتیک','اتومات','automatic','اتوماتيك','at gearbox','توربو اتومات'))
    manual=any(x in n for x in ('دنده ای','دستی','manual','گیربکس دستی','توربو دستی'))
    if automatic and manual:return None
    return 'automatic' if automatic else 'manual' if manual else None

def _safe_listing(code,car,card):
    from .legacy_market.common import same_host
    if not isinstance(card,dict) or card.get('detail_mismatch') or card.get('price_conflict') or card.get('detail_conflict'):return None
    url=str(card.get('url') or '')
    if not url.startswith('https://') or not same_host(url,HOSTS[code]):return None
    title=str(card.get('title') or '').strip()[:200]
    content=str(card.get('content') or '')[:1600]
    combined=title+' '+content
    # A bare price widget plus an unrelated 'تومان' fee is not price evidence.
    price=card.get('price')
    if not explicit_price_matches(price,combined):return None
    year=card.get('year') or query_year(title)
    # Named commercial variants outrank generic gearbox words (Prime vs AT).
    text_norm=normalize(combined)
    named=[name for name in ('پرایم','پرستیژ','الیت') if name in text_norm]
    if len(named)>1:return None
    trim=query_trim(combined) if named else (query_trim(title) or query_trim(combined))
    gear=_explicit_gear(combined)
    mileage=card.get('mileage')
    try:
        if isinstance(price,bool) or not (50_000_000<=int(price)<=100_000_000_000):return None
        if not (1350<=int(year)<=1450 or 1950<=int(year)<=2036):return None
        if mileage is not None:mileage=int(mileage)
    except (ValueError,TypeError):return None
    if not trim or not gear or mileage is None or not 0<=mileage<=2_000_000:return None
    # Explicit car mileage is required for used listings; zero-km requires
    # unequivocal zero-mileage text rather than only a numeric '0' widget.
    from safety_v24 import new_status
    status=new_status(combined,structured_mileage=mileage)
    if status is None:return None
    if status and mileage!=0:return None
    condition='new' if status else 'used'
    if condition=='used' and mileage<=0:return None
    from safety_v24 import body_group
    # The string 'شاسی سالم' is NOT evidence of collision damage.
    # Prefer a clearly labelled body-state field from the detail page.
    explicit_body=re.search(r'وضعیت\s*بدنه\s*[:：]?\s*(بدون\s*رنگ|دو\s*لکه\s*رنگ|چند\s*لکه\s*رنگ|رنگ\s*شده|تصادفی|فابریک)',normalize(combined))
    if explicit_body:
        mark=explicit_body.group(1)
        body=('original' if any(x in mark for x in ('بدون','فابریک')) else
              'damaged' if 'تصادفی' in mark else 'painted')
    else:
        # Unknown is safer than treating an unqualified chassis mention as damage.
        safe_text=re.sub(r'شاسی\s*سالم','',combined)
        category=body_group(safe_text)
        body={'clean':'original','painted':'painted','damaged':'damaged',
              'structural':'damaged','replaced':'damaged'}.get(category,'unknown')
    # The strict v30 validator verifies catalog identity, currency and year.
    return {'source':code,'external_id':urlsplit(url).path.rsplit('/',1)[-1][:120],
            'url':url,'title':title,'brand':car['brand'],'model':car['model'],
            'trim':trim,'model_year':int(year),'year_system':'jalali' if int(year)<1500 else 'gregorian',
            'condition':condition,'mileage_km':mileage,'body_condition':body,
            'transmission':gear,'fuel_type':None,'price_toman':int(price),
            'currency':'toman',
            # A normalized cash price clause is emitted ONLY after independently
            # verifying the amount in the local source text above.
            'price_text':'قیمت خودرو '+str(int(price))+' تومان',
            'raw_type':'listing','published_at':card.get('published_at'),'city':''}

def collect_public(code,catalog):
    """Only a few explicit pilot models per source; no 660-model crawling."""
    if code not in PILOT:raise SourceUnavailable('UNSUPPORTED_SOURCE','Not a legacy pilot site')
    _check_runtime(code)
    targets=_targets(catalog)
    if not targets:
        raise SourceUnavailable('NO_PILOT_TARGETS',
            'None of the pilot model names uniquely matches the local catalog')
    from .legacy_market import bama,divar,hamrah
    from .legacy_market.browser import source_session
    module={'bama':bama,'divar':divar,'hamrah':hamrah}[code]
    limit=max(1,min(20,int(os.getenv('PUBLIC_PILOT_AD_LIMIT','8'))))
    output=[];failures=[]
    for car in targets:
        try:
            with source_session():
                cards=module.search({'brand':car['brand'],'model':car['model']},limit=limit)
        except Exception as exc:
            failures.append(_translate_error(exc))
            # Stop immediately on a site access rejection. Never try other
            # transport, accounts, headers, proxies, or CAPTCHA solvers.
            if failures[-1] in ('HTTP_403','HTTP_429','CAPTCHA_OR_CHALLENGE'):
                raise SourceUnavailable(failures[-1],f'Public access blocked for {code}') from exc
            continue
        for card in cards[:limit]:
            row=_safe_listing(code,car,card)
            if row:output.append(row)
    if failures and not output:raise SourceUnavailable(failures[0],'Public-page source fetch failed; inspect worker source audit')
    if not output:raise SourceUnavailable('NO_VERIFIED_LISTINGS',
            'Pages were parsed but no listing passed strict model/year/trim/price checks')
    # Real successful raw parsing is still subject to v30.clean_listing.
    return output
