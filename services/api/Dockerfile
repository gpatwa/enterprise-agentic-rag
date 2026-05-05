# services/api/Dockerfile
# Multi-stage build for the Compass API + bundled SPA.
#
# Three stages:
#   1. python-builder — compile Python deps into /install
#   2. frontend-builder — npm build the Vite SPA into /app/frontend/dist
#   3. runtime — slim image, copies both, runs uvicorn
#
# The runtime image serves the SPA from /app/frontend/dist when
# NEW_UI_ENABLED=true (see main.py). One container, one URL — no
# separate frontend deploy.

# ── Stage 1: Python deps ─────────────────────────────────────────────
FROM python:3.10-slim AS python-builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: Frontend build ──────────────────────────────────────────
# Vite SPA → dist/. Uses npm install (not ci) per the lockfile-drift
# tradeoff documented in .github/workflows/ci-frontend.yml.
FROM node:22-slim AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm install --prefer-offline --no-audit --no-fund

COPY frontend/ ./
# Skip the Playwright prerender step inside Docker — needs browser
# install at build time which adds ~200MB. The marketing /welcome page
# still works as an SPA route; only loses the static prerender.
ENV PRERENDER_SKIP=1
# Build-time env vars for the SPA bundle. Override these at `docker build`
# time (e.g. --build-arg VITE_SENTRY_DSN=...) for prod-grade builds.
ARG VITE_SITE_URL=https://compass.example.com
ARG VITE_SENTRY_DSN=
ARG VITE_SENTRY_ENVIRONMENT=alpha
ARG VITE_SENTRY_RELEASE=
ARG VITE_FEEDBACK_DISABLED=
ENV VITE_SITE_URL=${VITE_SITE_URL} \
    VITE_SENTRY_DSN=${VITE_SENTRY_DSN} \
    VITE_SENTRY_ENVIRONMENT=${VITE_SENTRY_ENVIRONMENT} \
    VITE_SENTRY_RELEASE=${VITE_SENTRY_RELEASE} \
    VITE_FEEDBACK_DISABLED=${VITE_FEEDBACK_DISABLED}
RUN npm run build:fast


# ── Stage 3: Runtime ─────────────────────────────────────────────────
FROM python:3.10-slim

# Security: don't run as root
RUN groupadd -r appuser && useradd -r -g appuser -u 1000 -d /app appuser

# Prevent .pyc + buffered logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Python deps
COPY --from=python-builder /install /usr/local

# App source
COPY . .

# Built SPA — overlays /app/frontend/dist that exists in the source
# (mostly empty before build); main.py auto-detects and serves from
# there when NEW_UI_ENABLED=true.
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health/liveness')" || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
