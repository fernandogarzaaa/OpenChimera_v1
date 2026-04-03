FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OPENCHIMERA_ROOT=/app \
    OPENCHIMERA_PORT=7870

WORKDIR /app

RUN useradd --create-home --shell /bin/bash openchimera

COPY requirements-prod.txt requirements-prod.lock requirements.txt requirements.in pyproject.toml MANIFEST.in README.md LICENSE /app/
COPY core /app/core
COPY sandbox /app/sandbox
COPY scripts /app/scripts
COPY config /app/config
COPY assets /app/assets
COPY run.py /app/run.py

RUN python -m pip install --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements-prod.txt \
    && python -m pip install --no-cache-dir .

RUN mkdir -p /app/data /app/logs /app/models /app/memory \
    && chown -R openchimera:openchimera /app

USER openchimera

EXPOSE 7870

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -c "import json, sys, urllib.request; response = urllib.request.urlopen('http://127.0.0.1:7870/health', timeout=4); payload = json.loads(response.read().decode('utf-8')); sys.exit(0 if payload.get('status') == 'online' else 1)"

CMD ["python", "run.py", "serve"]