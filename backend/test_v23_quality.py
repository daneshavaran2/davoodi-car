"""Full offline quality regression: API, market evidence, UX contracts, cache.

Run from backend: python test_v23_quality.py
No live marketplace requests, secret keys, or made-up 'current' prices.
"""
import os
import sys
import json
import time
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

os.environ.setdefault('ADMIN_PASSWORD','offline-testing-password')
os.environ.setdefault('SESSION_SECRET','offline-testing-secret-longer-than-32-characters')
os.environ.setdefault('SEARCH_COOLDOWN','0')
os.environ.setdefault('MAX_SEARCHES_PER_HOUR','1000')
os.environ.setdefault('AVALAI_API_KEY','')
os.environ.setdefault('OPENAI_API_KEY','')
_tmpdir=tempfile.TemporaryDirectory(prefix='davoodi_test_v23_')
os.environ['DB_PATH']=str(Path(_tmpdir.name)/'db.sqlite3')
sys.path.insert(0,str(Path(__file__).resolve().parent))

import main
from fastapi.testclient import TestClient
from market_intelligence import price_summary, assess_and_dedupe

client=TestClient(main.app)


def fake_listing(n,price,domain='bama.ir',year=2025,kind='listing',text=None,age_days=2):
    paths={
        'bama.ir':f'/car/detail-qa-{n}',
        'divar.ir':f'/v/hyundai-santafe/qa-{n}',
        'sheypoor.com':f'/s/qa-{n}',
        'khodro45.com':f'/price/qa-{n}',
    }
    return {'url':'https://'+domain+paths[domain],
            'title':text or 'هیوندای سانتافه مدل 2025 صفر کیلومتر تهران',
            'content':'قیمت پنج میلیارد و ۸۰۰ میلیون تومان',
            'price':price,'kind':kind,'year':year,'mileage':0,'is_new':True,
            'published_at':time.time()-age_days*86400,'city':'تهران'}


class SearchQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r=client.post('/api/login',json={'password':os.environ['ADMIN_PASSWORD']})
        assert r.status_code==200,r.text
        cls.headers={'Authorization':'Bearer '+r.json()['token']}

    def setUp(self):
        with main.db() as c:
            c.execute('DELETE FROM searches')
            c.execute('DELETE FROM domain_cache')
        main._cache.clear()
        main._recent_calls.clear()
        main._last_search[0]=0

    def test_health_and_login_auth(self):
        self.assertEqual(client.get('/api/health').json()['version'],'23.0.0-search-qa-ux')
        self.assertEqual(client.post('/api/login',json={'password':'wrong'}).status_code,401)
        self.assertEqual(client.post('/api/search',json={'query':'سانتافه ۲۰۲۵'}).status_code,401)

    def test_manual_text_extracts_brand_model_year_and_zero(self):
        with patch.object(main,'research_market',side_effect=lambda vehicle:{'vehicle':vehicle,'sources':[],'new':{},'used':{}}) as mock:
            r=client.post('/api/search',json={'query':'هیوندای سانتافه نیوفیس ۲۰۲۵ صفر کیلومتر'},headers=self.headers)
        self.assertEqual(r.status_code,200,r.text)
        v=mock.call_args.args[0]
        self.assertEqual((v['brand'],v['model'],v['year'],v['mileage']),('هیوندای','سانتافه',2025,0))

    def test_manual_fidelity_variant_and_mileage(self):
        with patch.object(main,'research_market',side_effect=lambda v:{'vehicle':v}) as mock:
            r=client.post('/api/search',json={'query':'فیتیلی پرایم مدل ۱۴۰۳ با کارکرد ۵۰ هزار کیلومتر'},headers=self.headers)
        self.assertEqual(r.status_code,200,r.text)
        v=mock.call_args.args[0]
        self.assertEqual((v['brand'],v['model'],v['trim'],v['year'],v['mileage']),('بهمن موتور','فیدلیتی','پرایم',1403,50000))

    def test_explicit_fields_override_auto_parser(self):
        with patch.object(main,'research_market',side_effect=lambda v:{'vehicle':v}) as mock:
            r=client.post('/api/search',json={'query':'سانتافه ۲۰۲۵ صفر','year':2024,'mileage':12345,'city':'تهران'},headers=self.headers)
        self.assertEqual(r.status_code,200,r.text)
        v=mock.call_args.args[0]
        self.assertEqual((v['year'],v['mileage'],v['city']),(2024,12345,'تهران'))

    def test_missing_model_is_actionable_422_no_paid_call(self):
        with patch.object(main,'research_market') as mock:
            r=client.post('/api/search',json={'query':'خودرو سفید مدل 2025'},headers=self.headers)
        self.assertEqual(r.status_code,422,r.text)
        self.assertIn('مدل',r.json()['detail'])
        mock.assert_not_called()

    def test_cache_then_real_refresh(self):
        n={'calls':0}
        def mock_search(vehicle):
            n['calls']+=1
            return {'engine':'test','vehicle':vehicle,'seq':n['calls'],'new':{},'used':{},'sources':[]}
        body={'query':'سانتافه مدل 2025 صفر کیلومتر'}
        with patch.object(main,'research_market',side_effect=mock_search):
            r1=client.post('/api/search',json=body,headers=self.headers).json()
            r2=client.post('/api/search',json=body,headers=self.headers).json()
            r3=client.post('/api/search',json={**body,'refresh':True},headers=self.headers).json()
        self.assertEqual([r1['seq'],r2['seq'],r3['seq']],[1,1,2])
        self.assertTrue(r2['cached'])
        self.assertFalse(r3['cached'])

    def test_cache_key_separates_year_and_mileage(self):
        def mock_search(vehicle):return {'vehicle':vehicle}
        with patch.object(main,'research_market',side_effect=mock_search) as p:
            for row in [{'query':'فیدلیتی مدل ۱۴۰۳','mileage':0},{'query':'فیدلیتی مدل ۱۴۰۳','mileage':40000},{'query':'فیدلیتی مدل ۱۴۰۲','mileage':0}]:
                self.assertEqual(client.post('/api/search',json=row,headers=self.headers).status_code,200)
        self.assertEqual(p.call_count,3)

    def test_full_research_three_listings_without_article(self):
        vehicle={'brand':'هیوندای','model':'سانتافه','year':2025,'mileage':0,'city':'تهران','query':'سانتافه ۲۰۲۵ صفر کیلومتر'}
        pages={
            'bama.ir':[{'url':'https://bama.ir/car-reviews/santafe','title':'بررسی سانتافه مشخصات فنی','price':6_000_000_000},fake_listing(1,5_700_000_000)],
            'divar.ir':[fake_listing(2,5_800_000_000,domain='divar.ir')],
            'sheypoor.com':[fake_listing(3,5_900_000_000,domain='sheypoor.com')],
        }
        with patch.object(main,'AVALAI_KEY','offline-mock-key'),patch.object(main,'_direct_connector',return_value=None),patch.object(main,'_builtin_connector',return_value=None),patch.object(main,'_search_fallback_domain',side_effect=lambda v,s:pages.get(s['domain'],[])):
            old=main.MAX_DOMAIN_REQUESTS;main.MAX_DOMAIN_REQUESTS=6
            try:result=main.research_market(vehicle)
            finally:main.MAX_DOMAIN_REQUESTS=old
        self.assertEqual(result['new']['sample_count'],3)
        self.assertEqual(result['diagnostics']['articles_removed'],1)
        self.assertEqual(len(result['sources']),3)
        self.assertTrue(all(x['accepted'] for x in result['sources']))
        self.assertGreater(result['new']['price_average'],0)
        self.assertEqual(result['vehicle']['year'],2025)

    def test_off_domain_connector_result_is_rejected(self):
        row=fake_listing(4,5_800_000_000)
        row['url']='https://not-bama.ir/car/detail-qa-phishing'
        r=main._normalize_result({'name':'باما','domain':'bama.ir'},row,{'model':'سانتافه','year':2025,'mileage':0,'brand':'هیوندای'})
        self.assertFalse(r['accepted'])
        self.assertIn('خارج از دامنه',r['rejection_reason'])

    def test_article_unknown_year_and_stale_rejected(self):
        v={'model':'سانتافه','brand':'هیوندای','year':2025,'mileage':0,'city':'تهران'}
        art=fake_listing(4,5_500_000_000)
        art['url']='https://bama.ir/blog/santa-fe'
        art['title']='بررسی هیوندای سانتافه مشخصات فنی'
        row=main._normalize_result({'name':'باما','domain':'bama.ir'},art,v)
        self.assertFalse(row['accepted'])
        self.assertIn(row['kind'],('article','unknown'))
        old=fake_listing(5,5_500_000_000,age_days=400)
        assess_and_dedupe([old],v)
        self.assertFalse(old['accepted'])

    def test_fallback_without_key_does_not_claim_completed_search(self):
        with patch.object(main,'AVALAI_KEY',''):
            with self.assertRaises(RuntimeError) as c:
                main._search_fallback_domain({'model':'سانتافه'},main.SOURCE_CONNECTORS[0])
        self.assertIn('AVALAI_API_KEY',str(c.exception))

    def test_one_or_two_sources_no_invented_market_average(self):
        rows=[fake_listing(10,5_800_000_000),fake_listing(11,5_850_000_000,domain='divar.ir')]
        v={'model':'سانتافه','brand':'هیوندای','year':2025,'mileage':0,'city':'تهران'}
        assess_and_dedupe(rows,v)
        result=price_summary(rows,0)
        self.assertEqual(result['sample_count'],2)
        self.assertTrue(result['limited_evidence'])
        self.assertIsNone(result['price_average'])

    def test_history_and_detail(self):
        with patch.object(main,'research_market',side_effect=lambda v:{'vehicle':v,'new':{},'used':{},'sources':[]}):
            r=client.post('/api/search',json={'query':'فیدلیتی مدل ۱۴۰۱'},headers=self.headers)
        self.assertEqual(r.status_code,200,r.text)
        hid=r.json()['history_id']
        self.assertEqual(client.get('/api/history/'+str(hid),headers=self.headers).status_code,200)
        self.assertIn('items',client.get('/api/history',headers=self.headers).json())

    def test_formatted_connector_fields(self):
        source={'name':'باما','domain':'bama.ir'}
        vehicle={'brand':'هیوندای','model':'سانتافه','year':2025,'mileage':0}
        row={'url':'https://bama.ir/car/detail-qa-formatted',
             'title':'هیوندای سانتافه صفر کیلومتر تهران','content':'فروش مستقیم خودرو',
             'price':'۵ میلیارد و ۸۰۰ میلیون تومان','year':'۲۰۲۵','mileage':'۰','is_new':True}
        out=main._normalize_result(source,row,vehicle)
        self.assertEqual(out['price'],5_800_000_000)
        self.assertEqual(out['year'],2025)
        self.assertEqual(out['mileage'],0)
        self.assertTrue(out['accepted'],out['rejection_reason'])

    def test_formatted_used_mileage(self):
        source={'name':'دیوار','domain':'divar.ir'}
        vehicle={'brand':'بهمن موتور','model':'فیدلیتی','year':1403,'mileage':50000}
        row={'url':'https://divar.ir/v/fidelity/qa-99',
             'title':'فیدلیتی پرایم ۱۴۰۳ بدون رنگ','content':'آگهی فروش فوری',
             'price':'۱٬۹۰۰٬۰۰۰٬۰۰۰','year':'۱۴۰۳','mileage':'۵۰ هزار'}
        out=main._normalize_result(source,row,vehicle)
        self.assertEqual(out['price'],1_900_000_000)
        self.assertEqual(out['year'],1403)
        self.assertEqual(out['mileage'],50000)
        self.assertTrue(out['accepted'],out['rejection_reason'])

    def test_unconfigured_search_is_visible(self):
        vehicle={'brand':'هیوندای','model':'سانتافه','year':2025,'mileage':0}
        with patch.object(main,'AVALAI_KEY',''),patch.object(main,'_direct_connector',return_value=None),patch.object(main,'_builtin_connector',return_value=None):
            result=main.research_market(vehicle)
        self.assertEqual(result['diagnostics']['accepted'],0)
        self.assertTrue(any(row['status']=='not_configured' for row in result['site_status']))
        self.assertTrue(any('AVALAI_API_KEY' in warning for warning in result['warnings']))

    def test_source_processing_runs_in_parallel(self):
        vehicle={'brand':'هیوندای','model':'سانتافه','year':2025,'mileage':0}
        def primary(source,vehicle):
            time.sleep(.06)
            return []
        def fallback(vehicle,source):
            time.sleep(.06)
            return []
        with patch.object(main,'AVALAI_KEY','offline-mock-key'),patch.object(main,'_direct_connector',side_effect=primary),patch.object(main,'_search_fallback_domain',side_effect=fallback):
            old=main.MAX_DOMAIN_REQUESTS;main.MAX_DOMAIN_REQUESTS=6
            try:
                started=time.monotonic();result=main.research_market(vehicle)
                elapsed=time.monotonic()-started
            finally:
                main.MAX_DOMAIN_REQUESTS=old
        self.assertEqual(len(result['site_status']),6)
        # Serial 12 calls * .06 ~= .72 seconds; 3 workers finish in ~.24.
        self.assertLess(elapsed,.60, f'Sources appear to be running sequentially: {elapsed:.2f}s')


    def test_native_bama_html_connector(self):
        from connectors import bama
        pages={
          'https://bama.ir/car':'<a href="/car/hyundai">خرید و فروش هیوندای</a>',
          'https://bama.ir/car/hyundai':'<a href="/car/hyundai/santafe">هیوندای سانتافه</a>',
          'https://bama.ir/car/hyundai/santafe':'<a href="/car/detail-123">هیوندای سانتافه مدل 2025 صفر کیلومتر قیمت ۵ میلیارد تومان</a>'
        }
        with patch.object(bama,'fetch_html',side_effect=lambda url,**kwargs:pages[url]):
            rows=bama.search({'brand':'هیوندای','model':'سانتافه'})
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['price'],5_000_000_000)
        self.assertEqual(rows[0]['kind'],'listing')

    def test_native_hamrah_html_connector(self):
        from connectors import hamrah
        pages={
           hamrah.BASE:'<a href="/cars-for-sale/hyundai/santafe/123">فروش هیوندای سانتافه</a>',
           'https://www.hamrah-mechanic.com/cars-for-sale/hyundai/santafe/123': '<html><title>فروش هیوندای سانتافه</title><body>هیوندای سانتافه مدل 2025 صفر کیلومتر قیمت ۵ میلیارد تومان</body></html>'
        }
        with patch.object(hamrah,'fetch_html',side_effect=lambda url,**kwargs:pages[url]):
            rows=hamrah.search({'brand':'هیوندای','model':'سانتافه'})
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['price'],5_000_000_000)

    def test_khodro45_editorial_excluded(self):
        from connectors import khodro45
        pages={
          khodro45.BASE+'price/':'<a href="/price/santafe">هیوندای سانتافه 2025 قیمت ۵ میلیارد تومان</a><a href="/mag/santafe">بررسی هیوندای سانتافه قیمت ۶ میلیارد تومان</a>',
          khodro45.BASE+'car-price/':'',
          khodro45.BASE:''
        }
        with patch.object(khodro45,'fetch_html',side_effect=lambda url,**kwargs:pages[url]):
            rows=khodro45.search({'brand':'هیوندای','model':'سانتافه'})
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['kind'],'market_price')
        self.assertNotIn('/mag/',rows[0]['url'])


    def test_end_to_end_manual_api_through_market_engine(self):
        pages={
          'bama.ir':[fake_listing(101,5_700_000_000)],
          'divar.ir':[fake_listing(102,5_800_000_000,domain='divar.ir')],
          'sheypoor.com':[fake_listing(103,5_900_000_000,domain='sheypoor.com')],
        }
        with patch.object(main,'AVALAI_KEY','offline-mock-key'),patch.object(main,'OPENAI_KEY',''),patch.object(main,'_direct_connector',return_value=None),patch.object(main,'_builtin_connector',return_value=None),patch.object(main,'_search_fallback_domain',side_effect=lambda v,s:pages.get(s['domain'],[])):
            old=main.MAX_DOMAIN_REQUESTS;main.MAX_DOMAIN_REQUESTS=6
            try:
                response=client.post('/api/search',json={'query':'سانتافه نیوفیس ۲۰۲۵ صفر کیلومتر','city':'تهران'},headers=self.headers)
            finally:main.MAX_DOMAIN_REQUESTS=old
        self.assertEqual(response.status_code,200,response.text)
        result=response.json()
        self.assertEqual(result['vehicle']['model'],'سانتافه')
        self.assertEqual(result['vehicle']['year'],2025)
        self.assertEqual(result['vehicle']['mileage'],0)
        self.assertEqual(result['new']['sample_count'],3)
        self.assertEqual(result['new']['price_median'],5_800_000_000)
        self.assertEqual(len(result['sources']),3)
        self.assertEqual(len(result['verified_source_urls']),3)


if __name__=='__main__':unittest.main(verbosity=2)
