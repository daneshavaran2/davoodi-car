"""Khodro45 reference prices: never classify editorial pages as sales ads."""
from .common import fetch_html,token_score,same_host
from .extract import listing_cards_from_html,detail_fields
from .common import links_from_html, explicit_price, year_value, mileage_value
BASE='https://khodro45.com/'
DOMAIN='khodro45.com'


def search(vehicle,limit=20):
    brand=vehicle.get('brand') or '';model=vehicle.get('model') or ''
    rows=[];seen=set()
    for path in ('price/','car-price/',''):
        if len(rows)>=limit:break
        try:raw=fetch_html(BASE+path,timeout=8)
        except RuntimeError as exc:
            if any(x in str(exc) for x in ('403','401','429','کپچا','captcha','مسدود')):
                raise
            continue
        for url,text in links_from_html(raw,BASE+path):
            if url in seen or not same_host(url,DOMAIN):continue
            if any(part in url for part in ('/mag/','/blog/','/news/','/review/')):continue
            if token_score(brand,model,text)<(.45 if model else .3):continue
            price=explicit_price(text)
            if price is None:
                try:
                    detail=detail_fields(fetch_html(url,timeout=5),text)
                    price=detail.get('price')
                    if price is None:continue
                except (RuntimeError,ValueError):continue
            seen.add(url)
            rows.append({'url':url,'title':text,'content':text,'price':price,
                        'year':year_value(text),'mileage':mileage_value(text),'kind':'market_price'})
            if len(rows)>=limit:break
    return rows
