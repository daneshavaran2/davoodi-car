"""Extract local ad cards and detail attributes from hydrated HTML.

No CSS class names tied to a particular site are required. Crucially the price
is read from the *individual ad card*, not from the entire search page, which
could contain several unrelated prices or transaction fees.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup

from .common import listing_metadata, norm, year_value, mileage_value
from safety_v24 import explicit_vehicle_price, mileage_from_description

_PRICE_ATTR = re.compile(r'(?:^|[-_])(price|amount|cost)(?:$|[-_])', re.I)
_NOISE = ('script', 'style', 'noscript', 'svg', 'header', 'footer', 'nav')


def _text(node) -> str:
    return re.sub(r'\s+', ' ', node.get_text(' ', strip=True)).strip() if node else ''


def _ad_container(anchor, is_detail):
    """Smallest surrounding card with useful body text and one ad URL."""
    title = _text(anchor)
    best = anchor
    for candidate in list(anchor.parents)[:6]:
        if candidate.name in ('body', 'html', 'main'): break
        value = _text(candidate)
        if not value or len(value) > 1000: break
        hrefs = [a.get('href', '') for a in candidate.select('a[href]')]
        # Do not aggregate prices from multiple listings in one parent.
        details = {h for h in hrefs if is_detail(h)}
        if len(details) > 1: break
        if len(value) > len(title) + 5:
            best = candidate
    return best


def listing_cards_from_html(raw, base, predicate, limit=35):
    """Return ad URLs, local card text, parsed prices; never assign site-wide prices."""
    soup = BeautifulSoup(raw or '', 'html.parser')
    for noise in soup.select(','.join(_NOISE)):
        noise.decompose()
    seen=set();out=[]
    for a in soup.select('a[href]'):
        url=urljoin(base, a.get('href', ''))
        if url in seen or not predicate(url):continue
        seen.add(url)
        card = _ad_container(a, lambda u: predicate(urljoin(base,u)))
        text=_text(card)[:1000]
        title=_text(a) or _text(card.select_one('h2,h3,h4')) or text[:180]
        # Allow data attributes in a card but never use an unlabelled price from
        # a page that contains several amounts.
        price=explicit_vehicle_price(text)
        if price is None:
            amounts=[]
            for n in card.find_all(True):
                if any(_PRICE_ATTR.search(str(n.get(key) or '')) for key in ('class','data-testid','itemprop')):
                    v=explicit_vehicle_price('قیمت خودرو '+_text(n))
                    if v:amounts.append(v)
            if len(set(amounts))==1:
                price=amounts[0]
        out.append({'url':url,'title':title[:220], 'content':text, 'price':price,
                    'year':year_value(title) or year_value(text),
                    'mileage':mileage_from_description(text), 'kind':'listing'})
        if len(out)>=limit:break
    return out


def detail_fields(raw, fallback_title=''):
    """Extract only local detail facts, preferring explicit JSON-LD.

    Unknown price/date is returned as None; we will not hallucinate values.
    """
    soup=BeautifulSoup(raw or '', 'html.parser')
    metadata=listing_metadata(raw or '')
    for noise in soup.select(','.join(_NOISE)):
        noise.decompose()
    heading=soup.select_one('h1')
    title=_text(heading) or fallback_title
    main=soup.select_one('main,article,[role=main]') or soup.body or soup
    content=_text(main)[:3500]
    meta_price=metadata.get('price')
    if meta_price is None:
        amounts=[]
        # Limited to explicit price widgets, not arbitrary sidebar text.
        for element in main.select('[data-testid*="price"],[itemprop="price"],[class*="price"],[class*="Price"]')[:30]:
            amount=explicit_vehicle_price('قیمت خودرو '+_text(element))
            if amount:amounts.append(amount)
        if len(set(amounts))==1 and amounts:
            meta_price=amounts[0]
        if meta_price is None:
            meta_price=explicit_vehicle_price(content)
    return {
        'title':title[:220], 'content':content,
        'price':meta_price,
        'year':metadata.get('year') or year_value(title) or year_value(content),
        'mileage':metadata.get('mileage') if metadata.get('mileage') is not None else mileage_from_description(content),
        'published_at':metadata.get('published_at'),
    }
