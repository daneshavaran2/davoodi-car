"""Quality-focused regressions: fail closed on conflicting or unverified prices."""
from datetime import datetime,timezone,timedelta
import pytest

from backend.quality import detail_conflict,explicit_price_matches,price_outliers,publication_age
from backend.domain import normalize
from backend.legacy_bridge import _safe_listing
from backend import legacy_crawler


def _card():
    return {'url':'https://bama.ir/car/detail-abc',
            'title':'فیدلیتی پرایم اتومات مدل ۱۴۰۳',
            'content':'کارکرد ۴۵۰۰۰ کیلومتر، وضعیت بدنه بدون رنگ، قیمت خودرو ۱ میلیارد و ۷۰۰ میلیون تومان',
            'year':1403,'mileage':45000,'price':1700000000}


def _car():
    return {'catalog_id':'fid-1','brand':'بهمن','model':'فیدلیتی پرایم',
            'display_name':'بهمن فیدلیتی پرایم'}


@pytest.mark.parametrize('a,b,expected',[
    ({'year':1403},{'year':1402},'YEAR_CONFLICT'),
    ({'mileage':45000},{'mileage':145000},'MILEAGE_CONFLICT'),
    ({'price':1700000000},{'price':2400000000},'PRICE_CONFLICT'),
    ({'mileage':45000},{'mileage':45500},None),
    ({'year':1403},{'year':1403},None),
    ({'price':1700000000},{'price':1710000000},None),
])
def test_card_detail_consistency(a,b,expected):
    assert detail_conflict(a,b)==expected


def test_unrelated_fee_does_not_confirm_asking_price():
    assert not explicit_price_matches(1700000000,'کارمزد ۱۰۰ میلیون تومان')
    card=_card()
    card['content']='کارکرد 45000 کیلومتر؛ کارمزد 100 میلیون تومان'
    assert _safe_listing('bama',_car(),card) is None


def test_verified_cash_amount_only():
    assert explicit_price_matches(1700000000,'قیمت خودرو ۱ میلیارد و ۷۰۰ میلیون تومان')
    assert not explicit_price_matches(1700000000,'قیمت خودرو ۱ میلیارد تومان')
    assert not explicit_price_matches(1700000000,'قیمت توافقی تماس بگیرید')


def test_safe_listing_uses_verified_cash_evidence():
    x=_safe_listing('bama',_car(),_card())
    assert x and x['price_toman']==1700000000 and x['model_year']==1403
    assert 'قیمت خودرو' in x['price_text']
    bad=_card();bad['detail_conflict']='MILEAGE_CONFLICT'
    assert _safe_listing('bama',_car(),bad) is None


def test_detail_enrichment_rejects_conflicting_year(monkeypatch):
    monkeypatch.setattr(legacy_crawler,'fetch_html',lambda *a,**k:'<html><body>details</body></html>')
    monkeypatch.setattr(legacy_crawler,'detail_fields',
                        lambda *a,**k:{'title':'فیدلیتی پرایم ۱۴۰۲','year':1402,
                                      'mileage':45000,'price':1700000000,'content':'...'})
    monkeypatch.setattr(legacy_crawler,'extract_public_features',lambda *a,**k:{})
    card=_card();card['_model']='فیدلیتی پرایم'
    legacy_crawler._detail_enrich(card)
    assert card['detail_conflict']=='YEAR_CONFLICT'
    assert _safe_listing('bama',_car(),card) is None


def test_detail_enrichment_rejects_conflicting_mileage(monkeypatch):
    monkeypatch.setattr(legacy_crawler,'fetch_html',lambda *a,**k:'<html><body>details</body></html>')
    monkeypatch.setattr(legacy_crawler,'detail_fields',
                        lambda *a,**k:{'title':'فیدلیتی پرایم ۱۴۰۳','year':1403,
                                      'mileage':145000,'price':1700000000,'content':'...'})
    monkeypatch.setattr(legacy_crawler,'extract_public_features',lambda *a,**k:{})
    card=_card();card['_model']='فیدلیتی پرایم'
    legacy_crawler._detail_enrich(card)
    assert card['detail_conflict']=='MILEAGE_CONFLICT'


def test_tenfold_outlier_is_excluded():
    prices=[2000000000,2050000000,2100000000,2150000000,2200000000,2300000000,20000000000]
    rows=[{'price_toman':p} for p in prices]
    kept,excluded=price_outliers(rows)
    assert len(kept)==6 and len(excluded)==1 and excluded[0]['price_toman']==20000000000


def test_sparse_samples_are_not_manipulated():
    rows=[{'price_toman':400000000},{'price_toman':2000000000}]
    assert price_outliers(rows)==(rows,[])


def test_publication_date_unknown_is_not_fresh():
    now=datetime.now(timezone.utc)
    assert publication_age(None)=='unknown'
    assert publication_age(now.isoformat(),now)=='fresh'
    assert publication_age((now-timedelta(days=16)).isoformat(),now)=='stale'


def test_source_cash_quoted_from_fresh_non_outlier_evidence():
    from backend.worker import _recompute
    now=datetime.now(timezone.utc)
    def row(idx,price):
        return {'source':'bama','external_id':str(idx),'url':'https://bama.ir/car/detail-'+str(idx),
                'catalog_id':'fid-1','year':1403,'year_system':'jalali','trim':'پرایم',
                'condition':'used','mileage_km':55000,'transmission':'automatic',
                'fuel_type':'unknown','body_condition':'original',
                'price_toman':price,'observed_at':now,'title':'فیدلیتی پرایم مدل ۱۴۰۳',
                'city':'تهران'}
    rows=[row(i,p) for i,p in enumerate(
        [2000000000,2050000000,2100000000,2150000000,2200000000,2300000000,20000000000])]
    class Cursor:
        def __init__(self):
            self.executed=[]
        def execute(self,sql,params=None):
            self.executed.append((sql,params))
        def fetchall(self):
            return rows
        def fetchone(self):
            return {'id':1}
    cur=Cursor()
    count=_recompute(cur,now-timedelta(seconds=1))
    assert count==1
    samples=[params for sql,params in cur.executed if 'INSERT INTO price_samples' in sql]
    assert len(samples)==6
    assert all(20000000000 not in sample for sample in samples)
