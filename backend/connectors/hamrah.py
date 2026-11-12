"""Hamrah mechanic public listing connector, including hydrated JS cards."""
import os,re
from .common import fetch_html,token_score,matches_model,same_host
from .extract import listing_cards_from_html, detail_fields

BASE='https://www.hamrah-mechanic.com/cars-for-sale/'
DOMAIN='hamrah-mechanic.com'


def _is_detail(url):
    return same_host(url,DOMAIN) and bool(re.search(r'/cars-for-sale/[^/]+/[^/]+/\d+/?$',url))


def search(vehicle,limit=25):
    brand=vehicle.get('brand') or '';model=vehicle.get('model') or ''
    raw=fetch_html(BASE,timeout=8)
    cards=listing_cards_from_html(raw,BASE,_is_detail,limit=limit)
    rows=[]
    max_detail=min(int(os.getenv('MAX_DETAIL_PAGES_PER_SOURCE','6')),limit)
    for card in cards:
        if not matches_model(brand,model,card['title']+' '+card['content']):continue
        if len(rows)<max_detail:
            try:
                more=detail_fields(fetch_html(card['url'],timeout=6),card['title'])
                for key in ('price','year','mileage','published_at'):
                    if more.get(key) is not None and (card.get(key) is None or key=='published_at'):
                        card[key]=more[key]
                if more.get('title') and matches_model(brand,model,more['title']):card['title']=more['title']
                card['content']=(more.get('content') or card['content'])[:2200]
            except (RuntimeError, LookupError, ValueError):pass
        if matches_model(brand,model,card['title']+' '+card['content']): rows.append(card)
    return rows
