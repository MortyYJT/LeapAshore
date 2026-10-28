# Production image for the FastAPI backend. On start it applies migrations and runs the idempotent
# seeds, so a fresh database comes up with the catalogue and roadmap already in place.
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY pyproject.toml ./
COPY app ./app
RUN pip install .
COPY . .
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && python seed_cli.py && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
