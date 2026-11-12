"""Permitted-source feed adapters. No CAPTCHA evasion or unsupported scraping.

Each source is disabled until the operator has a lawful, approved feed URL.
Feeds must return JSON {"items": [...], "next_cursor": null} containing individual ads.
"""
from __future__ import annotations
import ipaddress
import json
import os
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen, build_opener, HTTPRedirectHandler

SOURCE_CODES=('divar','bama','sheypoor','hamrah','karnameh','khodro45')

class SourceUnavailable(RuntimeError):
    def __init__(self,code,message):
        super().__init__(message)
        self.code=code


def safe_endpoint(url):
    """Reject any operator typo pointing the external worker to private hosts.

    Re-check the DNS answer; DNS rebinding is mitigated by the HTTP client
    network policy and source URLs are only loaded from operator env, never users.
    """
    u=urlsplit(str(url or ''))
    if u.scheme!='https' or not u.hostname or u.username or u.password or u.port not in (None,443):
        raise SourceUnavailable('INVALID_ENDPOINT','Connector endpoint must be a public HTTPS host')
    if u.hostname in ('localhost','local','metadata.google.internal'):
        raise SourceUnavailable('INVALID_ENDPOINT','Private connector host forbidden')
    try:
        answers=socket.getaddrinfo(u.hostname,443,type=socket.SOCK_STREAM)
        if not answers or any(not ipaddress.ip_address(x[4][0]).is_global for x in answers):
            raise SourceUnavailable('INVALID_ENDPOINT','Connector DNS points at private address')
    except socket.gaierror as exc:
        raise SourceUnavailable('DNS_TLS','Unable to resolve connector endpoint') from exc
    return url


def get_endpoint(code):
    if code not in SOURCE_CODES:raise SourceUnavailable('UNSUPPORTED_SOURCE','Unknown site')
    url=os.environ.get('SOURCE_'+code.upper()+'_API_URL','').strip()
    if not url:
        raise SourceUnavailable('ACCESS_NOT_CONFIGURED',
                                'No approved source feed URL; native unauthenticated scraping is disabled')
    return safe_endpoint(url)


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        raise SourceUnavailable('UNEXPECTED_REDIRECT','Provider redirected to an unexpected URL')


def fetch_one_page(url,request,secret='',timeout=11):
    body=json.dumps(request,ensure_ascii=False).encode('utf-8')
    headers={'Content-Type':'application/json','Accept':'application/json',
             'User-Agent':'DavoodiCar/30 (approved feed client)'}
    if secret:headers['Authorization']='Bearer '+secret
    req=Request(url,headers=headers,data=body,method='POST')
    try:
        with build_opener(_RejectRedirects()).open(req,timeout=timeout) as response:
            mime=(response.headers.get('Content-Type') or '').lower()
            if 'application/json' not in mime:
                raise SourceUnavailable('PARSER_CHANGED','Provider returned non-JSON content')
            payload=response.read(3_000_001)
            if len(payload)>3_000_000:raise SourceUnavailable('RESPONSE_TOO_LARGE','Feed response exceeds limit')
            parsed=json.loads(payload)
    except HTTPError as e:
        code='HTTP_403' if e.code in (401,403) else 'HTTP_429' if e.code==429 else 'HTTP_5XX' if e.code>=500 else 'HTTP_ERROR'
        raise SourceUnavailable(code,'Provider returned HTTP '+str(e.code)) from e
    except (TimeoutError,URLError) as e:
        raise SourceUnavailable('TIMEOUT' if isinstance(e,TimeoutError) else 'DNS_TLS','Provider connection failed') from e
    except json.JSONDecodeError as e:
        raise SourceUnavailable('PARSER_CHANGED','Invalid JSON from source') from e
    if not isinstance(parsed,dict) or not isinstance(parsed.get('items'),list):
        raise SourceUnavailable('PARSER_CHANGED','Source must return a JSON object with items array')
    return parsed


def collect_source(code,request,*,max_pages=8):
    """Independent bounded collection, no browser requests on API endpoints."""
    url=get_endpoint(code)
    secret=os.environ.get('SOURCE_'+code.upper()+'_API_TOKEN','')
    results=[];cursor=None;cursors=set()
    for page in range(max_pages):
        try:
            data=fetch_one_page(url,{**request,'cursor':cursor,'page_size':100},secret)
        except SourceUnavailable as exc:
            # Only retry connection instability / provider 5xx with short backoff.
            if exc.code in ('TIMEOUT','DNS_TLS','HTTP_5XX'):
                time.sleep(min(2,0.4*(page+1)))
                data=fetch_one_page(url,{**request,'cursor':cursor,'page_size':100},secret)
            else:raise
        rows=data['items']
        if len(rows)>100:
            raise SourceUnavailable('PARSER_CHANGED','Source returned more than 100 rows per page')
        results.extend(rows)
        if len(results)>=800:break
        next_cursor=data.get('next_cursor')
        if not next_cursor:break
        if not isinstance(next_cursor,str) or len(next_cursor)>200 or next_cursor in cursors:
            raise SourceUnavailable('PARSER_CHANGED','Duplicate or invalid pagination cursor')
        cursors.add(next_cursor);cursor=next_cursor
    return results
