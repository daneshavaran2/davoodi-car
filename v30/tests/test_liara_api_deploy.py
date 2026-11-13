from datetime import datetime,timezone
from pathlib import Path
import io
import zipfile
import pytest

from backend.domain import normalize
from backend.worker import validate_with_public_extras
from scripts import deploy_liara_api as liara

def test_public_ad_extra_fields_survive_strict_validation():
    raw={'url':'https://bama.ir/car/detail-123','title':'فیدلیتی پرایم مدل ۱۴۰۳',
         'brand':'بهمن','model':'فیدلیتی پرایم','trim':'پرایم',
         'currency':'toman','model_year':1403,'condition':'used',
         'mileage_km':55000,'transmission':'automatic',
         'body_condition':'original','price_toman':2500000000,
         'raw_type':'listing','extra_fields':{
             'body_color':'سفید','city':'تهران',
             'photo_urls':['https://img.bama.ir/1.jpg']}}
    mapping={(normalize('بهمن'),normalize('فیدلیتی پرایم')):'car-one'}
    item,reason=validate_with_public_extras(raw,'bama',mapping,datetime.now(timezone.utc))
    assert reason is None
    assert item['price_toman']==2500000000
    assert item['extra_fields']['body_color']=='سفید'
    assert item['extra_fields']['photo_urls']==['https://img.bama.ir/1.jpg']

def test_invalid_listing_never_persists_extras():
    raw={'url':'https://example.test/anything','title':'فیدلیتی پرایم',
         'extra_fields':{'body_color':'قرمز'}}
    item,reason=validate_with_public_extras(raw,'bama',{},datetime.now(timezone.utc))
    assert item is None
    assert reason=='INVALID_URL'

def test_deploy_archive_has_worker_only_sources():
    bundle=liara.make_archive()
    assert len(bundle)>50_000
    with zipfile.ZipFile(io.BytesIO(bundle)) as z:
        names=set(z.namelist())
    assert all(x in names for x in liara.REQUIRED)
    assert not any(x.startswith('frontend/') for x in names)
    assert not any('.env' in x for x in names)

def test_deploy_api_keeps_database_envs_unmodified(monkeypatch):
    observed=[]
    def call(method,url,token,*,payload=None,form=None,team_id=None):
        observed.append((method,url,payload,form))
        if url.endswith('/sources'):return {'sourceID':'src-123'}
        if url.endswith('/releases'):return {'releaseID':'release-123'}
        raise AssertionError(url)
    monkeypatch.setattr(liara,'call',call)
    rid=liara.deploy(b'zip-content','secret-not-printed')
    assert rid=='release-123'
    assert observed[0][0]=='POST' and observed[0][3]==b'zip-content'
    assert observed[1][2]['type']=='docker'
    assert observed[1][2]['port']==8000
    assert 'envs' not in observed[1][2]
    assert observed[1][2]['sourceID']=='src-123'

def test_dry_run_requires_no_token(monkeypatch,capsys):
    monkeypatch.delenv('LIARA_API_TOKEN',raising=False)
    rc=liara.main(['--dry-run'])
    assert rc==0
    assert 'DRY_RUN_OK' in capsys.readouterr().out

def test_web_bundle_has_frontend_and_quality_migration_without_worker_image():
    bundle=liara.make_archive(role='web')
    with zipfile.ZipFile(io.BytesIO(bundle)) as z:
        names=set(z.namelist())
        dockerfile=z.read('Dockerfile').decode('utf-8')
    assert 'frontend/package.json' in names
    assert 'frontend/src/main.jsx' in names
    assert 'database/005_quality_audits.sql' in names
    assert 'backend/quality.py' in names
    assert 'build-frontend' in dockerfile
    assert 'requirements.worker.txt' not in names


def test_worker_bundle_includes_quality_and_browser_no_frontend():
    bundle=liara.make_archive(role='worker')
    with zipfile.ZipFile(io.BytesIO(bundle)) as z:
        names=set(z.namelist())
        dockerfile=z.read('Dockerfile').decode('utf-8')
    assert 'backend/quality.py' in names
    assert 'database/005_quality_audits.sql' in names
    assert 'requirements.worker.txt' in names
    assert 'playwright' in dockerfile.lower()
    assert not any(x.startswith('frontend/') for x in names)


def test_web_deploy_uses_web_project_and_preserves_environment(monkeypatch):
    calls=[]
    def fake_call(method,url,token,*,payload=None,form=None,team_id=None):
        calls.append((method,url,payload))
        return {'sourceID':'source-web'} if url.endswith('/sources') else {'releaseID':'release-web'}
    monkeypatch.setattr(liara,'call',fake_call)
    assert liara.deploy(b'zip','secret',app='davoodicar',role='web')=='release-web'
    assert calls[0][1].endswith('/projects/davoodicar/sources')
    assert calls[1][1].endswith('/projects/davoodicar/releases')
    assert calls[1][2]['type']=='docker' and 'envs' not in calls[1][2]
