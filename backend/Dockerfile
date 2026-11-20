# Production image for the Kaarigar backend (used in Phase 5).
# Build from the REPO ROOT so shared/languages.json is inside the build context:
#   docker build -f backend/Dockerfile -t kaarigar-backend .
# The embedding model is downloaded at build time, so the container starts ready and never
# downloads ~130 MB on a cold start.
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_RETRIES=10 \
    PIP_TIMEOUT=120 \
    FASTEMBED_CACHE_PATH=/app/.cache/fastembed \
    LANGUAGES_FILE=/app/shared/languages.json \
    APP_ENV=production

WORKDIR /app

# curl only for the HEALTHCHECK; ffmpeg comes from the imageio-ffmpeg wheel (Phase 2)
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements*.txt ./
RUN for f in requirements*.txt; do pip install -r "$f"; done

# Bake the embedding model (same name as EMBED_MODEL in .env)
ARG EMBED_MODEL=BAAI/bge-small-en-v1.5
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('${EMBED_MODEL}', cache_dir='${FASTEMBED_CACHE_PATH}')" \
    && python -c "import imageio_ffmpeg; print('ffmpeg', imageio_ffmpeg.get_ffmpeg_exe())"

COPY shared/languages.json /app/shared/languages.json
COPY backend/app /app/app

RUN useradd --create-home --uid 10001 kaarigar && chown -R kaarigar /app
USER kaarigar

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

# ONE worker on purpose: rate limits, "a new question cancels the old one" and the job lock
# live in process memory. Scale with more replicas only after moving them to Postgres/Redis.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--timeout-keep-alive", "75"]
