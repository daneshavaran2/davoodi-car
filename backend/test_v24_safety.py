"""Independent regression checks for release blocking bugs; all data fabricated."""
import os, time, unittest
from unittest.mock import patch
os.environ.setdefault('ADMIN_PASSWORD','ci-test-password')
os.environ.setdefault('SESSION_SECRET','ci-test-secret-longer-than-thirty-two-chars')
os.environ.setdefault('DB_PATH','/tmp/davoodi-v24-unit.sqlite')
os.environ.setdefault('SEARCH_COOLDOWN','0')
import main
from fastapi.testclient import TestClient
from safety_v24 import explicit_vehicle_price,mileage_from_description,new_status,body_group
from market_intelligence import score_evidence

class PriceQualityTests(unittest.TestCase):
    def test_price_ignores_commission(self):
        self.assertEqual(explicit_vehicle_price('قیمت خودرو ۵ میلیارد تومان، کارمزد ۳۰۰ میلیون تومان'),5_000_000_000)
        self.assertEqual(main._price_from_text('قیمت خودرو ۵ میلیارد تومان کارمزد ۳۰۰ میلیون تومان'),5_000_000_000)
    def test_price_rejects_financing_only(self):
        self.assertIsNone(explicit_vehicle_price('پیش پرداخت ۷۰۰ میلیون تومان قسط ماهانه ۸۰ میلیون تومان'))
    def test_ambiguous_two_prices_abstain(self):
        self.assertIsNone(explicit_vehicle_price('۵ میلیارد تومان یا ۶ میلیارد تومان'))
    def test_price_compound(self):
        self.assertEqual(explicit_vehicle_price('قیمت ۲ میلیارد و ۸۰۰ میلیون تومان'),2_800_000_000)
    def test_mileage_year_not_borrowed(self):
        self.assertEqual(mileage_from_description('فیدلیتی مدل ۱۴۰۳ کارکرد ۵۰ هزار'),50_000)
        v=main.parse_voice('فیدلیتی مدل ۱۴۰۳ کارکرد ۵۰ هزار')
        self.assertEqual((v['year'],v['mileage']),(1403,50000))
    def test_delivery_now_is_not_new(self):
        self.assertIsNone(new_status('فیدلیتی مدل ۱۴۰۳ تحویل فوری'))
        self.assertEqual(main._normalize_result({'name':'باما','domain':'bama.ir'},
            {'url':'https://bama.ir/car/detail-one','title':'فیدلیتی مدل ۱۴۰۳ تحویل فوری',
            'price':2_000_000_000,'kind':'listing','year':1403},
            {'brand':'بهمن موتور','model':'فیدلیتی','year':1403,'mileage':0})['is_new'],None)
    def test_variant_conflict(self):
        candidate={'kind':'listing','price':3_000_000_000,'url':'https://bama.ir/car/detail-qa',
                   'title':'فیدلیتی پرستیژ مدل ۱۴۰۳','content':'فیدلیتی پرستیژ','trim':'پرستیژ',
                   'mileage':45000,'is_new':False,'year':1403,'published_at':time.time()}
        score,reason=score_evidence(candidate,{'model':'فیدلیتی','trim':'پرایم','year':1403,'mileage':50000})
        self.assertIn('تیپ',reason)
    def test_unknown_variant_rejected_when_specific(self):
        candidate={'kind':'listing','price':3_000_000_000,'url':'https://bama.ir/car/detail-qa',
                   'title':'فیدلیتی مدل ۱۴۰۳','content':'فیدلیتی','trim':None,
                   'mileage':45000,'is_new':False,'year':1403,'published_at':time.time()}
        score,reason=score_evidence(candidate,{'model':'فیدلیتی','trim':'پرایم','year':1403,'mileage':50000})
        self.assertIn('تیپ',reason)
    def test_body_damage_mismatch(self):
        candidate={'kind':'listing','price':3_000_000_000,'url':'https://bama.ir/car/detail-qa',
                   'title':'فیدلیتی مدل ۱۴۰۳','content':'بدون رنگ','condition':'بدون رنگ',
                   'mileage':45000,'is_new':False,'year':1403,'published_at':time.time()}
        score,reason=score_evidence(candidate,{'model':'فیدلیتی','year':1403,'mileage':50000,'condition':'گلگیر رنگ‌شده'})
        self.assertIn('بدنه',reason)
    def test_body_dent_is_not_clean(self):
        self.assertEqual(body_group('گلگیر ضربه‌خورده بدون رنگ'),'damaged')
        self.assertEqual(body_group('بدون رنگ'),'clean')
    def test_color_mismatch_rejects_when_known(self):
        candidate={'kind':'listing','price':3_000_000_000,'url':'https://bama.ir/car/detail-qa',
                   'title':'فیدلیتی مدل ۱۴۰۳ قرمز','content':'','year':1403,'mileage':50000,'is_new':False}
        score,reason=score_evidence(candidate,{'model':'فیدلیتی','year':1403,'mileage':50000,'color':'سفید'})
        self.assertIn('رنگ خودرو',reason)
    def test_no_unknown_zero_evidence(self):
        item={'kind':'listing','price':3_000_000_000,'url':'https://bama.ir/car/detail-qa',
              'title':'فیدلیتی مدل ۱۴۰۳ تحویل فوری','content':'','mileage':None,'is_new':None,'year':1403}
        score,reason=score_evidence(item,{'model':'فیدلیتی','year':1403,'mileage':0})
        self.assertIn('صفر',reason)
    def test_throttle_failed_login(self):
        app=TestClient(main.app)
        with main._login_lock:
            main._login_failures.clear(); main._login_blocked_until.clear()
        for i in range(5):
            r=app.post('/api/login',json={'password':'bad'})
            self.assertEqual(r.status_code,401)
        r=app.post('/api/login',json={'password':'bad'})
        self.assertEqual(r.status_code,429)
        with main._login_lock:
            main._login_failures.clear(); main._login_blocked_until.clear()
    def test_progress_requires_auth(self):
        self.assertEqual(TestClient(main.app).get('/api/search-progress/abc-1234567890123456').status_code,401)


