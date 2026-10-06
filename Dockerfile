# The whole app (React front end + API + agent) on SQLite. Build from the repo root:
#   docker build -t warehouse-ops .
#   docker run --rm -p 8000:8000 --env-file .env warehouse-ops    # http://localhost:8000

# --- Stage 1: build the React app ---
FROM node:24-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

# --- Stage 2: Python API that also serves the built front end ---
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"

# Dependencies first so this layer is cached until uv.lock changes.
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY backend/src ./src
RUN uv sync --locked --no-dev

# Seed at build time. The data is deterministic, and WAREHOUSE_AS_OF pins the tools'
# "now" to the same moment, so every container starts from the same fresh warehouse.
ENV WAREHOUSE_AS_OF=2026-06-01T13:00
RUN seed-db --as-of "$WAREHOUSE_AS_OF"

COPY --from=frontend /frontend/dist ./static
ENV WAREHOUSE_STATIC_DIR=/app/static WAREHOUSE_API_HOST=0.0.0.0
EXPOSE 8000
CMD ["warehouse-api"]
