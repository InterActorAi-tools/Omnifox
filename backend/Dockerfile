ARG PYTHON_VERSION=3.10

FROM python:${PYTHON_VERSION}-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY . .

RUN useradd --create-home --shell /bin/bash --uid 1001 app \
    && mkdir -p /app/uploads /app/cache \
    && chown -R app:app /app
USER app

ARG APP_PORT=8000
ENV APP_PORT=${APP_PORT} \
    GUNICORN_WORKERS=2 \
    GUNICORN_TIMEOUT=120

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${APP_PORT}/health" || exit 1

CMD ["sh", "-c", "exec gunicorn main:app \
    -k uvicorn.workers.UvicornWorker \
    --workers ${GUNICORN_WORKERS} \
    --timeout ${GUNICORN_TIMEOUT} \
    --bind 0.0.0.0:${APP_PORT} \
    --access-logfile - \
    --error-logfile -"]
