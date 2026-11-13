"""Paginated, resumable public-page crawler for Bama, Divar and Hamrah.

Only public HTTPS pages of the selected source are visited. Does not log in,
bypass CAPTCHAs, retry after 403/429, or discover non-public JSON endpoints.
Next pages are followed only when linked by the source itself; there is no
guessing of page numbers, API endpoints, car prices, or missing ad attributes.
"""
from __future__ import annotations
import os
import re
import time
from urllib.parse import quote, urlencode, urljoin, urlsplit, parse_qs
from bs4 import BeautifulSoup

from .connectors import SourceUnavailable
from .domain import normalize
from .legacy_market.common import fetch_html, links_from_html, matches_model, same_host, token_score
from .legacy_market.extract import listing_cards_from_html, detail_fields
from .legacy_market.browser import source_session
from .legacy_market import bama, divar, hamrah
from .legacy_bridge import _safe_listing, _translate_error
from .legacy_details import extract_public_features

HOSTS={'bama':'bama.ir','divar':'divar.ir','hamrah':'hamrah-mechanic.com'}
_DETAIL={'bama':bama._is_detail,'divar':divar._is_detail,'hamrah':hamrah._is_detail}
NEXT_TEXT=re.compile(r'^(?:بعدی|صفحه\s*بعد|صفحه\s*بعدی|next\s*(?:page)?|more|بیشتر|›|»|→)$',re.I)
PAGE_KEYS=('page','p','pageNumber','page_number','cursor','offset')

def _positive(name,default,maximum):
    try:return max(1,min(maximum,int(os.getenv(name,str(default)))))
    except ValueError:return default

def allowed_page(url,code,*,parent=None):
    """No arbitrary redirects/hosts; only same-site list and pagination URLs."""
    if code not in HOSTS:return False
    try:
        u=urlsplit(str(url))
        if u.scheme!='https' or u.username or u.password or u.port not in (None,443):return False
        if not same_host(url,HOSTS[code]) or len(str(url))>600:return False
        if _DETAIL[code](url):return False
        if not parent:return True
        original=urlsplit(parent)
        if u.path.rstrip('/')!=original.path.rstrip('/'):return False
        nq=parse_qs(u.query,keep_blank_values=True)
        pq=parse_qs(original.query,keep_blank_values=True)
        # Search query and all non-pagination filters must remain unchanged.
        for key in set(nq)|set(pq):
            if key not in PAGE_KEYS and nq.get(key)!=pq.get(key):return False
        return any(nq.get(k)!=pq.get(k) for k in PAGE_KEYS)
    except (TypeError,ValueError):return False

def next_page_link(raw,page_url,code,seen=()):
    """Discover next link from HTML, without fabricating ?page=N URLs."""
    soup=BeautifulSoup(raw or '','html.parser')
    visited=set(seen)|{page_url}
    choices=[]
    for a in soup.select('a[href],link[href]'):
        href=a.get('href')
        if not href:continue
        dest=urljoin(page_url,href)
        if dest in visited or not allowed_page(dest,code,parent=page_url):continue
        rel=a.get('rel') or []
        rel=' '.join(rel) if isinstance(rel,list) else str(rel)
        label=(a.get('aria-label') or a.get_text(' ',strip=True) or '').strip().lower()
        if 'next' in rel.lower() or NEXT_TEXT.match(label):
            choices.append((0,dest))
        elif any(k in parse_qs(urlsplit(dest).query) for k in PAGE_KEYS):
            # Numbered page navigation is usable only when it is genuinely
            # displayed on the current page, not an imagined page endpoint.
            nums=re.findall(r'\d{1,5}',label)
            current=parse_qs(urlsplit(page_url).query)
            old=next((int(current[k][0]) for k in ('page','p','pageNumber') if k in current and current[k][0].isdigit()),1)
            if nums and int(nums[0])==old+1:choices.append((1,dest))
    return min(choices,key=lambda x:x[0])[1] if choices else None

