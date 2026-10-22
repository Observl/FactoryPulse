FROM node:22-bookworm-slim AS frontend
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile
COPY index.html tsconfig.json vite.config.ts ./
COPY src ./src
COPY scripts/check-button-system.mjs ./scripts/check-button-system.mjs
COPY public ./public
ARG BUILD_COMMIT=unknown
RUN VITE_STATIC_DEMO=false VITE_BUILD_COMMIT=$BUILD_COMMIT npm run build

FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 \
    FACTORYPULSE_DEPLOYMENT=cloud FACTORYPULSE_DATA_DIR=/data \
    FACTORYPULSE_UI_DIR=/app/dist FACTORYPULSE_SERVE_UI=1 TZ=Asia/Shanghai
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 tzdata && rm -rf /var/lib/apt/lists/*
COPY backend/requirements-cloud.lock.txt ./requirements-cloud.lock.txt
RUN pip install --no-cache-dir -r requirements-cloud.lock.txt
COPY backend ./backend
COPY config ./config
COPY data/model-validation ./data/model-validation
COPY --from=frontend /app/dist ./dist
RUN useradd --uid 10001 --create-home factorypulse && mkdir /data && chown factorypulse:factorypulse /data
USER factorypulse
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=4)"
CMD ["python","-m","uvicorn","backend.cloud_server:app","--host","0.0.0.0","--port","8000","--workers","1","--proxy-headers","--forwarded-allow-ips","*"]
