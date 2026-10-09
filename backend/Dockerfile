FROM python:3.12-slim AS base

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM base AS ingestion

COPY requirements-ingestion.txt .
RUN pip install --no-cache-dir -r requirements-ingestion.txt

COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app

CMD ["python", "-m", "app.ingestion.worker"]

FROM base AS api

COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"]
