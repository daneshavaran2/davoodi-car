"""Regression tests for v27 market extraction and failure transparency.

All tests run offline; live third-party site access is intentionally NOT claimed.
"""
import os
os.environ.setdefault('ADMIN_PASSWORD', 'offline-v27-unit-test-password')
os.environ.setdefault('SESSION_SECRET', 'offline-v27-unit-test-session-secret-32-chars-min')
os.environ.setdefault('DB_PATH', '/tmp/davoodi-v27-test.sqlite3')

import unittest
from unittest.mock import patch

from connectors.divar import _is_detail
from connectors.extract import listing_cards_from_html, detail_fields
from connectors.browser import AD_LINK_READY_JS
import main


class ExtractionV27Tests(unittest.TestCase):
    def test_short_and_long_divar_ad_urls(self):
        for url in ('https://divar.ir/v/AaXmEgkp',
                    'https://divar.ir/v/فیدلیتی-پرایم/AB12345'):
            self.assertTrue(_is_detail(url), url)
            self.assertEqual(main._kind_from_url_title(url, 'فیدلیتی پرایم ۱۴۰۳'), 'listing')
        self.assertFalse(_is_detail('https://divar.ir/s/tehran/car'))
        self.assertFalse(_is_detail('https://divar.ir.attacker.tld/v/abc123'))
        self.assertIn('(?:[^/?#]+\\/)?', AD_LINK_READY_JS)

    def test_numeric_price_widget_without_currency_does_not_steal_another_card(self):
        raw='''<main>
          <article><a href="/car/detail-11"><h3>فیدلیتی پرایم ۱۴۰۳</h3></a>
             <div class="ad-price">۲,۴۰۰,۰۰۰,۰۰۰</div><span>کارکرد ۵۰ هزار کیلومتر</span></article>
          <article><a href="/car/detail-22"><h3>فیدلیتی پرستیژ ۱۴۰۳</h3></a>
             <div class="ad-price">۳,۲۰۰,۰۰۰,۰۰۰</div><span>کارکرد ۳۰ هزار کیلومتر</span></article>
        </main>'''
        cards=listing_cards_from_html(raw,'https://bama.ir/car',
                                       lambda u:u.startswith('https://bama.ir/car/detail-'))
        self.assertEqual(len(cards),2)
        self.assertEqual([x['price'] for x in cards],[2_400_000_000,3_200_000_000])
        self.assertEqual(cards[0]['mileage'],50000)

    def test_price_widget_fee_not_asking_price(self):
        raw='''<main><h1>فیدلیتی</h1>
        <span class="price">اقساط ۳,۰۰۰,۰۰۰,۰۰۰ تومان</span></main>'''
        self.assertIsNone(detail_fields(raw)['price'])

    @patch.object(main, 'domain_persist')
    @patch.object(main, 'domain_saved', return_value=None)
    def test_search_snippet_never_counts_as_verification(self, _saved, _persist):
        rows=[{'link':'https://divar.ir/v/ABC12345',
               'title':'فیدلیتی پرایم ۱۴۰۳ کارکرد ۵۰ هزار',
               'snippet':'قیمت خودرو ۴ میلیارد تومان'}]
        actual='''<main><h1>فیدلیتی پرایم ۱۴۰۳</h1>
                  <p>کارکرد ۵۰ هزار کیلومتر</p></main>'''
        vehicle={'brand':'بهمن موتور','model':'فیدلیتی','year':1403,'trim':'پرایم','mileage':50000}
        source={'name':'دیوار','domain':'divar.ir'}
        with patch.object(main,'AVALAI_KEY','test-key'), \
             patch.object(main,'post_json',return_value={'results':rows}), \
             patch('connectors.common.fetch_html',return_value=actual):
            self.assertEqual(main._search_fallback_domain(vehicle,source),[])
        _persist.assert_not_called()

    @patch.object(main, 'domain_persist')
    @patch.object(main, 'domain_saved', return_value=None)
    def test_page_verified_price_used_not_snippet_price(self, _saved, _persist):
        rows=[{'link':'https://divar.ir/v/ABC12345',
               'title':'فیدلیتی پرایم ۱۴۰۳',
               'snippet':'قیمت خودرو ۴ میلیارد تومان'}]
        actual='''<main><h1>فیدلیتی پرایم ۱۴۰۳</h1>
            <div class="car-price">قیمت خودرو ۲ میلیارد و ۵۰۰ میلیون تومان</div>
            <p>کارکرد ۵۰ هزار کیلومتر</p></main>'''
        vehicle={'brand':'بهمن موتور','model':'فیدلیتی','year':1403,'trim':'پرایم','mileage':50000}
        source={'name':'دیوار','domain':'divar.ir'}
        with patch.object(main,'AVALAI_KEY','test-key'), \
             patch.object(main,'post_json',return_value={'results':rows}), \
             patch('connectors.common.fetch_html',return_value=actual):
            res=main._search_fallback_domain(vehicle,source)
        self.assertEqual(res[0]['price'],2_500_000_000)
        self.assertNotEqual(res[0]['price'],4_000_000_000)
        self.assertEqual(res[0]['kind'],'listing')
        _persist.assert_called_once()

    def test_browser_knows_detail_pages_vs_search_pages(self):
        from connectors.browser import _is_detail_page
        self.assertTrue(_is_detail_page('https://divar.ir/v/AaXmEgkp'))
        self.assertTrue(_is_detail_page('https://bama.ir/car/detail-123456'))
        self.assertTrue(_is_detail_page('https://hamrah-mechanic.com/cars-for-sale/brand/model/1234'))
        self.assertFalse(_is_detail_page('https://divar.ir/s/tehran/car'))

    def test_mismatched_card_and_detail_price_is_rejected(self):
        from connectors import bama
        listing='''<article><a href="/car/detail-111"><h3>فیدلیتی پرایم ۱۴۰۳</h3></a>
          <span>کارکرد ۵۰ هزار کیلومتر</span><span>قیمت خودرو ۲ میلیارد تومان</span></article>'''
        detail='''<main><h1>فیدلیتی پرایم ۱۴۰۳</h1>
           <span>کارکرد ۵۰ هزار کیلومتر</span>
           <p>قیمت خودرو ۳ میلیارد تومان</p></main>'''
        with patch.object(bama, 'fetch_html', side_effect=lambda u,**kw:listing if u.endswith('/car') else detail):
            rows=bama.search({'brand':'بهمن موتور','model':'فیدلیتی'},limit=3)
        self.assertEqual(len(rows),1)
        self.assertTrue(rows[0]['price_conflict'])
        car={'brand':'بهمن موتور','model':'فیدلیتی','trim':'پرایم',
             'year':1403,'mileage':50000}
        normalized=main._normalize_result({'name':'باما','domain':'bama.ir'},rows[0],car)
        self.assertFalse(normalized['accepted'])
        self.assertIn('ناسازگار',normalized['rejection_reason'])

    def test_empty_result_short_cache_ttl(self):
        self.assertLessEqual(main._effective_cache_ttl({'diagnostics':{'accepted':0}}),120)
        self.assertEqual(main._effective_cache_ttl({'diagnostics':{'accepted':1}}),main.CACHE_TTL)

    def test_failed_site_must_show_error_not_empty_market(self):
        car={'brand':'بهمن موتور','model':'فیدلیتی','year':1403,
             'trim':'پرایم','mileage':50000}
        with patch.object(main,'AVALAI_KEY',''), \
             patch.object(main,'OPENAI_KEY',''), \
             patch.object(main,'_direct_connector',return_value=None), \
             patch.object(main,'_builtin_connector',side_effect=RuntimeError('HTTP 403')):
            result=main.research_market(car)
        self.assertTrue(result['site_status'])
        self.assertTrue(any(s['status']=='connector_error' for s in result['site_status']))
        self.assertTrue(any('به معنای نبود آگهی نیست' in v for v in result['warnings']))

    def test_empty_connector_not_claimed_as_verified(self):
        car={'brand':'بهمن موتور','model':'فیدلیتی','year':1403,
             'trim':'پرایم','mileage':50000}
        with patch.object(main,'AVALAI_KEY',''), \
             patch.object(main,'OPENAI_KEY',''), \
             patch.object(main,'_direct_connector',return_value=None), \
             patch.object(main,'_builtin_connector',return_value=[]):
            result=main.research_market(car)
        self.assertFalse(any(s['status']=='evidence' for s in result['site_status']))
        self.assertFalse(any(s['status']=='connector' for s in result['site_status']))
        self.assertEqual(result['diagnostics']['accepted'],0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
