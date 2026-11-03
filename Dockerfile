# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock.txt ./
RUN --mount=type=secret,id=proxy_ca,target=/run/proxy_ca \
    if [ -f /run/proxy_ca ]; then PIP_CERT=/run/proxy_ca pip install --no-cache-dir -r requirements.lock.txt; \
    else pip install --no-cache-dir -r requirements.lock.txt; fi
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --create-home app \
    && mkdir -p /app/data && chown app:app /app/data
COPY --chown=app:app app ./app
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request; urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8000/api/health', headers={'Host':__import__('urllib.parse').parse.urlsplit(__import__('os').environ.get('ATC_PUBLIC_ORIGIN','http://127.0.0.1:8000')).netloc}), timeout=4)"
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
