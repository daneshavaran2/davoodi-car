#!/usr/bin/env python3
"""Deploy DavoodiCar Web and Worker using the documented Liara REST API.

No credentials are stored in this repository. Set LIARA_API_TOKEN in a secret
store; this script never prints the token or any database environment variable.

Reference: https://skmtc.dev/liara-cloud/apis/paas/docs/v2/projects/:project_id/sources/post
           https://skmtc.dev/liara-cloud/apis/paas/docs/v2/projects/:project_id/releases/post
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import zipfile
from urllib.parse import urlencode
from urllib.error import HTTPError,URLError
from urllib.request import Request,urlopen
import secrets

BASE='https://api.liara.ir'
SOURCE_DIR=Path(__file__).resolve().parents[1]
APP_DEFAULT='davoodicar-worker'
APP_BY_ROLE={'worker':'davoodicar-worker','web':'davoodicar'}
REQUIRED=('backend/legacy_crawler.py','backend/legacy_details.py','backend/quality.py',
          'backend/worker.py','database/004_public_crawl_checkpoints.sql',
          'database/005_quality_audits.sql','Dockerfile','safety_v24.py')

def make_archive(base=SOURCE_DIR,role='worker'):
    """Build a clean role-specific ZIP without credentials, caches or .env."""
    if role not in APP_BY_ROLE:raise ValueError('Unknown deployment role')
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        z.write(base/('Dockerfile.worker' if role=='worker' else 'Dockerfile'),'Dockerfile')
        root_files=['requirements.txt','safety_v24.py']
        if role=='worker':root_files.append('requirements.worker.txt')
        for relative in root_files:z.write(base/relative,relative)
        folders=['backend','scripts','database','data']
        if role=='web':folders.append('frontend')
        for folder in folders:
            for path in sorted((base/folder).rglob('*')):
                if not path.is_file():continue
                if any(x in ('__pycache__','.pytest_cache','.git','node_modules','dist') for x in path.parts):
                    continue
                if path.name in ('.env','.env.local','.env.production'):continue
                if path.suffix in ('.pyc','.pyo','.env','.log','.xlsx'):continue
                rel=path.relative_to(base).as_posix()
                if rel=='data/vehicle_catalog.json':continue
                z.write(path,rel)
    archive=out.getvalue()
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        names=set(z.namelist())
    required=set(REQUIRED)
    if role=='worker':required.update(('requirements.worker.txt','scripts/worker_liara.py'))
    else:required.update(('frontend/package.json','frontend/index.html','frontend/src/main.jsx'))
    if required-names:raise RuntimeError('Incomplete '+role+' ZIP: '+','.join(sorted(required-names)))
    if role=='worker' and any(x.startswith('frontend/') for x in names):
        raise RuntimeError('Frontend unexpectedly bundled into worker')
    return archive

def call(method,url,token,*,payload=None,form=None,team_id=None):
    if not url.startswith(BASE+'/'):raise ValueError('Unknown API hostname')
    if team_id:
        if len(team_id)!=24 or any(x not in '0123456789abcdefABCDEF' for x in team_id):
            raise ValueError('Invalid LIARA_TEAM_ID')
        url+='?'+urlencode({'teamID':team_id})
    headers={'Authorization':'Bearer '+token,'Accept':'application/json'}
    if form is not None:
        boundary='DavoodiCar-'+secrets.token_hex(16)
        body=(b'--'+boundary.encode()+b'\r\n'
              +b'Content-Disposition: form-data; name="file"; filename="davoodi-worker.zip"\r\n'
              +b'Content-Type: application/zip\r\n\r\n'+form
              +b'\r\n--'+boundary.encode()+b'--\r\n')
        headers['Content-Type']='multipart/form-data; boundary='+boundary
    elif payload is not None:
        body=json.dumps(payload,separators=(',',':')).encode()
        headers['Content-Type']='application/json'
    else:body=None
    if body is not None:headers['Content-Length']=str(len(body))
    req=Request(url,headers=headers,method=method,data=body)
    try:
        with urlopen(req,timeout=75) as response:
            data=response.read(100_000)
            return json.loads(data) if data else {}
    except HTTPError as e:
        # Do not echo request headers or body (contains bearer credential).
        raise RuntimeError(f'Liara {method} request rejected: HTTP {e.code}') from None
    except URLError as e:
        raise RuntimeError(f'Liara {method} request failed: network unavailable') from None

def deploy(archive,token,app=APP_DEFAULT,team_id=None,role='worker'):
    if not app or not app.replace('-','').isalnum():
        raise ValueError('Invalid app name')
    uploaded=call('POST',f'{BASE}/v2/projects/{app}/sources',token,form=archive,team_id=team_id)
    source_id=uploaded.get('sourceID')
    if not source_id:raise RuntimeError('Liara did not return sourceID')
    # IMPORTANT: omit envs, so existing DATABASE_URL and other secrets remain unchanged.
    release_payload={'type':'docker','port':8000,'sourceID':source_id,
                     'message':'DavoodiCar v30.8 '+role+' verified quality release'}
    result=call('POST',f'{BASE}/v2/projects/{app}/releases',token,
                payload=release_payload,team_id=team_id)
    release_id=result.get('releaseID')
    if not release_id:raise RuntimeError('Liara source was uploaded but no releaseID returned')
    return release_id

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument('--dry-run',action='store_true',
                   help='Validate source ZIP without network access or credentials')
    p.add_argument('--app',default=None)
    p.add_argument('--role',choices=('worker','web'),default='worker')
    args=p.parse_args(argv)
    archive=make_archive(role=args.role)
    sha=hashlib.sha256(archive).hexdigest()
    print(f'{args.role} ZIP ready: {len(archive)} bytes; sha256={sha[:16]}…')
    if args.dry_run:
        print('DRY_RUN_OK: no network call and no production deployment')
        return 0
    token=os.environ.get('LIARA_API_TOKEN','').strip()
    if not token:
        print('DEPLOY_SKIPPED: configure LIARA_API_TOKEN in the GitHub Actions secret store',
              file=sys.stderr)
        return 2
    release=deploy(archive,token,app=args.app or APP_BY_ROLE[args.role],role=args.role,
                   team_id=os.environ.get('LIARA_TEAM_ID','').strip() or None)
    print('RELEASE_CREATED: '+release)
    print('DEPLOYMENT_NOT_YET_VERIFIED: check Liara release state and /api/live')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
