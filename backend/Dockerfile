FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    INTERACTIVE_ANNOTATION_PROJECT_ROOT=/app \
    INTERACTIVE_ANNOTATION_DATA_ROOT=/data \
    INTERACTIVE_ANNOTATION_LINEAGE_ROOT=/data/lineages_current \
    INTERACTIVE_ANNOTATION_CORS_ORIGINS=http://127.0.0.1:5173,http://localhost:5173

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY backend/app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
