FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    OMP_THREAD_LIMIT=1 \
    SCANSPLIT_DATA_DIR=/data \
    SCANSPLIT_RUNTIME_DIR=/runtime \
    SCANSPLIT_PORT=8080

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates git poppler-utils tesseract-ocr tesseract-ocr-deu tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 scansplit \
    && useradd --uid 1000 --gid scansplit --create-home scansplit \
    && mkdir -p /data /runtime \
    && chown scansplit:scansplit /data /runtime

COPY entrypoint.sh /usr/local/bin/scansplit-entrypoint
RUN chmod 755 /usr/local/bin/scansplit-entrypoint
USER scansplit:scansplit
WORKDIR /runtime
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=4)"
ENTRYPOINT ["/usr/bin/tini", "-g", "--", "/usr/local/bin/scansplit-entrypoint"]
