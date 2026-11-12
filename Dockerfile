# React and static assets are built at image-build time, never at first request.
FROM node:22-alpine AS frontend
WORKDIR /web
COPY frontend/package.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# The official Playwright runtime contains Chromium, browser libraries and fonts.
# Match its browser version with backend/requirements.txt.
FROM mcr.microsoft.com/playwright/python:v1.57.0-noble
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000 \
    FRONTEND_DIST=/app/frontend/dist MARKET_FETCH_MODE=playwright \
    MAX_CONCURRENT_BROWSERS=2 DB_PATH=/app/data/davoodi.db
COPY backend/requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY backend/main.py ./main.py
COPY backend/market_intelligence.py ./market_intelligence.py
COPY backend/model_overview.py ./model_overview.py
COPY backend/vehicle_nlp.py ./vehicle_nlp.py
COPY backend/safety_v24.py ./safety_v24.py
COPY backend/connectors ./connectors
COPY backend/test_v26_playwright.py ./test_v26_playwright.py
COPY backend/test_v27_reliability.py ./test_v27_reliability.py
COPY backend/test_v28_name_only.py ./test_v28_name_only.py
COPY --from=frontend /web/dist /app/frontend/dist
RUN test -s /app/frontend/dist/index.html && test -d /app/frontend/dist/assets \
    && mkdir -p /app/data && chown -R pwuser:pwuser /app/data \
    && python -m compileall -q /app \
    && ADMIN_PASSWORD=build-only-v27-test-password SESSION_SECRET=build-only-v27-session-secret-must-be-32-characters DB_PATH=/tmp/davoodi-build-test.sqlite3 \
         BROWSER_TEST_REQUIRED=1 python test_v26_playwright.py \
    && ADMIN_PASSWORD=build-only-v27-test-password SESSION_SECRET=build-only-v27-session-secret-must-be-32-characters DB_PATH=/tmp/davoodi-build-test.sqlite3 \
         python test_v27_reliability.py \
    && ADMIN_PASSWORD=build-only-v28-test-password SESSION_SECRET=build-only-v28-session-secret-must-be-32-characters DB_PATH=/tmp/davoodi-build-test.sqlite3 \
         python test_v28_name_only.py
# Non-root account is recommended for public-page scraping. No CAPTCHA bypass.
USER pwuser
# Assert that Chromium launches with the same non-root account used in Liara.
RUN python -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(headless=True,args=['--disable-dev-shm-usage']); b.new_page().set_content('<p>OK</p>'); b.close(); p.stop(); print('Chromium runtime OK')"
EXPOSE 8000
CMD ["sh","-c","uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
