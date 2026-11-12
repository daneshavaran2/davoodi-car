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
COPY backend/vehicle_nlp.py ./vehicle_nlp.py
COPY backend/safety_v24.py ./safety_v24.py
COPY backend/connectors ./connectors
COPY --from=frontend /web/dist /app/frontend/dist
RUN test -s /app/frontend/dist/index.html && test -d /app/frontend/dist/assets \
    && mkdir -p /app/data && chown -R pwuser:pwuser /app/data \
    && python -c "from playwright.sync_api import sync_playwright; print('Playwright import OK')"
# Non-root account is recommended for public-page scraping. No CAPTCHA bypass.
USER pwuser
EXPOSE 8000
CMD ["sh","-c","uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
