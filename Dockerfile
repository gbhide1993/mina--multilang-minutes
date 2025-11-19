# Use slim Python base
FROM python:3.11-slim as base

ENV PYTHONUNBUFFERED=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=100

# Install system deps needed for audio handling, Postgres builds, ffmpeg, and Redis client
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      build-essential \
      gcc \
      libpq-dev \
      ffmpeg \
      ca-certificates \
      git \
      && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency file first for Docker layer caching
COPY requirements.txt /app/requirements.txt

# Install Python deps
RUN python -m pip install --upgrade pip setuptools wheel && \
    pip install -r /app/requirements.txt

# Copy application code
COPY . /app

# Ensure a non-root user (optional but recommended)
RUN useradd --create-home appuser || true
RUN chown -R appuser:appuser /app
USER appuser

# Default command runs the web app. Override at deploy time for worker.
# The Flask app entrypoint is `app.py` with `app` variable (app:app). See app.py. 
ENV PORT=8080
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8080", "--workers", "2", "--threads", "4", "--timeout", "120"]