class SourceAndConcurrencyTests(unittest.TestCase):
    def test_jsonld_offer_and_actual_posting_date(self):
        from connectors.common import listing_metadata
        page="""<html><script type="application/ld+json">{"@type":"Car","name":"فیدلیتی","datePublished":"2026-11-11T12:00:00+03:30","mileageFromOdometer":{"value":45000},"offers":{"@type":"Offer","price":30000000000,"priceCurrency":"IRR"}}</script></html>"""
        result=listing_metadata(page)
        self.assertEqual(result['price'],3_000_000_000)
        self.assertEqual(result['mileage'],45000)
        self.assertEqual(result['published_at'],'2026-11-11T12:00:00+03:30')

    def test_jsonld_unknown_currency_abstains(self):
        from connectors.common import listing_metadata
        page="""<script type="application/ld+json">{"@type":"Car","offers":{"price":"5000000000","priceCurrency":"USD"}}</script>"""
        self.assertIsNone(listing_metadata(page)['price'])

    def test_bama_link_host_not_substring(self):
        from connectors.common import same_host
        self.assertTrue(same_host('https://bama.ir/car/detail-aaa','bama.ir'))
        self.assertFalse(same_host('https://bama.ir.evil.example/car/detail-aaa','bama.ir'))

    def test_progress_endpoint_records_actual_stage(self):
        from fastapi.testclient import TestClient
        with main._login_lock:
            main._login_failures.clear();main._login_blocked_until.clear()
        app=TestClient(main.app)
        token=app.post('/api/login',json={'password':os.environ['ADMIN_PASSWORD']}).json()['token']
        headers={'Authorization':'Bearer '+token}
        job='v24-test-progress-uuid-00000001'
        def fake_market(vehicle):
            main.progress_report('بررسی منابع',2,6,'باما')
            return {'vehicle':vehicle,'sources':[],'new':{},'used':{}}
        with patch.object(main,'research_market',side_effect=fake_market),patch.object(main,'SEARCH_COOLDOWN',0),patch.object(main,'MAX_SEARCHES_PER_HOUR',1000):
            result=app.post('/api/search',json={'query':'هیوندای سانتافه مدل 2025','request_id':job,'refresh':True},headers=headers)
        self.assertEqual(result.status_code,200,result.text)
        st=app.get('/api/search-progress/'+job,headers=headers).json()
        self.assertEqual(st['stage'],'تکمیل شد')
        self.assertEqual(st['done'],1)
        self.assertIn('response_ms',result.json())

    def test_three_parallel_requests_do_not_global_queue(self):
        from concurrent.futures import ThreadPoolExecutor
        from fastapi.testclient import TestClient
        import threading
        client=TestClient(main.app)
        with main._login_lock:
            main._login_failures.clear();main._login_blocked_until.clear()
        token=client.post('/api/login',json={'password':os.environ['ADMIN_PASSWORD']}).json()['token']
        headers={'Authorization':'Bearer '+token}
        barrier=threading.Barrier(2,timeout=5)
        def fake_market(vehicle):
            barrier.wait()
            return {'vehicle':vehicle,'sources':[],'new':{},'used':{}}
        def call(year):
            return client.post('/api/search',json={'query':f'هیوندای سانتافه مدل {year}', 'refresh':True},headers=headers)
        with patch.object(main,'research_market',side_effect=fake_market),patch.object(main,'SEARCH_COOLDOWN',0),patch.object(main,'MAX_SEARCHES_PER_HOUR',1000):
            with ThreadPoolExecutor(max_workers=2) as pool:
                a=pool.submit(call,2024);b=pool.submit(call,2025)
                self.assertEqual(a.result(timeout=8).status_code,200)
                self.assertEqual(b.result(timeout=8).status_code,200)

if __name__=='__main__':unittest.main(verbosity=2)
