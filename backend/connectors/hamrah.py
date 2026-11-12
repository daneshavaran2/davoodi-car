"""Hamrah mechanic public listing connector, including hydrated JS cards."""
import os,re
from urllib.parse import urljoin
from .common import fetch_html,token_score,matches_model,same_host,links_from_html
from .extract import listing_cards_from_html, detail_fields

BASE='https://www.hamrah-mechanic.com/cars-for-sale/'
DOMAIN='hamrah-mechanic.com'


def _is_detail(url):
    return same_host(url,DOMAIN) and bool(re.search(r'/cars-for-sale/[^/]+/[^/]+/\d+/?$',url))


def search(vehicle,limit=25):
    brand=vehicle.get('brand') or '';model=vehicle.get('model') or ''
    raw=fetch_html(BASE,timeout=8)
    # Do not conclude that a model has no ads just because it is absent from
    # the first N cards on a generic "all cars" landing page.
    pages=[(BASE,raw)]
    candidates=[]
    for url,text in links_from_html(raw,BASE):
        if not same_host(url,DOMAIN) or _is_detail(url) or '/cars-for-sale/' not in url:
            continue
        if token_score('',model,text)<.75 or not model:
            continue
        if url not in candidates:candidates.append(url)
    for url in candidates[:3]:
        try:pages.append((url,fetch_html(url,timeout=7)))
        except RuntimeError:pass
    rows=[];seen=set()
    max_detail=min(int(os.getenv('MAX_DETAIL_PAGES_PER_SOURCE','6')),limit)
    for page_url,markup in pages:
     cards=listing_cards_from_html(markup,page_url,_is_detail,limit=max(160,limit*5))
     for card in cards:
        if card['url'] in seen:continue
        seen.add(card['url'])
        if not matches_model(brand,model,card['title']+' '+card['content']):continue
        if len(rows)<max_detail:
            try:
                more=detail_fields(fetch_html(card['url'],timeout=6),card['title'])
                for key in ('price','year','mileage','published_at'):
                    if more.get(key) is not None and (card.get(key) is None or key=='published_at'):
                        card[key]=more[key]
                if more.get('title') and matches_model(brand,model,more['title']):card['title']=more['title']
                card['content']=(more.get('content') or card['content'])[:2200]
            except (RuntimeError, LookupError, ValueError):
                card['detail_error']='دریافت جزئیات این آگهی ممکن نشد'
        if matches_model(brand,model,card['title']+' '+card['content']): rows.append(card)
        if len(rows)>=limit:return rows
    return rows
