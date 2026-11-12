"""Deterministic offline regression tests for v22.
Run: cd backend && python test_v22_intelligence.py
"""
import os
import sys
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('ADMIN_PASSWORD', 'test-password')
os.environ.setdefault('SESSION_SECRET', 'offline-test-secret-32-plus-characters-long')
os.environ.setdefault('DB_PATH', '/tmp/davoodi_v22_test.sqlite3')
sys.path.insert(0, os.path.dirname(__file__))
import main as m
from market_intelligence import assess_and_dedupe, price_summary
from vehicle_nlp import identify_vehicle

VEHICLE={'brand':'هیوندای','model':'سانتافه','year':2025,'mileage':0,'condition':'صفر کیلومتر','city':'تهران','query':'هیوندای سانتافه 2025 صفر'}

def listing(n,price,domain='bama.ir',kind='listing',title=None,age=1):
    prefix='https://bama.ir/car/detail-' if domain=='bama.ir' else f'https://{domain}/v/listing/'
    return {'title':title or 'هیوندای سانتافه مدل 2025 صفر کیلومتر تهران',
            'content':'آگهی فروش خودرو با قیمت قطعی درج شده',
            'url':prefix+str(n), 'domain':domain, 'kind':kind,
            'price':price, 'mileage':0, 'year':2025, 'city':'تهران',
            'published_at':time.time()-age*86400, 'is_new':True, 'accepted':True, 'rejection_reason':None}

