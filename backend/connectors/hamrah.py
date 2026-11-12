import re
from .common import fetch_html,links_from_html,text_from_html,token_score,explicit_price,year_value,mileage_value
BASE='https://www.hamrah-mechanic.com/cars-for-sale/'
DOMAIN='hamrah-mechanic.com'

def _detail(url,vehicle):
    raw=fetch_html(url); text=text_from_html(raw)
    title=''
    m=re.search(r'(?:خرید و فروش\s+)?([^|]{3,140}?)(?:\s+با ضمانت|\s+[–|-]\s+همراه مکانیک|$)',text)
    if m:title=m.group(1).strip()
    if not title:title=text[:180]
    return {'url':url,'title':title,'content':text[:5000],'price':explicit_price(text),
            'year':year_value(text),'mileage':mileage_value(text),'kind':'listing'}

def search(vehicle,limit=25):
    brand=vehicle.get('brand') or '';model=vehicle.get('model') or ''
    raw=fetch_html(BASE)
    candidates=[]
    for url,text in links_from_html(raw,BASE):
        if not re.search(r'/cars-for-sale/[^/]+/[^/]+/\d+/?$',url):continue
        if token_score(brand,model,text)<(.35 if model else .2):continue
        candidates.append((url,text))
    rows=[]
    for url,text in candidates[:min(limit,12)]:
        try:row=_detail(url,vehicle)
        except RuntimeError:
            row={'url':url,'title':text,'content':text,'price':explicit_price(text),
                 'year':year_value(text),'mileage':mileage_value(text),'kind':'listing'}
        if token_score(brand,model,row['title']+' '+row['content'])>=.45:rows.append(row)
    return rows
