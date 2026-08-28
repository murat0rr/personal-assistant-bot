FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml ./
RUN uv sync --no-dev --no-install-project

COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --no-dev

CMD ["uv", "run", "python", "-m", "src.adapters.telegram_bot"]
