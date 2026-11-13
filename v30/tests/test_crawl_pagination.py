"""Offline fixtures: public-page pagination, incremental checkpoints and details.

Never connects to real third-party websites.
"""
import pytest
from unittest.mock import patch
from backend import legacy_crawler as crawler
from backend import legacy_details

VEHICLES=[
    {'catalog_id':'a','brand':'بهمن','model':'فیدلیتی پرایم','display_name':'بهمن فیدلیتی پرایم'},
    {'catalog_id':'b','brand':'پژو','model':'207i','display_name':'پژو 207i'},
]
BASE='https://bama.ir/car/fidelity-prime'

def test_next_page_from_real_anchor_not_guessed():
    html='<a href="?page=2">بعدی</a><a href="https://attacker.example/page=9">بعدی</a>'
    assert crawler.next_page_link(html,BASE,'bama')==BASE+'?page=2'
    assert crawler.next_page_link('<div>1 2 3</div>',BASE,'bama') is None

def test_site_and_search_scope_are_retained():
    assert crawler.allowed_page(BASE+'?page=2','bama',parent=BASE)
    assert not crawler.allowed_page('http://bama.ir/car/fidelity-prime?page=2','bama',parent=BASE)
    assert not crawler.allowed_page('https://bama.ir/car/another?page=2','bama',parent=BASE)
    assert not crawler.allowed_page('https://private.local/page=2','bama',parent=BASE)
    divar='https://divar.ir/s/tehran/car?q=%D9%81%DB%8C%D8%AF%D9%84%DB%8C%D8%AA%DB%8C'
    assert not crawler.allowed_page('https://divar.ir/s/tehran/car?q=camry&page=2','divar',parent=divar)

def test_scan_follows_second_page_and_deduplicates(monkeypatch):
    seen=[]
    page1='''<article><a href="/car/detail-111">فیدلیتی پرایم 1402 اتومات</a>
      <p>کارکرد 45000 کیلومتر قیمت خودرو 1 میلیارد و 700 میلیون تومان</p>
      </article><a href="?page=2">بعدی</a>'''
    page2='''<article><a href="/car/detail-111">فیدلیتی پرایم 1402 اتومات</a></article>
       <article><a href="/car/detail-222">فیدلیتی پرایم 1402 اتومات</a>
       <p>کارکرد 35000 کیلومتر قیمت خودرو 1 میلیارد و 800 میلیون تومان</p>
       </article>'''
    def fetch(url,timeout=12):
        seen.append(url)
        assert url in (BASE,BASE+'?page=2')
        return page2 if url.endswith('page=2') else page1
    monkeypatch.setattr(crawler,'fetch_html',fetch)
    monkeypatch.setattr(crawler,'seed_url',lambda c,car:BASE)
    monkeypatch.setattr(crawler,'_detail_enrich',lambda card:card)
    class NoopSession:
        def __enter__(self):return self
        def __exit__(self,*args):pass
    monkeypatch.setattr(crawler,'source_session',lambda:NoopSession())
    from backend.legacy_bridge import _safe_listing
    monkeypatch.setattr(crawler,'_safe_listing',lambda c,car,card:{'url':card['url'],'title':card['title']})
    rows,resume,stats=crawler.scan_model('bama',VEHICLES[0],max_pages=2,max_ads=8)
    assert len(rows)==2
    assert resume is None
    assert stats['pages']==2
    assert seen==[BASE,BASE+'?page=2']

def test_checkpoint_resume_page_after_redeploy(monkeypatch):
    calls=[]
    def fake_scan(code,car,*,start_url=None,max_pages=3,max_ads=40):
        calls.append((car['catalog_id'],start_url))
        if start_url is None:return ([{'url':'https://bama.ir/car/detail-one'}],BASE+'?page=2',{'pages':1,'cards':1,'details':0})
        return ([{'url':'https://bama.ir/car/detail-two'}],None,{'pages':1,'cards':1,'details':0})
    monkeypatch.setattr(crawler,'scan_model',fake_scan)
    monkeypatch.setenv('PUBLIC_CRAWL_MODELS_PER_RUN','1')
    monkeypatch.setenv('PUBLIC_CRAWL_PAGES_PER_MODEL','1')
    first=crawler.crawl_catalog('bama',[VEHICLES[0]],{})
    assert first['checkpoint']['next_url']==BASE+'?page=2'
    second=crawler.crawl_catalog('bama',[VEHICLES[0]],first['checkpoint'])
    assert second['checkpoint']['next_url'] is None
    assert calls==[('a',None),('a',BASE+'?page=2')]

def test_priority_search_does_not_consume_background_cursor(monkeypatch):
    calls=[]
    def mock_scan(code,car,*,start_url=None,max_pages=3,max_ads=40):
        calls.append(car['catalog_id'])
        return [],None,{'pages':1,'cards':0,'details':0}
    monkeypatch.setattr(crawler,'scan_model',mock_scan)
    monkeypatch.setenv('PUBLIC_CRAWL_MODELS_PER_RUN','1')
    result=crawler.crawl_catalog('bama',VEHICLES,{},priority_ids=['b'])
    assert result['stats']['priority_models']==1
    assert result['stats']['models']==1
    assert set(calls)=={'a','b'}

def test_public_features_do_not_include_contact_information():
    html='''<html><head><meta property="og:image" content="https://img.bama.ir/a.jpg"/></head>
    <main>رنگ بدنه: سفید شهر: تهران شماره تماس 09123456789
    <img src="https://img.bama.ir/a.jpg"></main></html>'''
    fields=legacy_details.extract_public_features(html,BASE)
    assert fields['body_color']=='سفید'
    assert fields['city']=='تهران'
    assert fields['photo_urls']==['https://img.bama.ir/a.jpg']
    assert '09123456789' not in fields['public_description_excerpt']
