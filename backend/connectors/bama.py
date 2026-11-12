import re
from .common import fetch_html,links_from_html,norm,token_score,explicit_price,year_value,mileage_value,structured_listing_fields,text_from_html
BASE='https://bama.ir'
DOMAIN='bama.ir'

def _best_link(links,brand,model=None):
    target=norm(' '.join(x for x in [brand,model] if x))
    ranked=[]
    for url,text in links:
        if DOMAIN not in url:continue
        nt=norm(text)
        if not nt:continue
        score=token_score(brand,model,nt) if model else token_score(brand,'',nt)
        if 'خرید و فروش' in nt:score+=.25
        if model and '/car/' in url and 'detail-' not in url:score+=.15
        if score>0:ranked.append((score,-abs(len(nt)-len(target)),url,text))
    return max(ranked)[2] if ranked else None

def search(vehicle,limit=30):
    brand=vehicle.get('brand') or ''; model=vehicle.get('model') or ''
    if not brand and not model:return []
    home=fetch_html(BASE+'/car',timeout=8)
    home_links=links_from_html(home,BASE)
    brand_url=_best_link(home_links,brand)
    if not brand_url:return []
    brand_html=fetch_html(brand_url,timeout=8)
    page_url=brand_url
    if model:
        model_url=_best_link(links_from_html(brand_html,brand_url),brand,model)
        if model_url:page_url=model_url
    raw=fetch_html(page_url,timeout=8) if page_url!=brand_url else brand_html
    rows=[]
    for url,text in links_from_html(raw,page_url):
        if 'bama.ir/car/detail-' not in url:continue
        if token_score(brand,model,text)<(.45 if model else .35):continue
        # Verification on the detail page is bounded; link text alone has no
        # trustworthy publication date. A blocked detail page stays unverified.
        metadata={}; description=text
        if len(rows)<5:
            try:
                detail_html=fetch_html(url,timeout=5)
                metadata=structured_listing_fields(detail_html)
                description=text_from_html(detail_html)[:2500]
            except (RuntimeError,KeyError,ValueError):pass
        rows.append({'url':url,'title':text,'content':description,
                     'price':metadata.get('price') or explicit_price(text),
                     'year':year_value(text+' '+description),'mileage':mileage_value(text+' '+description),
                     'published_at':metadata.get('published_at'),'kind':'listing'})
        if len(rows)>=limit:break
    return rows
