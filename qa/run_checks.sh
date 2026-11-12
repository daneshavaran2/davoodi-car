#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export ADMIN_PASSWORD="${ADMIN_PASSWORD:-offline-qa-password}"
export SESSION_SECRET="${SESSION_SECRET:-offline-only-qa-secret-longer-than-32-characters}"
export AVALAI_API_KEY='' OPENAI_API_KEY=''
export SEARCH_COOLDOWN=0 MAX_SEARCHES_PER_HOUR=1000
cd "$ROOT/backend"
python -m compileall -q .
python test_v21_market_fix.py
python test_v22_intelligence.py
python test_v23_quality.py
python test_v24_release.py
cd "$ROOT"
node qa/test_frontend.cjs
python qa/test_static_serving_v24.py