def _seed_bama(car):
    base='https://bama.ir/car'
    raw=fetch_html(base,timeout=10)
    links=[(u,t) for u,t in links_from_html(raw,base) if allowed_page(u,'bama')]
    brand=car['brand'];model=car['model']
    seed=(bama._best_link(links,brand,model) or
          bama._best_link(links,brand) or bama._best_link(links,'',model))
    if not seed:raise SourceUnavailable('CATEGORY_NOT_FOUND','Bama model/brand link absent from public category page')
    if not allowed_page(seed,'bama'):raise SourceUnavailable('INVALID_PAGE_URL','Bama returned unsafe model link')
    if normalize(model) not in normalize(seed):
        # The first link may be brand only; check its listed model link.
        raw2=fetch_html(seed,timeout=9)
        model_url=bama._best_link(links_from_html(raw2,seed),brand,model)
        if model_url and allowed_page(model_url,'bama'):seed=model_url
    return seed

def _seed_divar(car):
    term=' '.join(x for x in (car.get('model'),car.get('brand')) if x)
    return 'https://divar.ir/s/tehran/car?'+urlencode({'q':term})

def _seed_hamrah(car):
    base='https://www.hamrah-mechanic.com/cars-for-sale/'
    raw=fetch_html(base,timeout=10)
    ranked=[]
    for url,label in links_from_html(raw,base):
        if not allowed_page(url,'hamrah') or '/cars-for-sale/' not in url:continue
        if hamrah._is_detail(url):continue
        score=token_score('',car.get('model'),label)
        if score>=.75:ranked.append((score,url))
    return max(ranked)[1] if ranked else base

def seed_url(code,car):
    if code=='bama':return _seed_bama(car)
    if code=='divar':return _seed_divar(car)
    if code=='hamrah':return _seed_hamrah(car)
    raise SourceUnavailable('UNSUPPORTED_SOURCE','Unsupported crawler source')

def _detail_enrich(card):
    # Unknown detail fields must stay unknown; never overwrite a card with a
    # conflicting value from its detail page.
    try:
        html=fetch_html(card['url'],timeout=9)
        more=detail_fields(html,card['title'])
        card['_extras']=extract_public_features(html,card['url'])
        if more.get('title') and not matches_model('',card.get('_model') or '',more['title']):
            card['detail_mismatch']=True;return card
        if card.get('price') and more.get('price'):
            if abs(card['price']-more['price'])>max(50_000_000,card['price']*.05):
                card['price_conflict']=True;return card
        for key in ('price','year','mileage','published_at'):
            if more.get(key) is not None and card.get(key) is None:card[key]=more[key]
        if more.get('title'):card['title']=more['title']
        if more.get('content'):card['content']=(card.get('content') or '')+' '+more['content'][:2000]
    except RuntimeError as exc:
        error=_translate_error(exc)
        if error in ('HTTP_403','HTTP_429','CAPTCHA_OR_CHALLENGE'):
            raise SourceUnavailable(error,'Listing detail access denied by source') from exc
        card['detail_error']=error
    return card

def scan_model(code,car,*,start_url=None,max_pages=3,max_ads=40):
    """Returns (rows,next_link,metrics); next_link can be resumed next run."""
    start=start_url or seed_url(code,car)
    if not allowed_page(start,code):raise SourceUnavailable('INVALID_PAGE_URL','Not a public list URL')
    current=start;seen_pages=set();seen_ads=set();rows=[];pages=0;cards_seen=0
    detail_limit=_positive('PUBLIC_CRAWL_DETAILS_PER_MODEL',12,40)
    details=0
    max_pages=max(1,min(12,max_pages))
    max_ads=max(1,min(150,max_ads))
    with source_session():
        for _ in range(max_pages):
            if not current or current in seen_pages:break
            # A saved checkpoint must also pass the source-domain guard.
            if not allowed_page(current,code):raise SourceUnavailable('INVALID_PAGE_URL','Unsafe checkpoint link')
            seen_pages.add(current)
            try:raw=fetch_html(current,timeout=12)
            except RuntimeError as exc:
                raise SourceUnavailable(_translate_error(exc),'Public listing page unavailable') from exc
            pages+=1
            cards=listing_cards_from_html(raw,current,_DETAIL[code],limit=max_ads*4)
            cards_seen+=len(cards)
            for card in cards:
                if card['url'] in seen_ads:continue
                seen_ads.add(card['url'])
                if not matches_model(car['brand'],car['model'],card.get('title','')+' '+card.get('content','')):continue
                card['_model']=car['model']
                if details<detail_limit:
                    _detail_enrich(card);details+=1
                converted=_safe_listing(code,car,card)
                if converted:
                    converted['extra_fields']=card.get('_extras') or {}
                    if converted['extra_fields'].get('city'):
                        converted['city']=converted['extra_fields']['city']
                    rows.append(converted)
                if len(rows)>=max_ads:break
            following=next_page_link(raw,current,code,seen_pages)
            if len(rows)>=max_ads:
                return rows,following,{'pages':pages,'cards':cards_seen,'details':details}
            current=following
            if not current:break
    return rows,current,{'pages':pages,'cards':cards_seen,'details':details}

