"""Best-effort public Divar car search (no login/captcha workarounds).

The public URL structure can change; on a blocked page this connector raises an
honest source error. Official/licensed connector URLs still take precedence.
"""
import os,re
from urllib.parse import quote, urlsplit
from .common import fetch_html, matches_model, same_host
from .extract import listing_cards_from_html, detail_fields

DOMAIN='divar.ir'
CITIES={'تهران':'tehran','مشهد':'mashhad','اصفهان':'isfahan',
        'شیراز':'shiraz','تبریز':'tabriz','کرج':'karaj','قم':'qom'}


def _is_detail(url):
    if not same_host(url,DOMAIN):return False
    # Divar supports both /v/<id> short links and /v/<slug>/<id> listings.
    # Count URL path segments rather than counting the slashes in https://.
    path=urlsplit(url).path.lower()
    return bool(re.fullmatch(r'/v/(?:[^/]+/)?[a-z0-9_-]{4,}/?',path,re.I))


def search(vehicle,limit=25):
    model=vehicle.get('model') or ''
    if not model:return []
    city=CITIES.get(vehicle.get('city') or 'تهران','tehran')
    term=' '.join(str(x) for x in (model,vehicle.get('trim') or '',vehicle.get('year') or '') if x)
    url='https://divar.ir/s/'+city+'/car?q='+quote(term,safe='')
    raw=fetch_html(url,timeout=9)
    cards=listing_cards_from_html(raw,url,_is_detail,limit=limit)
    result=[];max_detail=min(limit,int(os.getenv('MAX_DETAIL_PAGES_PER_SOURCE','6')))
    for card in cards:
        if not matches_model(vehicle.get('brand'),model,card['title']+' '+card['content']):continue
        if len(result)<max_detail:
            try:
                details=detail_fields(fetch_html(card['url'],timeout=6),card['title'])
                for key in ('price','year','mileage','published_at'):
                    if details.get(key) is not None and (card.get(key) is None or key=='published_at'):
                        card[key]=details[key]
                if details.get('title') and matches_model(vehicle.get('brand'),model,details['title']):card['title']=details['title']
                card['content']=(details.get('content') or card['content'])[:2200]
            except (RuntimeError, ValueError, LookupError):pass
        result.append(card)
    return result