class MarketIntelligenceTests(unittest.TestCase):
    def test_model_aliases(self):
        for phrase in ['فیتیلی', 'فیدیلیتی', 'فیدلیتی پرایم', 'santa fe 2025', 'سانتافه نیوفیس ۲۰۲۵']:
            r=identify_vehicle(phrase)
            self.assertIsNotNone(r,phrase)
            self.assertIn(r['model'],['فیدلیتی','سانتافه'])
        p=m.parse_voice('فیتیلی پرایم مدل ۱۴۰۳ ۵۰ هزار کیلومتر')
        self.assertEqual((p['brand'],p['model'],p['trim'],p['year'],p['mileage']),('بهمن موتور','فیدلیتی','پرایم',1403,50000))
        p=m.parse_voice('سانتافه نیوفیس ۲۰۲۵ سفید اتوماتیک صفر کیلومتر')
        self.assertEqual((p['model'],p['year'],p['generation']),('سانتافه',2025,'نیوفیس'))
        p=m.parse_voice('فیدلیتی مدل ۱۴۰۳')
        self.assertEqual(p['questions'],['فیدلیتی پرایم، پرستیژ یا الیت است؟'])

    def test_articles_rejected(self):
        a=listing(1,4_000_000_000,title='بررسی هیوندای سانتافه مشخصات فنی')
        a['kind']='article'
        assess_and_dedupe([a],VEHICLE)
        self.assertFalse(a['accepted'])

    def test_stale_rejected(self):
        a=listing(2,5_000_000_000,age=365)
        assess_and_dedupe([a],VEHICLE)
        self.assertFalse(a['accepted'])
        self.assertIn('قدیمی',a['rejection_reason'])

    def test_duplicate_urls(self):
        a=listing(1,5_000_000_000)
        b=listing(1,5_000_000_000)
        b['url'] += '?utm_source=bot'
        assess_and_dedupe([a,b],VEHICLE)
        self.assertEqual(sum(i['accepted'] for i in [a,b]),1)
        self.assertIn('تکراری',b['rejection_reason'])

    def test_year_mismatch(self):
        a=listing(1,5_000_000_000)
        a['year']=2015
        assess_and_dedupe([a],VEHICLE)
        self.assertFalse(a['accepted'])

    def test_outlier_and_market_reference(self):
        rows=[listing(i,price,domain=['bama.ir','divar.ir','sheypoor.com'][i%3])
              for i,price in enumerate((5_600_000_000,5_700_000_000,5_800_000_000,5_900_000_000,5_950_000_000,6_050_000_000,6_150_000_000,60_000_000_000))]
        rows[-1]['price']=60_000_000_000
        assess_and_dedupe(rows,VEHICLE)
        stats=price_summary(rows,0)
        self.assertEqual(stats['outliers_removed'],1)
        self.assertEqual(stats['sample_count'],7)
        self.assertGreater(stats['price_average'],5_600_000_000)
        self.assertLess(stats['price_average'],6_150_000_000)
        self.assertEqual(stats['domain_count'],3)
        self.assertEqual(stats['sample_count'],sum(x['count'] for x in stats['histogram']))
        self.assertFalse(stats['confidence_is_probability'])

    def test_reference_only_not_quoted_as_market(self):
        rows=[listing(i,5_000_000_000+i*100_000_000,kind='market_price') for i in range(5)]
        assess_and_dedupe(rows,VEHICLE)
        stats=price_summary(rows,0)
        self.assertTrue(stats['limited_evidence'])
        self.assertIsNone(stats['price_average'])

    def test_small_sample_no_quote(self):
        rows=[listing(i,5_000_000_000+i*100_000_000) for i in range(2)]
        assess_and_dedupe(rows,VEHICLE)
        stats=price_summary(rows,0)
        self.assertTrue(stats['limited_evidence'])
        self.assertIsNone(stats['suggested_min'])

    def test_three_observations_with_extreme_outlier(self):
        rows=[listing(i,p) for i,p in enumerate((5_700_000_000,5_800_000_000,90_000_000_000))]
        assess_and_dedupe(rows,VEHICLE)
        stats=price_summary(rows,0)
        self.assertEqual(stats['outliers_removed'],1)
        self.assertIsNone(stats['price_average'])
        self.assertTrue(stats['limited_evidence'])

    def test_unnamed_model_mismatch(self):
        a=listing(1,5_000_000_000,title='هیوندای توسان 2025 صفر کیلومتر تهران')
        assess_and_dedupe([a],VEHICLE)
        self.assertFalse(a['accepted'])

    def test_integration_offline(self):
        article={'url':'https://bama.ir/car-reviews/santafe','title':'بررسی سانتافه 2025 مشخصات فنی'}
        fake_rows={
            'bama.ir':[article,{'url':'https://bama.ir/car/detail-101','title':'هیوندای سانتافه 2025 صفر کیلومتر قیمت ۵ میلیارد و ۸۰۰ میلیون تومان','kind':'listing','year':2025,'mileage':0,'published_at':time.time()-86400}],
            'divar.ir':[{'url':'https://divar.ir/v/santafe/abc101','title':'هیوندای سانتافه 2025 صفر کیلومتر قیمت ۵ میلیارد و ۹۰۰ میلیون تومان','kind':'listing','year':2025,'mileage':0,'published_at':time.time()-86400}],
            'sheypoor.com':[{'url':'https://sheypoor.com/s/abc101','title':'هیوندای سانتافه 2025 صفر کیلومتر قیمت ۶ میلیارد تومان','kind':'listing','year':2025,'mileage':0,'published_at':time.time()-86400}],
        }
        with patch.object(m,'AVALAI_KEY','offline-mock-key'),patch.object(m,'_direct_connector',return_value=None),patch.object(m,'_builtin_connector',return_value=None),patch.object(m,'_search_fallback_domain',side_effect=lambda vehicle,source:fake_rows.get(source['domain'],[])):
            old=m.MAX_DOMAIN_REQUESTS;m.MAX_DOMAIN_REQUESTS=6
            try:
                result=m.research_market(VEHICLE)
            finally:
                m.MAX_DOMAIN_REQUESTS=old
        self.assertEqual(result['new']['sample_count'],3)
        self.assertIsNotNone(result['new']['price_average'])
        self.assertEqual(result['new']['domain_count'],3)
        self.assertFalse(any('car-reviews' in x['url'] for x in result['sources']))
        self.assertEqual(result['vehicle']['year'],2025)

if __name__=='__main__':
    unittest.main(verbosity=2)
