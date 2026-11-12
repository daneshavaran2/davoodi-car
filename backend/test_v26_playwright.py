"""v26 public-page browser extractor regression: no external websites required."""
import os
import unittest
from unittest.mock import patch

from connectors.browser import _valid_public_url, browser_mode, AD_LINK_READY_JS
from connectors.extract import listing_cards_from_html, detail_fields
from connectors.common import explicit_price, mileage_value, fetch_html
from connectors import bama, hamrah, divar

PAGE = '''<main id="list">
<article data-testid="car-card"><a href="/car/detail-111"><h3>فیدلیتی پرایم ۱۴۰۳</h3></a>
  <div class="ad-price">قیمت خودرو ۲ میلیارد و ۴۰۰ میلیون تومان</div>
  <span>کارکرد: ۵۰ هزار کیلومتر</span><p>بدون رنگ</p></article>
<article data-testid="car-card"><a href="/car/detail-222"><h3>فیدلیتی پرستیژ ۱۴۰۲</h3></a>
  <div class="ad-price">قیمت خودرو ۳ میلیارد تومان</div>
  <span>کارکرد: ۶۰ هزار کیلومتر</span></article>
</main>'''


def is_bama_ad(url):
    return url.startswith('https://bama.ir/car/detail-')


class ExtractionTests(unittest.TestCase):
    def test_card_price_sibling_not_just_anchor(self):
        rows=listing_cards_from_html(PAGE,'https://bama.ir/car',is_bama_ad)
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['price'],2_400_000_000)
        self.assertEqual(rows[0]['mileage'],50_000)
        self.assertEqual(rows[1]['price'],3_000_000_000)
        self.assertEqual(rows[1]['mileage'],60_000)

    def test_dont_merge_prices_across_cards(self):
        rows=listing_cards_from_html(PAGE,'https://bama.ir/car',is_bama_ad)
        self.assertNotEqual(rows[0]['price'],rows[1]['price'])

    def test_fee_is_not_asking_price(self):
        raw='''<article><a href="/car/detail-333">فیدلیتی پرایم ۱۴۰۳</a>
        <span>کارمزد ۳۰۰ میلیون تومان</span><span>قیمت خودرو ۲ میلیارد تومان</span></article>'''
        row=listing_cards_from_html(raw,'https://bama.ir/car',is_bama_ad)[0]
        self.assertEqual(row['price'],2_000_000_000)

    def test_only_fee_abstains(self):
        raw='<article><a href="/car/detail-334">فیدلیتی پرایم</a><span>کارمزد ۳۰۰ میلیون تومان</span></article>'
        row=listing_cards_from_html(raw,'https://bama.ir/car',is_bama_ad)[0]
        self.assertIsNone(row['price'])
        self.assertIsNone(explicit_price('کارمزد ۳۰۰ میلیون تومان'))

    def test_structured_rial_currency_and_publication_date(self):
        raw='''<script type="application/ld+json">{"@type":"Car",
        "datePublished":"2026-11-10T10:00:00+03:30",
        "mileageFromOdometer":{"value":50000},
        "offers":{"@type":"Offer","price":24000000000,"priceCurrency":"IRR"}}
        </script><main><h1>فیدلیتی پرایم ۱۴۰۳</h1></main>'''
        d=detail_fields(raw)
        self.assertEqual(d['price'],2_400_000_000)
        self.assertEqual(d['mileage'],50000)
        self.assertEqual(d['published_at'],'2026-11-10T10:00:00+03:30')

    def test_unknown_currency_and_two_prices_abstain(self):
        raw='''<script type="application/ld+json">{"@type":"Car","offers":{"price":2500000000,"priceCurrency":"USD"}}</script>
        <main><h1>فیدلیتی</h1><p>قیمت خودرو ۲ میلیارد تومان و قیمت خودرو ۳ میلیارد تومان</p></main>'''
        self.assertIsNone(detail_fields(raw)['price'])

    def test_farsi_mileage_in_source_cards(self):
        self.assertEqual(mileage_value('مدل ۱۴۰۳ کارکرد ۵۰ هزار کیلومتر'),50000)

    def test_domain_scheme_and_credentials_validated(self):
        self.assertTrue(_valid_public_url('https://bama.ir/car/detail-123'))
        for url in ('http://bama.ir/car','https://bama.ir.evil.com/car',
                    'https://user:pw@bama.ir/car','http://127.0.0.1/','file:///etc/passwd'):
            self.assertFalse(_valid_public_url(url),url)

    def test_http_mode_bypasses_browser(self):
        with patch.dict(os.environ,{'MARKET_FETCH_MODE':'http'}):
            from connectors import common
            with patch.object(common,'_fetch_http_html',return_value='OK') as get:
                self.assertEqual(common.fetch_html('https://bama.ir/car'),'OK')
            get.assert_called_once()

    def test_auto_mode_no_playwright_bypass_of_403(self):
        from connectors import common
        with patch.dict(os.environ,{'MARKET_FETCH_MODE':'auto'}):
            with patch.object(common,'_fetch_http_html',side_effect=RuntimeError('403 forbidden')):
                with patch('connectors.browser.rendered_html') as rendered:
                    with self.assertRaisesRegex(RuntimeError,'403'):
                        common.fetch_html('https://bama.ir/car')
                    rendered.assert_not_called()

    def test_auto_renders_javascript_shell(self):
        from connectors import common
        with patch.dict(os.environ,{'MARKET_FETCH_MODE':'auto'}):
            with patch.object(common,'_fetch_http_html',return_value='<html><div id="__next"></div></html>'):
                with patch('connectors.browser.rendered_html',return_value=PAGE) as rendered:
                    self.assertIn('قیمت خودرو',common.fetch_html('https://bama.ir/car'))
                    rendered.assert_called_once()

    def test_bama_multi_page_with_card_and_detail(self):
        pages={
            'https://bama.ir/car':'<a href="/car/fidelity">خرید و فروش فیدلیتی</a>',
            'https://bama.ir/car/fidelity':'<a href="/car/fidelity/prime">فیدلیتی پرایم</a>',
            'https://bama.ir/car/fidelity/prime':PAGE,
            'https://bama.ir/car/detail-111':'<main><h1>فیدلیتی پرایم ۱۴۰۳</h1><p>کارکرد ۵۰ هزار کیلومتر</p></main>',
        }
        with patch.object(bama,'fetch_html',side_effect=lambda url,**kw:pages[url]):
            rows=bama.search({'brand':'بهمن موتور','model':'فیدلیتی'},limit=1)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['price'],2_400_000_000)
        self.assertEqual(rows[0]['mileage'],50_000)

    def test_hamrah_card_price_sibling(self):
        base=hamrah.BASE
        raw='''<article><a href="/cars-for-sale/bahman/fidelity/555">فیدلیتی پرایم ۱۴۰۳</a>
         <span>قیمت خودرو ۲ میلیارد تومان</span><span>کارکرد: ۵۰ هزار کیلومتر</span></article>'''
        with patch.object(hamrah,'fetch_html',side_effect=lambda url,**kw:raw if url==base else '<main><h1>فیدلیتی پرایم ۱۴۰۳</h1></main>'):
            rows=hamrah.search({'brand':'بهمن موتور','model':'فیدلیتی'})
        self.assertEqual(rows[0]['price'],2_000_000_000)

    def test_divar_public_search_and_local_price(self):
        from connectors import divar
        raw='''<article><a href="/v/فروش-فیدلیتی/aa123">فیدلیتی پرایم مدل ۱۴۰۳</a>
          <p>قیمت خودرو ۲ میلیارد و ۵۰۰ میلیون تومان</p>
          <p>کارکرد ۵۰ هزار کیلومتر</p></article>'''
        with patch.object(divar,'fetch_html',side_effect=lambda url,**kw:raw if '/s/' in url else '<h1>فیدلیتی پرایم مدل ۱۴۰۳</h1>') as fetch:
            rows=divar.search({'brand':'بهمن موتور','model':'فیدلیتی','trim':'پرایم','year':1403,'city':'تهران'})
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['price'],2_500_000_000)
        self.assertIn('q=',fetch.call_args_list[0].args[0])

    def test_divar_off_domain_is_not_listing(self):
        from connectors.divar import _is_detail
        self.assertFalse(_is_detail('https://divar.ir.attacker.test/v/fidelity/123'))

    def test_blocked_site_not_reported_as_no_listings(self):
        os.environ.setdefault('ADMIN_PASSWORD','offline-v26-test-password')
        os.environ.setdefault('SESSION_SECRET','offline-v26-test-secret-longer-than-32-characters')
        os.environ.setdefault('DB_PATH','/tmp/davoodi-v26-test.sqlite3')
        import main
        vehicle={'brand':'بهمن موتور','model':'فیدلیتی','trim':'پرایم','year':1403,'mileage':50000}
        with patch.object(main,'AVALAI_KEY',''), patch.object(main,'_direct_connector',return_value=None), patch.object(main,'_builtin_connector',side_effect=RuntimeError('HTTP 403')):
            result=main.research_market(vehicle)
        self.assertTrue(any(x['status']=='connector_error' for x in result['site_status']))
        self.assertTrue(any('به معنای نبود آگهی نیست' in x for x in result['warnings']))

    def test_actual_chromium_hydration_in_memory(self):
        """Run real Chromium JS with set_content; external navigation is blocked in CI."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest('Playwright unavailable')
        with sync_playwright() as playwright:
            path=os.getenv('PLAYWRIGHT_CHROMIUM_PATH','')
            options={'headless':True,'args':['--no-sandbox']}
            if path:options['executable_path']=path
            try: browser=playwright.chromium.launch(**options)
            except Exception as exc:
                if os.getenv('BROWSER_TEST_REQUIRED')=='1':raise
                self.skipTest(str(exc).splitlines()[0])
            try:
                page=browser.new_page()
                page.set_content('<main id="root"></main><script>document.getElementById("root").innerHTML='+repr(PAGE).replace('\\n',' ')+';</script>')
                page.wait_for_selector('article[data-testid="car-card"]')
                rows=listing_cards_from_html(page.content(),'https://bama.ir/car',is_bama_ad)
                self.assertEqual(len(rows),2)
                self.assertEqual(rows[0]['price'],2_400_000_000)
                # Divar links use /v/ and can appear after delayed JS hydration.
                page.set_content('''<main id="root"></main><script>
                    setTimeout(() => {
                      document.getElementById('root').innerHTML =
                        '<article><a href="/v/fidelity/xyz123">فیدلیتی پرایم ۱۴۰۳</a><span>قیمت خودرو ۲ میلیارد تومان</span></article>';
                    }, 450);
                </script>''')
                page.wait_for_function(AD_LINK_READY_JS,timeout=2000)
                hydrated=listing_cards_from_html(page.content(),'https://divar.ir/s/tehran/car',divar._is_detail)
                self.assertEqual(len(hydrated),1)
                self.assertEqual(hydrated[0]['price'],2_000_000_000)
            finally: browser.close()


if __name__=='__main__':unittest.main(verbosity=2)
