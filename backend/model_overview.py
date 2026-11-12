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
        # Zero versus used is kept separate even when the user gave no mileage.
        kind='صفر' if item.get('is_new') is True else 'کارکرده'
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
        links=list(dict.fromkeys(x['url'] for x in items if x.get('url','').startswith('https://')))[:3]
        result.append({
            'year':year,'trim':trim,'condition':kind,
            'label':f"{year if year else 'سال نامشخص'} · {trim} · {kind}",
            'price_min':lower,'price_max':upper,
            'price_middle':round(median(prices)) if len(prices)>=3 else None,
            'listing_count':len(prices),
            'source_count':len({x.get('domain') for x in items if x.get('domain')}),
            'links':links,
            'limited':len(prices)<3,
        })
    result.sort(key=lambda x:(-x['listing_count'],-(x['year'] or 0),x['trim'],x['condition']))
    return {'groups':result[:max_groups], 'groups_total':len(result),
            'listing_count':sum(x['listing_count'] for x in result),
            'source_count':len({x.get('domain') for x in accepted if x.get('accepted') and x.get('kind')=='listing'}),
            'mode':'name_only', 'basis':'observed_ad_prices',
            'note':'بازه‌ها فقط قیمت پیشنهادی آگهی‌ها هستند؛ سال، تیپ و وضعیت صفر/کارکرده جداگانه بررسی می‌شوند.'}
