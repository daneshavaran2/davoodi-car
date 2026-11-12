"""Independent v24 regression suite, all market responses are fixtures (not live prices)."""
import os,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('ADMIN_PASSWORD','qa-only-password')
os.environ.setdefault('SESSION_SECRET','offline-qa-very-long-secret-1234567890')
os.environ.setdefault('SEARCH_COOLDOWN','0')
os.environ.setdefault('MAX_SEARCHES_PER_HOUR','500')
os.environ.setdefault('AVALAI_API_KEY','')
os.environ.setdefault('OPENAI_API_KEY','')
_tmp=tempfile.TemporaryDirectory(prefix='davoodi24_')
os.environ['DB_PATH']=str(Path(_tmp.name)/'db.sqlite3')
sys.path.insert(0,str(Path(__file__).resolve().parent))
import main
from market_parsers import parse_price,parse_mileage,is_new_vehicle
from market_intelligence import assess_and_dedupe,price_summary
from connectors.common import structured_listing_fields
from fastapi.testclient import TestClient

client=TestClient(main.app)

class ReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r=client.post('/api/login',json={'password':os.environ['ADMIN_PASSWORD']})
        assert r.status_code==200,r.text
        cls.headers={'Authorization':'Bearer '+r.json()['token']}
    def setUp(self):
        with main.db() as c:c.execute('DELETE FROM searches');c.execute('DELETE FROM domain_cache')
        main._cache.clear();main._recent_calls.clear();main._last_search.clear()

    def listing(self,**override):
        row={'title':'فیدلیتی پرایم مدل ۱۴۰۳ کارکرد ۵۰ هزار کیلومتر بدون رنگ اتوماتیک',
             'content':'قیمت خودرو ۲ میلیارد و ۵۰۰ میلیون تومان',
             'url':'https://bama.ir/car/detail-v24-111','domain':'bama.ir','kind':'listing',
             'price':2_500_000_000,'year':1403,'trim':'پرایم','mileage':50000,
             'condition':'بدون رنگ','transmission':'اتوماتیک','is_new':False,
             'published_at':time.time()-86400,'city':'تهران','accepted':True,'rejection_reason':None}
        row.update(override);return row
    def vehicle(self,**override):
        v={'brand':'بهمن موتور','model':'فیدلیتی','trim':'پرایم','year':1403,'mileage':50000,
           'condition':'بدون رنگ','transmission':'اتوماتیک','city':'تهران'}
        v.update(override);return v
    def test_car_price_not_commission(self):
        self.assertEqual(parse_price('قیمت خودرو ۵ میلیارد تومان، کارمزد ۳۰۰ میلیون تومان'),5_000_000_000)
    def test_ambiguous_multiple_prices_not_invented(self):
        self.assertIsNone(parse_price('قیمت ۵ میلیارد تومان، قیمت ۶ میلیارد تومان'))
    def test_deposit_not_car_price(self):
        self.assertIsNone(parse_price('پیش پرداخت ۳۰۰ میلیون تومان'))
    def test_rial_conversion(self):
        self.assertEqual(parse_price('قیمت ۵۰۰۰۰۰۰۰۰۰۰ ریال'),5_000_000_000)
    def test_km_after_keyword(self):
        self.assertEqual(main.parse_voice('فیدلیتی مدل ۱۴۰۳ کارکرد ۵۰ هزار')['mileage'],50000)
    def test_km_before_keyword(self):
        self.assertEqual(main.parse_voice('فیدلیتی مدل ۱۴۰۳، ۵۰ هزار کیلومتر')['mileage'],50000)
    def test_km_spoken(self):
        self.assertEqual(parse_mileage('پنجاه هزار تا کارکرد'),50000)
    def test_year_is_not_km(self):
        self.assertIsNone(parse_mileage('فیدلیتی مدل ۱۴۰۳'))
    def test_used_car_is_not_new_from_delivery(self):
        self.assertFalse(is_new_vehicle('سانتافه کارکرد ۵۰۰۰۰ تحویل فوری',50000))
        source={'name':'باما','domain':'bama.ir'}
        row=main._normalize_result(source,{'url':'https://bama.ir/car/detail-55',
              'title':'فیدلیتی پرایم ۱۴۰۳ کارکرد ۵۰ هزار تحویل فوری','kind':'listing',
              'price':2_500_000_000,'year':1403,'mileage':50000,'trim':'پرایم'},self.vehicle())
        self.assertFalse(row['is_new'])
    def test_trim_from_title(self):
        source={'name':'باما','domain':'bama.ir'}
        row=main._normalize_result(source,{'url':'https://bama.ir/car/detail-56',
              'title':'فیدلیتی پرستیژ مدل ۱۴۰۳','kind':'listing','price':2_500_000_000,
              'year':1403,'mileage':50000,'published_at':time.time()-86400},self.vehicle())
        self.assertEqual(row['trim'],'پرستیژ')
        assess_and_dedupe([row],self.vehicle())
        self.assertFalse(row['accepted']);self.assertIn('تیپ',row['rejection_reason'])
    def test_missing_trim_needs_review(self):
        row=self.listing(trim=None,title='فیدلیتی مدل ۱۴۰۳ کارکرد ۵۰ هزار کیلومتر')
        assess_and_dedupe([row],self.vehicle())
        self.assertFalse(row['accepted']);self.assertTrue(row['review_required'])
    def test_unknown_publication_date_needs_review(self):
        row=self.listing(published_at=None)
        assess_and_dedupe([row],self.vehicle())
        self.assertFalse(row['accepted']);self.assertTrue(row['review_required'])
    def test_unknown_year_needs_review(self):
        row=self.listing(year=None)
        assess_and_dedupe([row],self.vehicle())
        self.assertFalse(row['accepted']);self.assertTrue(row['review_required'])
    def test_transmission_conflict(self):
        row=self.listing(transmission='دستی')
        assess_and_dedupe([row],self.vehicle())
        self.assertFalse(row['accepted']);self.assertIn('گیربکس',row['rejection_reason'])
    def test_body_condition_conflict(self):
        row=self.listing(condition='رنگ‌شده')
        assess_and_dedupe([row],self.vehicle())
        self.assertFalse(row['accepted']);self.assertIn('بدنه',row['rejection_reason'])
    def test_mileage_big_difference(self):
        row=self.listing(mileage=150000)
        assess_and_dedupe([row],self.vehicle())
        self.assertFalse(row['accepted']);self.assertIn('کارکرد',row['rejection_reason'])
    def test_listing_stale(self):
        row=self.listing(published_at=time.time()-65*86400)
        assess_and_dedupe([row],self.vehicle())
        self.assertFalse(row['accepted']);self.assertIn('قدیمی',row['rejection_reason'])
    def test_low_sample_not_quoted(self):
        row=self.listing();assess_and_dedupe([row],self.vehicle())
        self.assertIsNone(price_summary([row],50000)['price_average'])
    def test_single_domain_not_quoted_even_3(self):
        rows=[self.listing(url=f'https://bama.ir/car/detail-abc{i}',price=2_500_000_000+i*15_000_000) for i in range(3)]
        assess_and_dedupe(rows,self.vehicle())
        self.assertIsNone(price_summary(rows,50000)['price_average'])
    def test_3_samples_2_domains_quoted(self):
        rows=[self.listing(url=f'https://bama.ir/car/detail-abc{i}',price=2_500_000_000+i*15_000_000) for i in range(2)]
        rows.append(self.listing(url='https://divar.ir/v/fidelity/abc3',domain='divar.ir',price=2_600_000_000))
        assess_and_dedupe(rows,self.vehicle())
        self.assertIsNotNone(price_summary(rows,50000)['price_average'])
    def test_unverified_raw_result_must_not_show_valid_evidence_badge(self):
        vehicle=self.vehicle()
        raw={'url':'https://divar.ir/v/fidelity-v24','title':'فیدلیتی پرایم مدل ۱۴۰۳ کارکرد ۵۰ هزار بدون رنگ',
             'kind':'listing','price':2500000000,'year':1403,'trim':'پرایم','mileage':50000,
             'condition':'بدون رنگ','transmission':'اتوماتیک','published_at':None}
        def direct(source,vehicle):
            return [raw] if source['domain']=='divar.ir' else []
        with patch.object(main,'_direct_connector',side_effect=direct):
            with patch.object(main,'_builtin_connector',return_value=[]):
                result=main.research_market(vehicle)
        st=next(x for x in result['site_status'] if x['domain']=='divar.ir')
        self.assertEqual(st['accepted_count'],0)
        self.assertNotEqual(st['status'],'evidence')
        self.assertEqual(result['diagnostics']['accepted'],0)

    def test_jsonld_time_and_currency(self):
        raw='<html><script type="application/ld+json">{"@type":"Offer","datePublished":"2026-11-09T12:00:00+03:30","price":"25000000000","priceCurrency":"IRR"}</script></html>'
        found=structured_listing_fields(raw)
        self.assertEqual(found['price'],2_500_000_000)
        self.assertIn('2026-11-09',found['published_at'])
    def test_login_limited(self):
        with main.db() as c:c.execute('DELETE FROM login_attempts')
        statuses=[client.post('/api/login',json={'password':'wrong'}).status_code for _ in range(main.LOGIN_MAX_ATTEMPTS+1)]
        self.assertEqual(statuses[-1],429)
        with main.db() as c:c.execute('DELETE FROM login_attempts')
    def test_unique_sessions(self):
        a=client.post('/api/login',json={'password':os.environ['ADMIN_PASSWORD']}).json()['token']
        b=client.post('/api/login',json={'password':os.environ['ADMIN_PASSWORD']}).json()['token']
        self.assertNotEqual(a,b)
    def test_logout_revokes_token(self):
        token=client.post('/api/login',json={'password':os.environ['ADMIN_PASSWORD']}).json()['token']
        headers={'Authorization':'Bearer '+token}
        self.assertEqual(client.post('/api/logout',headers=headers).status_code,200)
        self.assertEqual(client.get('/api/history',headers=headers).status_code,401)

    def test_stale_cache_cap(self):
        key='test-stale'; old=time.time()-main.STALE_MAX_AGE-10
        with main.db() as c:c.execute('INSERT INTO searches(query,cache_key,result_json,created_at) VALUES (?,?,?,?)',('test',key,'{}',old))
        self.assertIsNone(main.saved(key,main.STALE_MAX_AGE))
    def test_unconfirmed_trim_no_paid_search(self):
        with patch.object(main,'research_market') as mock:
            r=client.post('/api/search/jobs',headers=self.headers,json={'query':'فیدلیتی مدل ۱۴۰۳ صفر کیلومتر'})
        self.assertEqual(r.status_code,422);self.assertIn('تیپ',r.json()['detail']);mock.assert_not_called()

    def test_missing_used_body_no_paid_search(self):
        with patch.object(main,'research_market') as mock:
            r=client.post('/api/search/jobs',headers=self.headers,json={'query':'فیدلیتی پرایم مدل ۱۴۰۳ کارکرد ۵۰ هزار'})
        self.assertEqual(r.status_code,422);self.assertIn('بدنه',r.json()['detail']);mock.assert_not_called()

    def test_missing_year_no_paid_search(self):
        with patch.object(main,'research_market') as mock:
            r=client.post('/api/search/jobs',headers=self.headers,json={'query':'فیدلیتی پرایم صفر کیلومتر'})
        self.assertEqual(r.status_code,422);self.assertIn('سال',r.json()['detail']);mock.assert_not_called()

    def test_async_search_job_real_progress_and_owner_isolation(self):
        def fake_market(v):
            for source in main.SOURCE_CONNECTORS:main._emit_source_status(source['domain'],'connector')
            return {'vehicle':v,'sources':[],'new':{},'used':{},'diagnostics':{'accepted':0}}
        with patch.object(main,'research_market',side_effect=fake_market):
            r=client.post('/api/search/jobs',headers=self.headers,json={'query':'فیدلیتی پرایم مدل ۱۴۰۳ کارکرد ۵۰ هزار بدون رنگ'})
            self.assertEqual(r.status_code,202,r.text)
            ident=r.json()['job_id']
            result={}
            for _ in range(50):
                status=client.get('/api/search/jobs/'+ident,headers=self.headers)
                self.assertEqual(status.status_code,200,status.text)
                result=status.json()
                if result['status'] in ('failed','completed'):break
                time.sleep(.03)
            self.assertEqual(result['status'],'completed',result)
            self.assertEqual(result['progress'],100)
            self.assertEqual(len(result['source_status']),len(main.SOURCE_CONNECTORS))
            other=client.post('/api/login',json={'password':os.environ['ADMIN_PASSWORD']}).json()['token']
            self.assertEqual(client.get('/api/search/jobs/'+ident,headers={'Authorization':'Bearer '+other}).status_code,404)

if __name__=='__main__':unittest.main(verbosity=2)
