"""Offline tests for safe Liara PostgreSQL bootstrap - no real network."""
from unittest.mock import patch
from scripts import setup_liara_postgres as setup


def test_missing_url_does_not_connect(monkeypatch, capsys):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    assert setup.run(apply=True)==2
    assert 'DATABASE_URL_MISSING' in capsys.readouterr().out


def test_placeholder_url_is_rejected(monkeypatch):
    monkeypatch.setenv('DATABASE_URL','postgresql://DB_USER:CHANGE_THIS_PASSWORD@LIARA_PRIVATE_DB_HOST:5432/db')
    assert setup.run(apply=True)==2


def test_no_plaintext_credentials_in_failure(monkeypatch, capsys):
    monkeypatch.setenv('DATABASE_URL','postgresql://user:VERYSECRET@private-db.example:5432/davoodicar')
    with patch('backend.storage.connection',side_effect=RuntimeError('VERYSECRET contained in error')):
        assert setup.run(apply=True)==1
    captured=capsys.readouterr().out
    assert 'VERYSECRET' not in captured
    assert 'RuntimeError' in captured


class FakeCursor:
    def __init__(self):
        self.queries=[]
    def execute(self,sql,*args):
        self.queries.append(sql)
    def fetchone(self):
        sql=self.queries[-1]
        if 'current_database' in sql:return {'db':'davoodicar','ok':1}
        if 'to_regclass' in sql:return {'tbl':'public.table'}
        if 'FROM vehicle_models' in sql:return {'n':660}
        if 'FROM vehicle_aliases' in sql:return {'n':1200}
        if 'FROM data_sources' in sql:return {'n':6}
        raise AssertionError(sql)
    def __enter__(self):return self
    def __exit__(self,*_):return False


class FakeConnection:
    def cursor(self):return FakeCursor()
    def __enter__(self):return self
    def __exit__(self,*_):return False


def test_read_only_verification_skips_bootstrap(monkeypatch,capsys):
    monkeypatch.setenv('DATABASE_URL','postgresql://u:p@private-db.example:5432/davoodicar')
    with patch('backend.storage.connection',return_value=FakeConnection()),patch('scripts.bootstrap.main') as bootstrap:
        assert setup.run(apply=False)==0
        bootstrap.assert_not_called()
    assert 'READ_ONLY:' in capsys.readouterr().out


def test_apply_bootstraps_once_and_verifies_catalog(monkeypatch,capsys):
    monkeypatch.setenv('DATABASE_URL','postgresql://u:p@private-db.example:5432/davoodicar')
    with patch('backend.storage.connection',return_value=FakeConnection()),patch('scripts.bootstrap.main') as bootstrap:
        assert setup.run(apply=True)==0
        bootstrap.assert_called_once_with()
    assert 'vehicles=660' in capsys.readouterr().out
