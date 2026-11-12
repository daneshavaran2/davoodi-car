# Both the React build and API are mandatory; no missing-dist fallback in release.
FROM node:22-alpine AS build-frontend
WORKDIR /src/frontend
COPY frontend/package.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build && test -s dist/index.html

FROM python:3.12-slim-bookworm AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app \
    FRONTEND_DIST=/app/frontend/dist PORT=8000
WORKDIR /app
RUN groupadd -r davoodi && useradd --no-log-init -r -g davoodi -m davoodi
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY database ./database
COPY scripts ./scripts
COPY data/vehicle_catalog.csv ./data/vehicle_catalog.csv
COPY --from=build-frontend /src/frontend/dist ./frontend/dist
RUN test -s /app/frontend/dist/index.html && python -m compileall -q /app/backend /app/scripts
USER davoodi
EXPOSE 8000
# Run this image twice on Liara: SERVICE_ROLE=web and SERVICE_ROLE=worker.
# Each role bootstraps idempotently, protected by PostgreSQL advisory lock.
CMD ["sh","-c","python -m scripts.bootstrap && if [ "${SERVICE_ROLE:-web}" = worker ]; then exec python -m backend.worker --loop; else exec uvicorn backend.api:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers; fi"]
