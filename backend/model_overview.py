"""Evidence-only price snapshots for users who say just a model name.

Never average vehicles from different model-years, trims, or zero/used groups.
Values shown here are observed ASKING prices, not final transaction prices.
"""
from collections import defaultdict
from statistics import median


def name_only_search(vehicle):
    """Keep the existing precise flow for fully described cars."""
    return vehicle.get('year') is None or vehicle.get('mileage') is None or (
        vehicle.get('model') in ('فیدلیتی', 'دیگنیتی') and not vehicle.get('trim')
    )


def model_overview(vehicle, accepted, max_groups=8):
    groups = defaultdict(list)
    for item in accepted:
        if not item.get('accepted') or item.get('kind') != 'listing':
            continue
        price=item.get('price')
        if isinstance(price,bool) or not isinstance(price,(int,float)) or not 50_000_000 <= price <= 100_000_000_000:
            continue
        year=item.get('year')
        if not isinstance(year,int) or isinstance(year,bool):
            year=None
        trim=' '.join(str(item.get('trim') or 'نامشخص').strip().split())[:80]
        # Missing new/used evidence must never silently become "used".
        km=item.get('mileage')
        if item.get('is_new') is True:
            kind='صفر'
        elif item.get('is_new') is False or (isinstance(km,int) and km>0):
            kind='کارکرده'
        else:
            kind='وضعیت نامشخص'
        groups[(year,trim,kind)].append(item)

    result=[]
    for (year,trim,kind),items in groups.items():
        prices=sorted(int(x['price']) for x in items)
        # 4+ ads: use an interior percentile interval to resist asking-price
        # extremes. Smaller samples display the actual min/max only.
        if len(prices)>=4:
            lower=prices[(len(prices)-1)//4]
            upper=prices[(3*(len(prices)-1)+3)//4]
        else:
            lower,upper=prices[0],prices[-1]
        # Prefer one real link per independent source before repeating a site.
        linked=[];domains=set();urlset=set()
        ordered=sorted(items,key=lambda x: (str(x.get('domain') or ''),str(x.get('url') or '')))
        for pass_num in (0,1):
            for x in ordered:
                url=x.get('url') or ''
                domain=x.get('domain') or ''
                if not isinstance(url,str) or not url.startswith('https://') or url in urlset:
                    continue
                if pass_num==0 and domain in domains:continue
                if pass_num==1 and domain not in domains:continue
                linked.append({'url':url,'source':x.get('source') or domain,
                               'domain':domain,'price':int(x['price'])})
                urlset.add(url);domains.add(domain)
                if len(linked)>=4:break
            if len(linked)>=4:break
        links=[a['url'] for a in linked]
        result.append({
            'year':year,'trim':trim,'condition':kind,
            'label':f"{year if year else 'سال نامشخص'} · {trim} · {kind}",
            'price_min':lower,'price_max':upper,
            'price_middle':round(median(prices)) if len(prices)>=3 else None,
            'listing_count':len(prices),
            'source_count':len({x.get('domain') for x in items if x.get('domain')}),
            'links':links,'ads':linked,
            'limited':len(prices)<3,
        })
    result.sort(key=lambda x:(-x['listing_count'],-(x['year'] or 0),x['trim'],x['condition']))
    return {'groups':result[:max_groups], 'groups_total':len(result),
            'listing_count':sum(x['listing_count'] for x in result),
            'source_count':len({x.get('domain') for x in accepted if x.get('accepted') and x.get('kind')=='listing'}),
            'mode':'name_only', 'basis':'observed_ad_prices',
            'note':'بازه‌ها فقط قیمت پیشنهادی آگهی‌ها هستند؛ سال، تیپ و وضعیت صفر/کارکرده جداگانه بررسی می‌شوند.'}
