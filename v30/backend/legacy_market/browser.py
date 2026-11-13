"""Public-page renderer for the Davoodi Car market connectors.

Uses real, unmodified Chromium and only ordinary public pages. Does not solve
CAPTCHAs, authenticate, impersonate a human, use proxies or bypass 403/429.
A browser is shared by consecutive page fetches within a single source run.
"""
from __future__ import annotations

from contextlib import contextmanager
import os
import re
import threading
from urllib.parse import urlsplit

_ALLOWED_HOSTS = frozenset({
    'bama.ir', 'hamrah-mechanic.com', 'khodro45.com',
    'divar.ir', 'sheypoor.com', 'karnameh.com',
})
# The regex covers Bama, Hamrah Mechanic, Divar and reference-price pages.
# Matching a link only signals hydration progress; normalizers still validate it.
AD_LINK_READY_JS = r"""() => [...document.querySelectorAll('a[href]')].some(a =>
    /\/car\/detail-|\/cars-for-sale\/[^/]+\/[^/]+\/\d+|\/v\/(?:[^/?#]+\/)?[^/?#]+|\/price\//i.test(a.getAttribute('href') || ''))"""
def _is_detail_page(url):
    path=urlsplit(str(url)).path.lower()
    return bool(re.search(r'/car/detail-|/v/(?:[^/]+/)?[^/]+/?$|/cars-for-sale/[^/]+/[^/]+/\d+/?$',path))


_local = threading.local()
# Each Chromium instance can use hundreds of MiB. Bound concurrent browser
# launches across parallel user searches inside this application process.
_browser_slots = threading.BoundedSemaphore(max(1, min(4, int(os.getenv('MAX_CONCURRENT_BROWSERS', '2')))))


def _valid_public_url(url: str) -> bool:
    try:
        parsed = urlsplit(str(url))
        host = (parsed.hostname or '').casefold().removeprefix('www.')
        return parsed.scheme == 'https' and (
            host in _ALLOWED_HOSTS or any(host.endswith('.' + d) for d in _ALLOWED_HOSTS)
        ) and not parsed.username and not parsed.password and parsed.port in (None, 443)
    except (ValueError, AttributeError):
        return False


def browser_mode() -> str:
    value = os.getenv('MARKET_FETCH_MODE', 'playwright').lower().strip()
    return value if value in ('playwright', 'http', 'auto') else 'playwright'


