"""Liara entrypoint: always expose the HTTP port even when PostgreSQL is down.

The web service responds with JSON 503 while database bootstrap is pending.
The independent collection worker remains fail-closed.
Never log DATABASE_URL or authentication secrets.
"""
import os
import sys
import time
import threading


def _config():
    role = os.getenv('SERVICE_ROLE', 'web').strip().lower()
    if role not in ('web', 'worker'):
        raise ValueError('SERVICE_ROLE must be web or worker')
    port = os.getenv('PORT', '8000')
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError('PORT is not a valid TCP port')
    return role, int(port)


def _bootstrap_once():
    if not os.getenv('DATABASE_URL', '').strip():
        raise RuntimeError('DATABASE_URL_MISSING')
    from scripts.bootstrap import main as bootstrap
    bootstrap()


def _web_db_initializer():
    attempts = 0
    while True:
        try:
            _bootstrap_once()
            print('DB_BOOTSTRAP_OK: PostgreSQL schema and catalog available.', flush=True)
            return
        except Exception as exc:
            attempts += 1
            category = 'DATABASE_URL_MISSING' if not os.getenv('DATABASE_URL', '').strip() else type(exc).__name__
            print(f'DB_BOOTSTRAP_RETRY {attempts}: {category}; web HTTP stays online.', flush=True)
            time.sleep(min(60, 5 * min(attempts, 12)))


def main() -> int:
    try:
        role, port = _config()
    except ValueError as exc:
        print(f'CONFIG_ERROR: {exc}', flush=True)
        return 2

    if role == 'web':
        # Start Uvicorn immediately; a failed database connection must not
        # make the Liara reverse proxy report a gateway 502.
        threading.Thread(target=_web_db_initializer, daemon=True, name='postgres-bootstrap').start()
        print(f'WEB_LISTEN: 0.0.0.0:{port}; POSTGRES_BOOTSTRAP=background', flush=True)
        import uvicorn
        uvicorn.run('backend.api:app', host='0.0.0.0', port=port, proxy_headers=True)
        return 0

    attempts = max(1, min(30, int(os.getenv('DB_WAIT_ATTEMPTS', '12'))))
    interval = max(1, min(15, int(os.getenv('DB_WAIT_INTERVAL', '3'))))
    for index in range(attempts):
        try:
            _bootstrap_once()
            break
        except Exception as exc:
            print(f'WORKER_DB_NOT_READY ({type(exc).__name__}) attempt={index+1}/{attempts}', flush=True)
            if index + 1 == attempts:
                return 1
            time.sleep(interval)
    print('WORKER_STARTED: independent hourly collection', flush=True)
    os.execvp(sys.executable, [sys.executable, '-m', 'backend.worker', '--loop'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
