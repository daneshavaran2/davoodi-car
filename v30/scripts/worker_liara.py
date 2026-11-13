"""DavoodiCar dedicated hourly worker for Liara, with honest liveness/readiness.

No marketplace credentials or PostgreSQL passwords are stored in this file.
An independent worker in one Liara app uses the SAME DATABASE_URL as the web app.
"""
import json
import os
import sys
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATE = {'phase': 'starting', 'bootstrapped': False, 'started_at': time.time()}


def response_document(path):
    if path in ('/', '/api/live', '/health'):
        return 200, {'status': 'alive', 'service': 'davoodicar-worker',
                     'version': '30.2.0', 'phase': STATE['phase'],
                     'database_bootstrapped': STATE['bootstrapped'],
                     'source_access_verified': False}
    if path == '/api/worker/health':
        if not STATE['bootstrapped']:
            return 503, {'status': 'unavailable', 'service': 'davoodicar-worker',
                         'phase': STATE['phase'], 'error_code': 'DATABASE_NOT_READY'}
        try:
            from backend.storage import connection
            with connection() as db:
                with db.cursor() as cur:
                    cur.execute('SELECT COUNT(*) AS n FROM data_sources WHERE enabled')
                    enabled = cur.fetchone()['n']
                    cur.execute("SELECT scheduled_for,status,finished_at,source_ok,source_failed FROM scheduler_runs ORDER BY scheduled_for DESC LIMIT 1")
                    run = cur.fetchone()
            last = None if not run else {
                'scheduled_for': run['scheduled_for'].isoformat() if run['scheduled_for'] else None,
                'status': run['status'],
                'finished_at': run['finished_at'].isoformat() if run['finished_at'] else None,
                'source_ok': run['source_ok'], 'source_failed': run['source_failed'],
            }
            return 200, {'status': 'running', 'service': 'davoodicar-worker',
                         'database': 'ok', 'enabled_source_count': enabled,
                         'last_scheduler_run': last,
                         'note': ('No feed sources are enabled; no new market prices can be collected.'
                                  if not enabled else 'Enabled sources are not proof of successful collection.')}
        except Exception:
            return 503, {'status': 'unavailable', 'service': 'davoodicar-worker',
                         'error_code': 'DATABASE_UNAVAILABLE'}
    return 404, {'status': 'not_found'}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        status, document = response_document(self.path.split('?', 1)[0])
        payload = json.dumps(document, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        # Avoid logging raw URLs, query strings or authorization information.
        pass


def start_health_server():
    port = int(os.getenv('PORT', '8000'))
    if not 1 <= port <= 65535:
        raise ValueError('Invalid PORT configuration')
    server = ThreadingHTTPServer(('0.0.0.0', port), Handler)
    threading.Thread(target=server.serve_forever, name='worker-health', daemon=True).start()
    print('WORKER_HEALTH_HTTP_READY port=' + str(port), flush=True)
    return server


def main():
    server = start_health_server()
    try:
        delay = max(2, min(60, int(os.getenv('DB_WAIT_INTERVAL', '3'))))
        attempt = 0
        while True:
            try:
                if not os.getenv('DATABASE_URL', '').strip():
                    raise RuntimeError('DATABASE_URL_MISSING')
                from scripts.bootstrap import main as bootstrap
                bootstrap()
                STATE.update(phase='running', bootstrapped=True)
                print('WORKER_DB_BOOTSTRAP_OK', flush=True)
                break
            except Exception as exc:
                attempt += 1
                STATE.update(phase='waiting_for_database', bootstrapped=False)
                # Never print the exception string: DB errors may contain the DSN.
                category = 'DATABASE_URL_MISSING' if not os.getenv('DATABASE_URL', '').strip() else type(exc).__name__
                print('WORKER_DB_RETRY attempt=' + str(attempt) + ' category=' + category, flush=True)
                time.sleep(min(60, delay * min(attempt, 12)))
        sys.argv = ['davoodi-worker', '--loop']
        print('WORKER_LOOP_STARTED; timezone=' + os.getenv('SCHEDULER_TZ', 'Asia/Tehran'), flush=True)
        from backend.worker import main as worker_main
        worker_main()
    finally:
        server.shutdown()


if __name__ == '__main__':
    main()

