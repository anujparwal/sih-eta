FROM docker.io/library/python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY backend/requirements.txt backend/requirements-dev.txt ./
# The local scaffold includes test tools so `compose run --rm backend pytest` works.
RUN pip install --require-hashes -r requirements-dev.txt \
    && useradd --create-home --uid 10001 appuser \
    && chown appuser:appuser /app
COPY --chown=appuser:appuser backend/ .
COPY --chown=appuser:appuser data/ ./data/
COPY --chown=appuser:appuser simulator/ ./simulator/
COPY --chown=appuser:appuser scripts/ ./scripts/
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
