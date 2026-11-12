"""Regression checks: web binds even when DB unavailable; no secret leakage."""
import sys
from types import SimpleNamespace
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.api import app
from scripts import liara_entrypoint

client=TestClient(app,raise_server_exceptions=False)

def test_missing_db_returns_json_503(monkeypatch):
    monkeypatch.delenv('DATABASE_URL',raising=False)
    r=client.get('/api/v1/health')
    assert r.status_code==503 and r.json()['error_code']=='DATABASE_URL_MISSING'
    assert r.headers['content-type'].startswith('application/json')

def test_postgres_down_does_not_leak_secret(monkeypatch):
    monkeypatch.setenv('DATABASE_URL','postgresql://fake:secret@fake/test')
    with patch('backend.storage.connection',side_effect=RuntimeError('secret-should-not-leak')):
        r=client.get('/api/health')
    assert r.status_code==503 and r.json()['error_code']=='DATABASE_UNAVAILABLE'
    assert 'secret-should-not-leak' not in r.text

def test_web_binds_before_database_ready(monkeypatch):
    monkeypatch.setenv('SERVICE_ROLE','web')
    monkeypatch.delenv('DATABASE_URL',raising=False)
    monkeypatch.setenv('PORT','8000')
    calls=[]
    class NoStartThread:
        def __init__(self,*args,**kwargs):pass
        def start(self):calls.append('thread')
    monkeypatch.setattr(liara_entrypoint.threading,'Thread',NoStartThread)
    monkeypatch.setitem(sys.modules,'uvicorn',SimpleNamespace(run=lambda *a,**kw:calls.append(('listener',kw))))
    assert liara_entrypoint.main()==0
    assert calls[0]=='thread' and calls[1][0]=='listener'

def test_worker_fails_closed_without_db(monkeypatch):
    monkeypatch.setenv('SERVICE_ROLE','worker')
    monkeypatch.setenv('PORT','8000')
    monkeypatch.setenv('DB_WAIT_ATTEMPTS','1')
    monkeypatch.delenv('DATABASE_URL',raising=False)
    assert liara_entrypoint.main()==1

def test_live_endpoint_works_without_database(monkeypatch):
    monkeypatch.delenv('DATABASE_URL',raising=False)
    r=client.get('/api/live')
    assert r.status_code==200 and r.json()['status']=='alive'
