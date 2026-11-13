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

def test_no_legacy_mode_by_default(monkeypatch):
    monkeypatch.delenv('SOURCE_BAMA_MODE',raising=False)
    assert bridge.pilot_mode('bama') is False

def test_explicit_access_approval_required(monkeypatch):
    monkeypatch.setenv('SOURCE_BAMA_MODE','legacy_public')
    monkeypatch.delenv('SOURCE_BAMA_PUBLIC_ACCESS_APPROVED',raising=False)
    with pytest.raises(SourceUnavailable) as exc:
        bridge.collect_public('bama',CARS)
    assert exc.value.code=='PERMISSION_NOT_CONFIRMED'

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
