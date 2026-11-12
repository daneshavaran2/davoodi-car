"""Bama public listings connector, including hydrated JS ad cards."""
import os
from .common import fetch_html, links_from_html, norm, token_score, matches_model, same_host
from .extract import listing_cards_from_html, detail_fields

BASE='https://bama.ir'
DOMAIN='bama.ir'


def _best_link(links,brand,model=None):
    target=norm(' '.join(x for x in (brand,model) if x))
    ranked=[]
    for url,text in links:
        if not same_host(url,DOMAIN):continue
        nt=norm(text)
        if not nt:continue
        score=token_score(brand,model,nt)
        if 'خرید و فروش' in nt:score+=.25
        if model and '/car/' in url and 'detail-' not in url:score+=.15
        if score>0:ranked.append((score,-abs(len(nt)-len(target)),url))
    return max(ranked)[2] if ranked else None


def _is_detail(url):
    return same_host(url,DOMAIN) and '/car/detail-' in url.lower()


def search(vehicle,limit=30):
    brand=vehicle.get('brand') or '';model=vehicle.get('model') or ''
    if not (brand or model):return []
    home=fetch_html(BASE+'/car',timeout=8)
    home_links=links_from_html(home,BASE)
    # Some layouts expose a model category directly without the maker label.
    brand_url=(_best_link(home_links,brand,model) if model else None) or _best_link(home_links,brand)
    if not brand_url and model:
        brand_url=_best_link(home_links,'',model)
    if not brand_url:
        # Some Bama layouts show results directly rather than navigation links.
        return _rows(home,BASE+'/car',brand,model,limit)
    brand_html=fetch_html(brand_url,timeout=8)
    page_url=brand_url; raw=brand_html
    if model:
        model_url=_best_link(links_from_html(brand_html,brand_url),brand,model)
        if model_url and model_url!=brand_url:
            page_url=model_url
            raw=fetch_html(page_url,timeout=8)
    rows=_rows(raw,page_url,brand,model,limit)
    if rows:return rows
    # The current marketplace layout may expose cards directly on the first
    # brand page, even if its navigation sent us to a category landing page.
    if page_url!=brand_url:
        rows=_rows(brand_html,brand_url,brand,model,limit)
    if not rows:
        rows=_rows(home,BASE+'/car',brand,model,limit)
    return rows


def _rows(raw,url,brand,model,limit):
    cards=listing_cards_from_html(raw,url,_is_detail,limit=max(140,limit*5))
    rows=[];max_detail=min(int(os.getenv('MAX_DETAIL_PAGES_PER_SOURCE','6')),limit)
    for card in cards:
        if not matches_model(brand,model,card['title']+' '+card['content']):continue
        if len(rows)<max_detail:
            try:
                more=detail_fields(fetch_html(card['url'],timeout=6),card['title'])
                if more.get('title') and not matches_model(brand,model,more['title']):
                    card['detail_mismatch']=True
                    raise ValueError('عنوان صفحه جزئیات با مدل خواسته‌شده تفاوت دارد')
                if card.get('price') and more.get('price') and abs(card['price']-more['price'])>max(50_000_000,card['price']*.05):
                    card['price_conflict']=True
                # A detail page can add missing data, but should not silently
                # override a known valid card price with contradictory content.
                for key in ('price','year','mileage','published_at'):
                    if more.get(key) is not None and (card.get(key) is None or key=='published_at'):
                        card[key]=more[key]
                if more.get('title') and matches_model(brand,model,more['title']):
                    card['title']=more['title']
                card['content']=(more.get('content') or card['content'])[:2200]
            except (RuntimeError, LookupError, ValueError):
                # Retain card-level facts; final normalizer rejects incomplete data.
                card['detail_error']='دریافت جزئیات این آگهی ممکن نشد'
        rows.append(card)
        if len(rows)>=limit:break
    return rows
