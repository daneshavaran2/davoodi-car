from unittest.mock import patch
import pytest
from backend.connectors import collect_source,SourceUnavailable,get_endpoint,safe_endpoint


def test_unconfigured_sources_not_marked_healthy():
    with patch.dict('os.environ',{},clear=True):
        with pytest.raises(SourceUnavailable) as ex:get_endpoint('bama')
        assert ex.value.code=='ACCESS_NOT_CONFIGURED'


def test_only_https_and_public():
    for url in ['http://site.example/feed','https://localhost/feed','https://user:pass@site.example/feed']:
        with pytest.raises(SourceUnavailable):safe_endpoint(url)


def test_source_pages_bound_and_no_guess():
    def fake(url,request,token):
        if request.get('cursor') is None:return {'items':[{'id':1}], 'next_cursor':'2'}
        return {'items':[{'id':2}], 'next_cursor':None}
    with patch('backend.connectors.get_endpoint',return_value='https://provider.example/feed'),\
         patch('backend.connectors.fetch_one_page',side_effect=fake):
        assert collect_source('bama',{'locale':'fa-IR'})==[{'id':1},{'id':2}]


def test_invalid_cursor_does_not_loop():
    def bad(url,request,token):return {'items':[],'next_cursor':'same'}
    with patch('backend.connectors.get_endpoint',return_value='https://provider.example/feed'),\
         patch('backend.connectors.fetch_one_page',side_effect=bad):
        with pytest.raises(SourceUnavailable) as ex:collect_source('divar',{})
        assert ex.value.code=='PARSER_CHANGED'


def test_blocked_provider_no_bypass():
    def blocked(url,request,token):raise SourceUnavailable('HTTP_403','Access denied')
    with patch('backend.connectors.get_endpoint',return_value='https://provider.example/feed'),\
         patch('backend.connectors.fetch_one_page',side_effect=blocked) as fetch:
        with pytest.raises(SourceUnavailable) as ex:collect_source('divar',{})
        assert ex.value.code=='HTTP_403'
        assert fetch.call_count==1
