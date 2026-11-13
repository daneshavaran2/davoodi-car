"""Offline acceptance tests for v29 -> v30 legacy public-page pilot.

No requests to Bama/Divar/Hamrah are sent by these tests.
"""
from datetime import datetime,timezone
from unittest.mock import patch
import pytest

from backend import legacy_bridge as bridge
from backend.connectors import SourceUnavailable
from backend.domain import clean_listing,normalize


CARS=[
 {'catalog_id':'fid-1','brand':'بهمن','model':'فیدلیتی پرایم','display_name':'بهمن فیدلیتی پرایم'},
 {'catalog_id':'peu-1','brand':'پژو','model':'207i','display_name':'پژو 207i'},
]

def valid_card():
    return {'url':'https://bama.ir/car/detail-abc123',
            'title':'فیدلیتی پرایم اتومات 1402',
            'content':'فیدلیتی پرایم اتومات 1402 کارکرد 45000 کیلومتر بدون رنگ قیمت خودرو 1 میلیارد و 700 میلیون تومان',
            'year':1402,'mileage':45000,'price':1700000000,'published_at':None}

def test_default_public_mode_without_json_feed(monkeypatch):
    monkeypatch.delenv('SOURCE_BAMA_MODE',raising=False)
    monkeypatch.delenv('SOURCE_BAMA_API_URL',raising=False)
    assert bridge.pilot_mode('bama') is True

def test_explicit_feed_url_takes_priority(monkeypatch):
    monkeypatch.delenv('SOURCE_BAMA_MODE',raising=False)
    monkeypatch.setenv('SOURCE_BAMA_API_URL','https://provider.example/api/cars')
    assert bridge.pilot_mode('bama') is False
    monkeypatch.setenv('SOURCE_BAMA_MODE','legacy_public')
    assert bridge.pilot_mode('bama') is True

def test_non_pilot_source_keeps_feed_mode(monkeypatch):
    monkeypatch.setenv('SOURCE_SHEYPOOR_MODE','legacy_public')
    assert bridge.pilot_mode('sheypoor') is False

def test_fidelity_adapter_accepts_evidence_and_validator():
    row=bridge._safe_listing('bama',CARS[0],valid_card())
    assert row and row['currency']=='toman'
    mapping={(normalize(x['brand']),normalize(x['model'])):x['catalog_id'] for x in CARS}
    valid,reason=clean_listing(row,'bama',mapping,now=datetime.now(timezone.utc))
    assert reason is None and valid['price_toman']==1700000000
    assert valid['condition']=='used' and valid['trim']=='پرایم'

def test_missing_mileage_is_not_guessed():
    card=valid_card();card['mileage']=None
    assert bridge._safe_listing('bama',CARS[0],card) is None

def test_conflicting_detail_price_rejected():
    card=valid_card();card['price_conflict']=True
    assert bridge._safe_listing('bama',CARS[0],card) is None

def test_unrecognized_gear_rejected():
    card=valid_card();card['title']='فیدلیتی پرایم 1402';card['content']='قیمت خودرو 1 میلیارد تومان کارکرد 45000 کیلومتر'
    assert bridge._safe_listing('bama',CARS[0],card) is None

def test_wrong_source_link_rejected():
    card=valid_card();card['url']='https://unknown.example/car/detail-a'
    assert bridge._safe_listing('bama',CARS[0],card) is None

def test_blocked_access_stops_without_bypass(monkeypatch):
    monkeypatch.setenv('SOURCE_BAMA_PUBLIC_ACCESS_APPROVED','1')
    monkeypatch.setenv('MARKET_FETCH_MODE','http')
    monkeypatch.setenv('PUBLIC_PILOT_MODELS','فیدلیتی پرایم')
    from backend.legacy_market import bama
    with patch.object(bama,'search',side_effect=RuntimeError('403 access denied')):
        with pytest.raises(SourceUnavailable) as e:
            bridge.collect_public('bama',CARS)
        assert e.value.code=='HTTP_403'

def test_mock_source_fills_only_real_pilot_rows(monkeypatch):
    monkeypatch.setenv('SOURCE_BAMA_PUBLIC_ACCESS_APPROVED','1')
    monkeypatch.setenv('MARKET_FETCH_MODE','http')
    monkeypatch.setenv('PUBLIC_PILOT_MODELS','فیدلیتی پرایم')
    from backend.legacy_market import bama
    with patch.object(bama,'search',return_value=[valid_card()]):
        rows=bridge.collect_public('bama',CARS)
    assert len(rows)==1 and rows[0]['model']=='فیدلیتی پرایم'

def test_bama_public_page_navigation_to_model_and_detail(monkeypatch):
    """Replays observed public page structure; does not contact the real site."""
    from backend.legacy_market import bama
    home='<html><a href="/car/fidelity">خرید و فروش فیدلیتی</a></html>'
    family='<html><a href="/car/fidelity-prime">خرید و فروش فیدلیتی پرایم</a></html>'
    model='''<html><article><a href="/car/detail-abc-fidelity-prime-1403">
     فیدلیتی، پرایم تیپ 1 پنج نفره 1403</a><p>کارکرد 45,000 کیلومتر</p>
     <span class="asking-price">6,800,000,000 تومان</span></article></html>'''
    detail='''<html><main><h1>فیدلیتی، پرایم</h1>
     <div>تیپ 1 پنج نفره 1403 کارکرد 45,000 کیلومتر</div>
     <div>قیمت فروش 6,800,000,000 تومان</div>
     <div>گیربکس اتوماتیک</div><div>وضعیت بدنه بدون رنگ</div>
     </main></html>'''
    routes={'https://bama.ir/car':home,'https://bama.ir/car/fidelity':family,
            'https://bama.ir/car/fidelity-prime':model,
            'https://bama.ir/car/detail-abc-fidelity-prime-1403':detail}
    def local_page(url,timeout=8):
        assert url in routes, url
        return routes[url]
    monkeypatch.setattr(bama,'fetch_html',local_page)
    cards=bama.search({'brand':'بهمن','model':'فیدلیتی پرایم'},limit=5)
    assert len(cards)==1
    converted=bridge._safe_listing('bama',CARS[0],cards[0])
    assert converted is not None
    assert converted['model_year']==1403
    assert converted['price_toman']==6800000000
    assert converted['transmission']=='automatic'
    assert converted['trim']=='پرایم تیپ 1 پنج نفره'

def test_fidelity_seat_variant_not_blended():
    from backend.domain import query_trim,clean_listing,normalize
    assert query_trim('فیدلیتی پرایم تیپ 1 پنج نفره اتومات')=='پرایم تیپ 1 پنج نفره'
    assert query_trim('فیدلیتی پرایم تیپ 2 هفت نفره اتومات')=='پرایم تیپ 2 هفت نفره'
    assert query_trim('فیدلیتی پرایم')=='پرایم'
    first=valid_card()
    first['content']+=' تیپ 1 پنج نفره'
    row=bridge._safe_listing('bama',CARS[0],first)
    assert row['trim']=='پرایم تیپ 1 پنج نفره'
    cars={(normalize(v['brand']),normalize(v['model'])):v['catalog_id'] for v in CARS}
    parsed,reason=clean_listing(row,'bama',cars,now=datetime.now(timezone.utc))
    assert reason is None and parsed['trim']=='پرایم تیپ 1 پنج نفره'

def test_body_field_without_paint_is_not_damaged():
    card=valid_card()
    card['content']+=' وضعیت بدنه بدون رنگ شاسی سالم'
    row=bridge._safe_listing('bama',CARS[0],card)
    assert row['body_condition']=='original'
