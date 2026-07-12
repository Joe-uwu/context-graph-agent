# llm-service image. Built from the repo root; runs only the llm process.
#   docker build -f services/llm-service/Dockerfile -t cortex/llm-service .

FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY pyproject.toml README.md CODE_README.md ./
COPY packages ./packages
COPY services ./services
COPY tools ./tools
RUN pip install ".[api,kafka,neo4j,qdrant,otel]"

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH="/opt/venv/bin:$PATH" \
    CORTEX_HTTP_PORT=8006
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY packages ./packages
COPY services ./services
COPY tools ./tools
COPY pyproject.toml README.md CODE_README.md ./
RUN useradd -m -u 10001 cortex && chown -R cortex /app
USER cortex
EXPOSE 8006
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8006/health').status==200 else 1)"
CMD ["python", "-m", "cortex.services.llm.main"]
