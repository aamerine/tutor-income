# syntax=docker/dockerfile:1
FROM docker.io/library/python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore
WORKDIR /srv
COPY requirements.txt constraints.txt ./
RUN pip install -r requirements.txt
COPY app ./app

# Unit + integration tests: `./run.sh test`
FROM base AS test
COPY requirements-dev.txt pyproject.toml ./
RUN pip install -r requirements-dev.txt
COPY tests ./tests
CMD ["pytest", "tests/unit", "tests/integration"]

FROM base AS runtime
RUN useradd --system --uid 10001 --no-create-home app \
    && mkdir /data && chown app:app /data
USER app
ENV TUTOR_DB_PATH=/data/tutor.db
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"]
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
