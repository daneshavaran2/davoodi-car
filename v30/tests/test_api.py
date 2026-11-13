from datetime import datetime,timezone
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.api import app

client=TestClient(app)
CAR={'catalog_id':'abc','brand':'بهمن','model':'فیدلیتی پرایم','display_name':'بهمن فیدلیتی پرایم','search_text':'بهمن فیدلیتی پرایم'}


def test_no_data_returns_immediately_and_queues():
    with patch('backend.storage.vehicles',return_value=([CAR],[])),\
         patch('backend.storage.price_rows',return_value=[]) as rows,\
         patch('backend.storage.request_refresh') as queue:
        r=client.get('/api/v1/prices/estimate?q=فیدلیتی%20پرایم')
        assert r.status_code==200
        assert r.json()['status']=='no_data'
        assert r.json()['groups']==[]
        assert r.json()['duration_ms']<3000
        queue.assert_called_once()
        rows.assert_called_once()


def test_precached_price_fast_and_real():
    result={'segment_key':'key','model_year':1403,'year_system':'jalali','vehicle_condition':'used',
        'mileage_band':'50-99k','body_condition':'original','sample_count':12,'source_count':2,
        'low_toman':2400000000,'median_toman':2550000000,'high_toman':2700000000,
        'confidence':'high','computed_at':datetime.now(timezone.utc),
        'stale_after':datetime.now(timezone.utc),'trim_name':'پرایم','transmission':'automatic','fuel_type':'unknown',
        'ads':[{'source_code':'bama','url':'https://bama.ir/car/detail-111','price_toman':2400000000,
             'observed_at':datetime.now(timezone.utc)}]}
    with patch('backend.storage.vehicles',return_value=([CAR],[])),\
         patch('backend.storage.price_rows',return_value=[result]):
        r=client.get('/api/v1/prices/estimate?q=فیدلیتی%20پرایم')
        assert r.status_code==200
        d=r.json();assert d['status']=='ok'
        assert d['groups'][0]['low_toman']==2400000000
        assert d['groups'][0]['source_count']==2
        assert d['duration_ms']<3000


def test_admin_requires_token_and_missing_secret_denied():
    with patch.dict('os.environ',{'ADMIN_TOKEN':''}):
        r=client.get('/api/v1/sources/status')
        assert r.status_code==503


def test_health_honest_db_failure():
    with patch('backend.storage.connection',side_effect=RuntimeError('postgres down')):
        r=client.get('/api/v1/health')
        assert r.status_code==503
        assert r.json()['database']=='unavailable'


def test_marketplace_collection_never_called_by_price_route():
    with patch('backend.storage.vehicles',return_value=([CAR],[])),\
         patch('backend.storage.price_rows',return_value=[]),\
         patch('backend.storage.request_refresh'),\
         patch('backend.connectors.collect_source',side_effect=AssertionError('external call during user request')) as forbidden:
        r=client.get('/api/v1/prices/estimate?q=فیدلیتی%20پرایم')
        assert r.status_code==200
        forbidden.assert_not_called()

def test_health_version_follows_running_fastapi_release(monkeypatch):
    import json
    from backend import api
    assert api.live()['version']==api.app.version=='30.8.0'
    monkeypatch.delenv('DATABASE_URL',raising=False)
    response=api.health()
    assert response.status_code==503
    body=json.loads(response.body)
    assert body['version']==api.app.version
    assert body['error_code']=='DATABASE_URL_MISSING'
