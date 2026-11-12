import os, importlib, sys
os.environ.setdefault('ADMIN_PASSWORD','test-password')
os.environ.setdefault('SESSION_SECRET','x'*40)
sys.path.insert(0, os.path.dirname(__file__))
m=importlib.import_module('main')

vehicle={'brand':'هیوندای','model':'سانتافه','trim':'','year':2025,'mileage':0,'condition':'صفر کیلومتر','query':'سانتافه 2025'}

assert m._kind_from_url_title('https://bama.ir/car/detail-abc','سانتافه 2025')=='listing'
assert m._kind_from_url_title('https://bama.ir/car-reviews/santafe','بررسی خودرو سانتافه')=='article'
assert m._kind_from_url_title('https://example.com/x','مشخصات فنی هیوندای وراکروز')=='article'
q=m._fallback_query(vehicle,{'name':'باما','domain':'bama.ir'})
assert 'site:bama.ir' in q and 'آگهی فروش خودرو' in q and '2025' in q

source={'name':'باما','domain':'bama.ir','env':'X'}
article=m._normalize_result(source,{'url':'https://bama.ir/car-reviews/santafe','title':'بررسی هیوندای سانتافه 2025 قیمت 5 میلیارد تومان'},vehicle)
assert article['accepted'] is False and article['kind']=='article'
listing=m._normalize_result(source,{'url':'https://bama.ir/car/detail-abc','title':'هیوندای سانتافه 2025 صفر کیلومتر 5 میلیارد تومان','kind':'listing'},vehicle)
assert listing['accepted'] is True and listing['price']==5_000_000_000

limited=m._weighted_stats([listing],0)
assert limited['limited_evidence'] is True and limited['price_average'] is None and limited['price_min']==5_000_000_000

print('v21 backend tests: OK')
print('fallback query:',q)
print('limited evidence:',limited)

# Integration-style deterministic test without external network.
orig_direct,orig_builtin,orig_fallback=m._direct_connector,m._builtin_connector,m._search_fallback_domain
old_avalai=m.AVALAI_KEY; m.AVALAI_KEY='offline-mock-key'
try:
    m._direct_connector=lambda source,vehicle: None
    m._builtin_connector=lambda source,vehicle: None
    def fake_fallback(vehicle,source):
        if source['domain']=='bama.ir':
            return [
                {'url':'https://bama.ir/car-reviews/santafe','title':'بررسی سانتافه 2025 قیمت 4 میلیارد تومان'},
                {'url':'https://bama.ir/car/detail-one','title':'هیوندای سانتافه 2025 صفر کیلومتر 5 میلیارد تومان'},
            ]
        if source['domain']=='divar.ir':
            return [{'url':'https://divar.ir/v/santafe/test-ad','title':'هیوندای سانتافه 2025 صفر کیلومتر 5 میلیارد و 200 میلیون تومان'}]
        return []
    m._search_fallback_domain=fake_fallback
    old_max=m.MAX_DOMAIN_REQUESTS; m.MAX_DOMAIN_REQUESTS=6
    out=m.research_market(vehicle)
    assert out['diagnostics']['articles_removed']>=1
    assert all('car-reviews' not in x['url'] for x in out['sources'])
    assert out['new']['sample_count']==2 and out['new']['limited_evidence'] is True
    assert out['new']['price_average'] is None
    assert len(out['verified_source_urls'])==2
    bama=[x for x in out['site_status'] if x['domain']=='bama.ir'][0]
    assert bama['raw_count']==2 and bama['accepted_count']==1
    print('v21 research_market integration test: OK')
finally:
    m._direct_connector,m._builtin_connector,m._search_fallback_domain=orig_direct,orig_builtin,orig_fallback
    m.MAX_DOMAIN_REQUESTS=old_max
    m.AVALAI_KEY=old_avalai
