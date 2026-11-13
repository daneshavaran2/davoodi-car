from datetime import datetime,timezone
import pytest
from backend.nemuda import parse_aggregate,_match_catalog,_paths_from_index,collect_records,NemudaError

NOW=datetime(2026,11,13,tzinfo=timezone.utc)
BASE=dict(price=6000000000,priceRange={'low':5600000000,'high':6400000000},dataPoints=50,
          modelYear=1403,displayYear=1403,yearCalendar='jalali',coverage='solid',
          computedAt='2026-11-13T00:00:00Z')

def test_valid_aggregate_and_source_attribution():
    x=parse_aggregate(BASE,catalog_id='42',name='بهمن فیدلیتی پرایم',path='car/fidelity/prime-5/1403',now=NOW)
    assert x['median_toman']==6000000000
    assert x['vehicle_catalog_id']=='42'
    assert x['source_url']=='https://nemuda.com/car/fidelity/prime-5/1403'
    assert x['year_system']=='jalali'

def test_sparse_or_hidden_aggregates_never_get_published():
    for update in ({'dataPoints':9},{'coverage':'none'},{'price':None},
                   {'price':7000000000},{'computedAt':'2025-01-01T00:00:00Z'}):
        assert parse_aggregate({**BASE,**update},catalog_id='42',name='x',path='car/fidelity/a/1403',now=NOW) is None

def test_no_fabricated_paths():
    assert _paths_from_index({'items':[{'brand':'fidelity','model':'prime','year':1403}]})==[]
    assert _paths_from_index({'items':[{'path':'/api/market/vehicles/car/fidelity/prime/1403'}]})==['car/fidelity/prime/1403']

def test_explicit_leaf_collection(monkeypatch):
    monkeypatch.setenv('NEMUDA_TARGET_PATHS','car/fidelity/prime/1403')
    def fetch(url):
        return {'ignored':True} if url.endswith('/index') else BASE
    rows=collect_records(fetch=fetch)
    assert len(rows)==1 and rows[0][1]['price']==BASE['price']

def test_unique_catalog_match():
    cars=[{'catalog_id':'a','brand':'بهمن','model':'فیدلیتی','display_name':'بهمن فیدلیتی'},
          {'catalog_id':'b','brand':'بهمن','model':'فیدلیتی پرایم','display_name':'بهمن فیدلیتی پرایم'}]
    assert _match_catalog('فیدلیتی پرایم ۵ نفره',cars,[])['catalog_id']=='b'
    assert _match_catalog('ناشناس',cars,[]) is None

def test_year_paths_with_explicit_nested_slugs():
    index={'categories':[{'slug':'car','brands':[{'slug':'fidelity','models':[{'slug':'prime-5','years':[{'displayYear':1403}]}]}]}]}
    assert _paths_from_index(index)==['car/fidelity/prime-5/1403']

