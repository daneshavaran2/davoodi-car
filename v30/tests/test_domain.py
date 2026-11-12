import csv
from datetime import datetime,timezone,timedelta
from pathlib import Path
import pytest
from backend.domain import (normalize,normalize_query,find_vehicle,query_year,query_trim,
       clean_listing,quote,grouping_key,valid_ad_url,GOOD_HOSTS,mileage_band,_nearest)

FILE=Path(__file__).parents[1]/'data/vehicle_catalog.csv'
with FILE.open(encoding='utf-8-sig') as f:
    RAW=list(csv.DictReader(f))
CARS=[{**r,'catalog_id':r['id']} for r in RAW]
LOOKUP={(normalize(c['brand']),normalize(c['model'])):c['catalog_id'] for c in CARS}


def fixture(price=2_500_000_000,year=1403,trim='پرایم',**extra):
    row={'url':'https://bama.ir/car/detail-unique-123','title':'فیدلیتی پرایم مدل ۱۴۰۳',
     'brand':'بهمن','model':'فیدلیتی پرایم','trim':trim,'currency':'toman',
     'model_year':year,'condition':'used','mileage_km':55000,'transmission':'automatic',
     'body_condition':'original','price_toman':price,'city':'تهران',
     'external_id':'bama-123','raw_type':'listing'}
    row.update(extra)
    return row


def accepted(**changes):
    row=fixture()
    row.update(changes)
    return clean_listing(row,'bama',LOOKUP)


def test_catalog_counts():
    assert len(CARS)==660
    assert len({r['catalog_id'] for r in CARS})==660
    assert len({r['brand'] for r in CARS})==74


@pytest.mark.parametrize('search,expected',[
 ('سانتافه ۲۰۱۷','سانتافه'),('Hyundai Santa Fe 2017','سانتافه'),
 ('لیفان 820','820'),('Lifan 820','820'),
 ('دنا پلاس توربو اتومات ۱۴۰۲','دنا پلاس توربو'),
 ('فیدلیتی پرایم ۱۴۰۳','فیدلیتی پرایم'),
])
def test_match_longest_real_model(search,expected):
    result=find_vehicle(search,CARS)
    assert result['status']=='matched'
    assert result['matches'][0]['model']==expected


def test_dates_not_from_catalog():
    assert query_year('سانتافه ۲۰۱۷')==2017
    assert query_year('دنا پلاس توربو اتومات ۱۴۰۲')==1402
    assert query_year('فیدلیتی پرایم') is None
    assert query_trim('دنا پلاس توربو اتومات ۱۴۰۲')=='توربو اتومات'


def test_alias_translation():
    assert normalize('عربي كی ۱۴۰۳')==normalize('عربي کی 1403')
    assert normalize_query('Lifan 820')==normalize('لیفان 820')


def test_valid_real_listing():
    result,reason=accepted()
    assert reason is None
    assert result['year']==1403
    assert result['trim']=='پرایم'
    assert result['price_toman']==2_500_000_000


def test_rial_to_toman_exactly_ten():
    x,reason=accepted(price_toman=None,price=25_000_000_000,currency='irr')
    assert reason is None
    assert x['price_toman']==2_500_000_000
    _,reason=accepted(price_toman=None,price=25_000_000_001,currency='irr')
    assert reason=='RIAL_CONVERSION_UNCERTAIN'


@pytest.mark.parametrize('change,reason',[
 ({'price_toman':None,'price':10000000,'currency':None},'UNKNOWN_CURRENCY'),
 ({'title':'فیدلیتی پرایم مدل ۱۴۰۲'},'YEAR_TITLE_CONFLICT'),
 ({'trim':'پرستیژ'},'TRIM_TITLE_CONFLICT'),
 ({'condition':'new','mileage_km':55000},'CONFLICTING_CONDITION'),
 ({'condition':'used','mileage_km':None},'UNKNOWN_MILEAGE'),
 ({'transmission':None},'UNKNOWN_TRANSMISSION'),
 ({'trim':None,'title':'فیدلیتی مدل ۱۴۰۳'},'MODEL_TITLE_CONFLICT'),
 ({'url':'https://evil.example/car/detail-123'},'INVALID_URL'),
 ({'price_text':'پیش پرداخت ۱۰۰ میلیون تومان'},'NON_CASH_PRICE'),
 ({'currency':'USD'},'UNKNOWN_CURRENCY'),
 ({'raw_type':'article'},'NOT_A_SALE_LISTING'),
 ({'title':'دیگنیتی پرایم ۱۴۰۳'},'MODEL_TITLE_CONFLICT'),
 ({'price_toman':2500000000,'currency':'irr'},'CURRENCY_FIELD_CONFLICT'),
 ({'model_year':1400},'YEAR_TITLE_CONFLICT'),
])
def test_reject_unsafe_adverts(change,reason):
    x,why=accepted(**change)
    assert x is None,change
    assert why==reason,change


def test_stale_ad_rejected_and_observed_not_substituted():
    dt=datetime.now(timezone.utc)-timedelta(days=16)
    x,why=accepted(published_at=dt.isoformat())
    assert x is None and why=='STALE_OR_FUTURE_LISTING'
    x,why=accepted(published_at=None)
    assert why is None and x['published_at'] is None


def test_quote_requires_five_unique_and_identical_segments():
    row,why=accepted()
    assert why is None
    rows=[{**row,'external_id':str(i),'price_toman':2_000_000_000+i*40_000_000,
           'source':'divar' if i%2 else 'bama'} for i in range(12)]
    assert quote(rows[:4]) is None
    result=quote(rows)
    prices=sorted(x['price_toman'] for x in rows)
    assert result['low']==prices[2]
    assert result['high']==prices[9]
    assert result['median']>result['low']
    assert result['confidence']=='high'
    assert result['count']==12
    with pytest.raises(ValueError,match='mixed'):
        quote(rows[:5]+[{**rows[5],'year':1402}])


def test_no_false_price_from_catalog():
    assert all('price' not in row for row in RAW)


def test_bad_domains_rejected():
    assert valid_ad_url('https://divar.ir/v/123abc','divar')
    assert not valid_ad_url('http://divar.ir/v/123abc','divar')
    assert not valid_ad_url('https://divar.ir.attacker.com/v/123abc','divar')
    assert not valid_ad_url('https://user:password@divar.ir/v/123abc','divar')
