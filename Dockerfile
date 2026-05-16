# =============================================================================
# EduMaster Backend – Production Docker Image
# =============================================================================
# What lives INSIDE this container:
#   ✔ FastAPI / Uvicorn application
#   ✔ Tesseract OCR 5.x  (eng + urd tessdata)
#   ✔ OpenCV headless libraries
#   ✔ ChromaDB  (persistent, file-based – data volume at /app/chroma_db)
#   ✔ sentence-transformers + PyTorch CPU  (BAAI/bge-base-en-v1.5 pre-baked)
#   ✔ All Python dependencies from requirements.txt
#
# What lives OUTSIDE (supplied via environment variables only):
#   ✘ PostgreSQL  →  DATABASE_URL
#   ✘ Redis       →  REDIS_URL  /  CELERY_BROKER_URL  /  CELERY_RESULT_BACKEND
# =============================================================================

# ── Stage 1: wheel builder ────────────────────────────────────────────────────
FROM python:3.11-slim-bookworm AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        g++ \
        git \
        curl \
        libpq-dev \
        libffi-dev \
        libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .

RUN pip install --upgrade pip wheel setuptools && \
    pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt


# ── Stage 2: runtime image ────────────────────────────────────────────────────
FROM python:3.11-slim-bookworm AS runtime

# ── 1. System runtime libraries ──────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        # ---- Tesseract OCR ----
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-urd \
        # ---- OpenCV headless runtime ----
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender-dev \
        libgl1-mesa-glx \
        # ---- Pillow / ReportLab image libs ----
        libfreetype6 \
        libjpeg62-turbo \
        libpng16-16 \
        # ---- asyncpg (PostgreSQL client) ----
        libpq5 \
        # ---- Process supervisor ----
        tini \
        # ---- Misc ----
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ── 2. Non-root user ──────────────────────────────────────────────────────────
RUN groupadd --gid 1001 appgroup && \
    useradd  --uid 1001 --gid appgroup --shell /bin/bash --create-home appuser

# ── 3. Install Python wheels ──────────────────────────────────────────────────
COPY --from=builder /wheels /wheels
RUN pip install --upgrade pip && \
    pip install --no-cache-dir --no-index --find-links=/wheels /wheels/*.whl && \
    rm -rf /wheels

# ── 4. Pre-download embedding model into the image ────────────────────────────
# Baking the model (~440 MB) avoids a slow download on first container start.
# Override LOCAL_EMBEDDING_MODEL to use a different model.
ENV HF_HOME=/app/.cache/huggingface \
    TRANSFORMERS_OFFLINE=0
RUN python -c "\
from sentence_transformers import SentenceTransformer; \
print('Downloading BAAI/bge-base-en-v1.5 …'); \
SentenceTransformer('BAAI/bge-base-en-v1.5'); \
print('Model cached.')" \
    || echo "WARNING: model pre-download failed — will download at first runtime request"

# ── 5. Application source ─────────────────────────────────────────────────────
WORKDIR /app
COPY --chown=appuser:appgroup . .

# Persistent directories (mount named volumes over these in production)
RUN mkdir -p /app/uploads \
             /app/chroma_db \
             /app/static \
             /app/logs \
             /app/.cache/huggingface \
             /app/.cache/torch && \
    chown -R appuser:appgroup /app

# ── 6. Default environment ────────────────────────────────────────────────────
# All secrets / URLs MUST be supplied at runtime via env / --env-file.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    ENVIRONMENT=production \
    DEBUG=false \
    PORT=8010 \
    # Tesseract is on PATH inside the container — no Windows path needed
    TESSERACT_PATH=/usr/bin/tesseract \
    USE_GOOGLE_VISION=false \
    # ChromaDB — file-based, persisted via Docker volume
    CHROMA_DB_PATH=/app/chroma_db \
    # Uploads — persisted via Docker volume
    UPLOAD_PATH=/app/uploads \
    # Embedding model
    LOCAL_EMBEDDING_MODEL=BAAI/bge-base-en-v1.5 \
    HF_HOME=/app/.cache/huggingface \
    TORCH_HOME=/app/.cache/torch \
    TRANSFORMERS_OFFLINE=1

# ── 7. Port ───────────────────────────────────────────────────────────────────
EXPOSE 8010

# ── 8. Drop to non-root ───────────────────────────────────────────────────────
USER appuser

# ── 9. Health check ───────────────────────────────────────────────────────────
# start_period=120s: allow time for DB init + embedding model load on cold start
HEALTHCHECK --interval=30s --timeout=15s --start-period=120s --retries=5 \
    CMD curl -f http://localhost:${PORT:-8010}/health || exit 1

# ── 10. Startup ───────────────────────────────────────────────────────────────
# tini as PID-1 ensures proper signal handling and zombie reaping
ENTRYPOINT ["/usr/bin/tini", "--"]

# Railway injects $PORT at runtime — we must bind to it.
# Fallback to 8010 for local docker run without Railway.
CMD sh -c "uvicorn main:app \
    --host 0.0.0.0 \
    --port ${PORT:-8010} \
    --workers 1 \
    --loop uvloop \
    --http httptools \
    --log-level info"
