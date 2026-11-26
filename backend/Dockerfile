# Debian/glibc supports the existing PyTorch, PyAV and Azure Speech wheels.
FROM python:3.12.16-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/home/app/.cache/huggingface

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libgomp1 libasound2 libssl3 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home app \
    && mkdir -p /home/app/.cache/huggingface \
    && chown -R app:app /home/app/.cache

COPY requirements-linux-amd64.txt ./requirements-linux-amd64.txt
# Embeddings use CPU PyTorch. Ollama uses the GPU on the host.
RUN python -m pip install --require-hashes --only-binary=:all: -r requirements-linux-amd64.txt \
    && python -m pip check

COPY --chown=app:app app ./app
COPY --chown=app:app docker_healthcheck.py ./docker_healthcheck.py
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD ["python", "/app/docker_healthcheck.py"]
# One worker preserves the existing process-local admission/rate-limit semantics.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-proxy-headers", "--no-access-log"]