class BrowserSession:
    """A browser for a *single* worker thread, never shared across threads."""

    def __init__(self):
        self.manager = None
        self.browser = None
        self.context = None
        self.page = None
        self.has_slot = False

    def _start(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError('Playwright نصب نیست؛ وابستگی‌های سرور را نصب کنید') from exc
        if not _browser_slots.acquire(timeout=15):
            raise RuntimeError('ظرفیت مرورگرها پر است؛ منبع موقتاً قابل بررسی نیست')
        self.has_slot = True
        try:
            self.manager = sync_playwright().start()
            path = os.getenv('PLAYWRIGHT_CHROMIUM_PATH', '').strip()
            args = ['--disable-dev-shm-usage']
            if os.getenv('PLAYWRIGHT_NO_SANDBOX', '0') == '1':
                args.append('--no-sandbox')
            kwargs = {'headless': True, 'args': args}
            if path: kwargs['executable_path'] = path
            self.browser = self.manager.chromium.launch(**kwargs)
            self.context = self.browser.new_context(
                locale='fa-IR', timezone_id='Asia/Tehran',
                viewport={'width': 1280, 'height': 900},
                java_script_enabled=True, service_workers='block',
            )
            self.page = self.context.new_page()
            # Preserve JavaScript/XHR; omit heavy assets to reduce load time.
            def guard(route):
                request = route.request
                if request.is_navigation_request() and not _valid_public_url(request.url):
                    route.abort()
                elif request.resource_type in ('image','font','media'):
                    route.abort()
                else:
                    route.continue_()
            self.page.route('**/*', guard)
        except Exception as exc:
            self.close()
            raise RuntimeError('اجرای مرورگر Playwright ناموفق بود: ' + str(exc).splitlines()[0][:180]) from exc

    def fetch(self, url: str, timeout: float = 8, max_bytes: int = 3_000_000) -> str:
        if not _valid_public_url(url):
            raise RuntimeError('فقط صفحات عمومی HTTPS منابع تأییدشده قابل بازشدن هستند')
        if self.page is None: self._start()
        try:
            response = self.page.goto(url, wait_until='domcontentloaded', timeout=int(timeout * 1000))
            if response and response.status in (401, 403, 429):
                raise RuntimeError('سایت دسترسی عمومی را مسدود یا محدود کرده است (HTTP ' + str(response.status) + ')')
            if response and response.status >= 400:
                raise RuntimeError('صفحه منبع خطای HTTP ' + str(response.status) + ' دارد')
            if not _valid_public_url(self.page.url):
                raise RuntimeError('صفحه به دامنه خارج از منابع مجاز هدایت شد')
            # Do not wait for listing links on detail pages: they normally
            # have none, and the extra delay can exhaust the 105s API deadline.
            is_detail=_is_detail_page(url)
            try:
                if is_detail:
                    self.page.wait_for_function(
                        """() => !!document.querySelector('[itemprop="price"],[class*="price"],[class*="Price"],[data-testid*="price"]') ||
                          /(?:قیمت|تومان|کارکرد)/.test(document.body?.innerText||'')""",
                        timeout=min(1500,max(500,int(timeout*190))))
                else:
                    self.page.wait_for_function(
                        AD_LINK_READY_JS, timeout=min(2800,max(800,int(timeout*320))))
            except Exception:
                self.page.wait_for_timeout(250)
            title = (self.page.title() or '').lower()
            visible = (self.page.locator('body').inner_text(timeout=2000) or '')[:2500].lower()
            if any(k in title or k in visible for k in ('captcha', 'کپچا', 'تأیید کنید ربات نیستید', 'verify you are human')):
                raise RuntimeError('سایت تأیید انسانی یا کپچا درخواست کرده است؛ دور زده نمی‌شود')
            # Scroll ordinary public listing pages to load lazy-rendered
            # cards. This is normal page interaction, never a CAPTCHA solver
            # or a second transport after 403/429.
            if not is_detail:
                try: steps=max(0,min(12,int(os.getenv('PUBLIC_CRAWL_SCROLL_STEPS','5'))))
                except ValueError: steps=5
                for _ in range(steps):
                    self.page.mouse.wheel(0,900)
                    self.page.wait_for_timeout(300)
                    body=(self.page.locator('body').inner_text(timeout=1500) or '')[:1200].lower()
                    if any(x in body for x in ('captcha','کپچا','تأیید کنید ربات نیستید','verify you are human')):
                        raise RuntimeError('CAPTCHA_OR_CHALLENGE: public-page access requires human verification')
            markup = self.page.content()
            if len(markup.encode('utf-8')) > max_bytes:
                raise RuntimeError('صفحه رندرشده بزرگ‌تر از سقف امن است')
            return markup
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError('مرورگر نتوانست صفحه عمومی را دریافت کند: ' + str(exc).splitlines()[0][:150]) from exc

    def close(self):
        for name in ('page', 'context', 'browser'):
            resource = getattr(self, name, None)
            setattr(self, name, None)
            if resource:
                try: resource.close()
                except Exception: pass
        manager, self.manager = self.manager, None
        if manager:
            try: manager.stop()
            except Exception: pass
        if self.has_slot:
            self.has_slot = False
            _browser_slots.release()


@contextmanager
def source_session():
    previous = getattr(_local, 'session', None)
    session = BrowserSession()
    _local.session = session
    try: yield
    finally:
        session.close()
        _local.session = previous


def rendered_html(url, timeout=8, max_bytes=3_000_000):
    session = getattr(_local, 'session', None)
    if session is not None:
        return session.fetch(url, timeout, max_bytes)
    with source_session():
        return _local.session.fetch(url, timeout, max_bytes)
