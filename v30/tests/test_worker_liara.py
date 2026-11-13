from scripts.worker_liara import STATE, response_document


def test_worker_reports_liveness_without_claiming_verified_prices():
    status, payload = response_document('/api/live')
    assert status == 200
    assert payload['service'] == 'davoodicar-worker'
    assert payload['source_access_verified'] is False


def test_worker_does_not_claim_db_readiness_until_bootstrap():
    old = STATE['bootstrapped']
    try:
        STATE['bootstrapped'] = False
        status, payload = response_document('/api/worker/health')
        assert status == 503
        assert payload['error_code'] == 'DATABASE_NOT_READY'
    finally:
        STATE['bootstrapped'] = old


def test_nonexistent_health_route_is_not_available():
    assert response_document('/api/not-real')[0] == 404

