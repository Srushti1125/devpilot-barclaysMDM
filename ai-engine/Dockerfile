FROM python:3.11-slim

# System deps needed by `unstructured` for document parsing (pdf/docx/etc).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    poppler-utils \
    tesseract-ocr \
    libreoffice \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Secrets (GOOGLE_API_KEY, DATABASE_URL, MISTRAL_API_KEY) are injected at
# runtime via AWS Secrets Manager -> ECS task definition env vars, NOT
# baked into the image and NOT copied in from a local .env file.
ENV PYTHONUNBUFFERED=1
EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
