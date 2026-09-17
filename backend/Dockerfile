FROM ghcr.io/astral-sh/uv:0.8.15-python3.11-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY backend/pyproject.toml backend/uv.lock /app/backend/
RUN uv sync --project /app/backend --frozen --no-dev

COPY backend /app/backend

EXPOSE 8000

# Migrations run against the same DATABASE_URL used by the application.
CMD ["sh", "-c", "cd /app/backend && /app/backend/.venv/bin/alembic upgrade head && exec /app/backend/.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8000"]
