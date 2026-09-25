FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --upgrade pip==26.1.2 \
    && pip install --no-cache-dir -r requirements.txt
RUN groupadd --system offerpilot && useradd --system --gid offerpilot --home-dir /app offerpilot
COPY --chown=offerpilot:offerpilot app ./app
COPY --chown=offerpilot:offerpilot alembic.ini ./
COPY --chown=offerpilot:offerpilot migrations ./migrations
COPY --chown=offerpilot:offerpilot alembic_agent.ini ./
COPY --chown=offerpilot:offerpilot alembic_agent ./alembic_agent
USER offerpilot
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
