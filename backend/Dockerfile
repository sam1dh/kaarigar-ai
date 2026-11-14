# Build context must be the REPO ROOT (see docker-compose.yml) so that
# shared/languages.json and backend/ are both visible.
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY backend/pyproject.toml ./
RUN pip install --no-cache-dir .

COPY backend/app ./app
COPY backend/scripts ./scripts
COPY shared/languages.json ./shared/languages.json

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
