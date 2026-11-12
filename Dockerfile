# Alternative Liara build: avoids pulling the large MCR Playwright runtime.
# Experimental fallback; production Dockerfile on main remains unchanged.
FROM node:22-alpine AS frontend
WORKDIR /web
COPY frontend/package.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Debian glibc is required by Chromium. Never use Alpine for browser runtime.
FROM python:3.12-slim-bookworm
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    FRONTEND_DIST=/app/frontend/dist \
    MARKET_FETCH_MODE=playwright \
    MAX_CONCURRENT_BROWSERS=1 \
    MAX_DETAIL_PAGES_PER_SOURCE=6 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    DB_PATH=/app/data/davoodi.db
COPY backend/requirements.txt /app/requirements.txt
# Install Chromium *headless shell only*, and the OS dependencies it needs.
# Playwright Python package is pinned to 1.57.0 in requirements.txt.
RUN python -m pip install --no-cache-dir -r /app/requirements.txt \
    && python -m playwright install --with-deps --only-shell chromium \
    && rm -rf /var/lib/apt/lists/* \
    && chmod -R a+rX /ms-playwright
COPY backend/ /app/
COPY --from=frontend /web/dist /app/frontend/dist
RUN test -s /app/frontend/dist/index.html \
    && test -d /app/frontend/dist/assets \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin pwuser \
    && mkdir -p /app/data \
    && chown -R pwuser:pwuser /app/data
USER pwuser
# Fail Docker build early if the real browser cannot launch without root.
RUN python -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(headless=True,args=['--disable-dev-shm-usage']); page=b.new_page(); page.set_content('<h1>OK</h1>'); assert page.locator('h1').inner_text()=='OK'; b.close(); p.stop(); print('Chromium headless smoke OK')"
EXPOSE 8000
CMD ["sh","-c","uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
