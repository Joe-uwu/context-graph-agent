# ingestion-service image. Built from the repo root so it can access the shared cortex
# packages; multi-stage so the runtime layer carries no build toolchain. Runs only the
# ingestion process. See services/ingestion-service/README.md.
#
#   docker build -f services/ingestion-service/Dockerfile -t cortex/ingestion-service .

FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY pyproject.toml README.md CODE_README.md ./
COPY packages ./packages
COPY services ./services
COPY tools ./tools
RUN pip install ".[api,kafka,neo4j,qdrant,otel,github]"

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH="/opt/venv/bin:$PATH" \
    CORTEX_HTTP_PORT=8001
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY packages ./packages
COPY services ./services
COPY tools ./tools
COPY pyproject.toml README.md CODE_README.md ./
RUN useradd -m -u 10001 cortex && chown -R cortex /app
USER cortex
EXPOSE 8001
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8001/health').status==200 else 1)"
CMD ["python", "-m", "cortex.services.ingestion.main"]
