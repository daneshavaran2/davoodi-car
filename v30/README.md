# DavoodiCar v30 — offline-first vehicle asking-price search

For full Persian setup/deployment instructions, see [README_FA.md](README_FA.md).

- React + FastAPI + PostgreSQL; 660 vehicles imported from the user-provided catalog.
- User-facing price search queries stored snapshots only; no external I/O to marketplaces.
- Separate hourly worker ingests only approved JSON feeds, retains source errors and previous prices.
- Five comparable verified listings minimum; source links, last update and sample count shown.
- No live feed URLs included. Six sources are **disabled by default**; real extraction and Liara deployment remain unverified.

```bash
cp .env.example .env
# Change POSTGRES_PASSWORD and ADMIN_TOKEN, then:
docker compose up --build -d
```

Production Liara: deploy the same Docker image to two applications with `SERVICE_ROLE=web` and `SERVICE_ROLE=worker`, both using one PostgreSQL DB. See Persian README.

Run local offline tests using `python -m pytest -q`.