def crawl_catalog(code,catalog,checkpoint,priority_ids=()):
    """Walk the 660-model catalog across runs, persisting an explicit next URL.

    The Web/API request path is never involved. Priority user requests are
    scanned first without moving the background round-robin catalog cursor.
    """
    cars=sorted(catalog,key=lambda c:(normalize(c['brand']),normalize(c['model']),c['catalog_id']))
    if not cars:raise SourceUnavailable('EMPTY_CATALOG','No catalog entries')
    budget=_positive('PUBLIC_CRAWL_PAGES_PER_MODEL',3,12)
    model_limit=_positive('PUBLIC_CRAWL_MODELS_PER_RUN',3,12)
    max_depth=_positive('PUBLIC_CRAWL_MAX_DEPTH',25,150)
    max_ads=_positive('PUBLIC_CRAWL_ADS_PER_MODEL',60,150)
    index=int(checkpoint.get('catalog_index') or 0)%len(cars)
    depth=max(0,int(checkpoint.get('page_depth') or 0))
    current_id=checkpoint.get('vehicle_catalog_id')
    next_url=checkpoint.get('next_url')
    output=[];stats={'pages':0,'cards':0,'details':0,'models':0,'priority_models':0,'skipped_models':0,'errors':{}}
    deadline=time.monotonic()+_positive('PUBLIC_CRAWL_MAX_RUNTIME_SECONDS',150,1200)
    blocking=('HTTP_403','HTTP_429','CAPTCHA_OR_CHALLENGE')
    scanned_ids=set()

    # A requested model is useful immediately; do not wait for a full
    # 660-model sweep. Limit priorities to one per site/run.
    by_id={c['catalog_id']:c for c in cars}
    for pid in tuple(priority_ids)[:1]:
        if pid not in by_id:continue
        vehicle=by_id[pid]
        try:
            ads,_,metric=scan_model(code,vehicle,max_pages=budget,max_ads=max_ads)
        except SourceUnavailable as exc:
            if exc.code in blocking:raise
            stats['skipped_models']+=1
            stats['errors'][exc.code]=stats['errors'].get(exc.code,0)+1
            continue
        output.extend(ads);scanned_ids.add(pid)
        stats['priority_models']+=1
        for key in ('pages','cards','details'):stats[key]+=metric[key]
    for _ in range(model_limit):
        if time.monotonic()>deadline:break
        car=cars[index]
        if current_id!=car['catalog_id']:
            next_url=None;depth=0;current_id=car['catalog_id']
        if car['catalog_id'] in scanned_ids:
            # A priority fetch must not count as a repeated background fetch.
            index=(index+1)%len(cars);next_url=None;current_id=None;depth=0
            continue
        try:
            ads,resume,metric=scan_model(code,car,start_url=next_url,max_pages=budget,max_ads=max_ads)
        except SourceUnavailable as exc:
            if exc.code in blocking:raise
            # An unavailable catalogue model must not freeze progress for all
            # 660 models. Skip this model but retain the per-run error metric.
            stats['skipped_models']+=1
            stats['errors'][exc.code]=stats['errors'].get(exc.code,0)+1
            next_url=None;current_id=None;depth=0
            index=(index+1)%len(cars)
            continue
        output.extend(ads)
        stats['models']+=1
        for key in ('pages','cards','details'):stats[key]+=metric[key]
        depth+=metric['pages']
        if resume and depth<max_depth:
            next_url=resume
            break  # resume this model's linked pagination on the next tick
        next_url=None;current_id=None;depth=0
        index=(index+1)%len(cars)
    # Source-level URL dedup protects against repeated ads on neighboring pages.
    by_url={}
    for row in output:by_url[row['url']]=row
    return {'rows':list(by_url.values()),'checkpoint':{
        'catalog_index':index,'vehicle_catalog_id':current_id,
        'next_url':next_url,'page_depth':depth},'stats':stats}
