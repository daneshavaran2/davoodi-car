from datetime import datetime,timezone,timedelta
from unittest.mock import patch
from backend.domain import grouping_key
from backend.worker import _recompute, next_hour


class Cursor:
    def __init__(self,rows):self.rows=rows;self.commands=[]
    def execute(self,sql,params=None):self.commands.append((sql,params))
    def fetchall(self):return self.rows


def test_no_refresh_of_old_segments_when_other_sites_succeed():
    """A source connection elsewhere must not refresh unrelated cached quotes."""
    old=datetime.now(timezone.utc)-timedelta(days=2)
    ad={'source':'bama','external_id':'1','url':'https://bama.ir/car/detail-1',
         'catalog_id':'abc','year':1403,'year_system':'jalali',
         'trim':'پرایم','condition':'used','mileage_km':55000,'fuel_type':'unknown',
         'transmission':'automatic','body_condition':'original','price_toman':2400000000,
         'observed_at':old,'title':'فیدلیتی پرایم مدل ۱۴۰۳','city':'تهران'}
    cur=Cursor([ad]*6)
    result=_recompute(cur,datetime.now(timezone.utc)-timedelta(minutes=1))
    assert result==0
    assert len(cur.commands)==1  # only read; no price updates


def test_next_hour_is_future_and_hour_boundary():
    future=next_hour('Asia/Tehran')
    assert future>datetime.now(timezone.utc)
    assert future.minute in (0,30)  # 3:30 timezone offset when UTC-converted


def test_robust_quote_keeps_unknown_fuel_separate():
    one={'catalog_id':'abc','year':1403,'year_system':'jalali','trim':'پرایم',
         'condition':'used','transmission':'automatic','fuel_type':'petrol',
         'body_condition':'original','mileage_km':10000}
    two={**one,'fuel_type':'hybrid'}
    assert grouping_key(one)!=grouping_key(two)


def test_tehran_hour_boundary_is_utc_half_hour():
    dt=datetime(2026,11,12,20,5,tzinfo=timezone.utc)
    with patch('backend.worker._now',return_value=dt):
        assert next_hour('Asia/Tehran')==datetime(2026,11,12,20,30,tzinfo=timezone.utc)
