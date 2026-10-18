FROM python:3.11-slim

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./

# Config (JWT secret, DATABASE_URL, AI_ENGINE_URL) is injected at runtime, not baked in.
RUN useradd --create-home --uid 1000 appuser && mkdir -p /shared/uploads && chown appuser /shared/uploads
USER appuser
ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
