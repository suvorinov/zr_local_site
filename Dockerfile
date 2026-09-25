FROM python:3.12-slim

# UID/GID процесса внутри контейнера соответствуют владельцу
# bind-mount каталогов хоста (data/, app/static/greetings).
ARG UID=1000
ARG GID=1000

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p app/static/greetings data \
    && groupadd -g ${GID} appuser \
    && useradd -u ${UID} -g ${GID} -d /app -s /sbin/nologin appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8800

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; assert urllib.request.urlopen('http://localhost:8800/healthz').status == 200" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8800"]
