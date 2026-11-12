"""Offline ASGI static frontend routing smoke test. Tests a fake build, NOT npm/Vite build."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

backend = Path(__file__).resolve().parent.parent / 'backend'
dockerfile = backend.parent / 'Dockerfile'
assert 'FRONTEND_DIST=/app/frontend/dist' in dockerfile.read_text()
with tempfile.TemporaryDirectory() as d:
    dist = Path(d) / 'dist'
    (dist / 'assets').mkdir(parents=True)
    (dist / 'index.html').write_text('<!doctype html><title>DAVOUDI-STATIC-V24</title>', encoding='utf-8')
    (dist / 'assets' / 'test.js').write_text('console.log("v24")', encoding='utf-8')
    env = dict(os.environ)
    env.update({
        'ADMIN_PASSWORD': 'offline-qa-only',
        'SESSION_SECRET': 'offline-only-secret-longer-than-thirty-two-characters',
        'FRONTEND_DIST': str(dist),
        'DB_PATH': str(Path(d)/'temp.sqlite3'),
        'AVALAI_API_KEY': '',
        'OPENAI_API_KEY': '',
    })
    code = """from fastapi.testclient import TestClient
import main
c = TestClient(main.app)
a = c.get('/')
assert a.status_code==200 and 'DAVOUDI-STATIC-V24' in a.text, (a.status_code,a.text)
b = c.get('/assets/test.js')
assert b.status_code==200 and 'console.log' in b.text, (b.status_code,b.text)
h=c.get('/api/health')
assert h.status_code==200 and '24.0.0-release-candidate' in h.text,(h.status_code,h.text)
print('Static ASGI/Health smoke: PASS')
"""
    completed = subprocess.run([sys.executable,'-c',code],cwd=backend,env=env,timeout=20,text=True,capture_output=True)
    if completed.returncode:
        print(completed.stdout,completed.stderr)
        sys.exit(completed.returncode)
    print(completed.stdout.strip())
