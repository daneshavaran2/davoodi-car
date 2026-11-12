import re
from .common import fetch_html,links_from_html,text_from_html,token_score,explicit_price,year_value,mileage_value,structured_listing_fields
BASE='https://khodro45.com/'
DOMAIN='khodro45.com'

def search(vehicle,limit=20):
    # Khodro45 public web is primarily pricing/valuation/editorial, not a stable public listing feed.
    # We only emit rows with an explicit vehicle price and never treat /mag/ articles as listings.
    brand=vehicle.get('brand') or '';model=vehicle.get('model') or ''
    rows=[]; seen=set()
    for path in ('price/','car-price/',''):
        try:raw=fetch_html(BASE+path,timeout=8)
        except RuntimeError:continue
        for url,text in links_from_html(raw,BASE+path):
            if not url.startswith(BASE):continue
            if '/mag/' in url or '/blog/' in url or '/news/' in url:continue
            if token_score(brand,model,text)<(.45 if model else .3):continue
            price=explicit_price(text)
            if price and url not in seen:
                seen.add(url)
                meta={}; description=text
                if len(rows)<4:
                    try:
                        detail=fetch_html(url,timeout=5)
                        meta=structured_listing_fields(detail)
                        description=text_from_html(detail)[:1800]
                    except (RuntimeError,KeyError,ValueError):pass
                rows.append({'url':url,'title':text,'content':description,
                             'price':meta.get('price') or price,
                             'year':year_value(text+' '+description),'mileage':mileage_value(text+' '+description),
                             'published_at':meta.get('published_at'),'kind':'market_price'})
            if len(rows)>=limit:return rows
    return rows
