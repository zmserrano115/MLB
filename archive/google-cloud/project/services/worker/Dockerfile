FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY packages/backend ./packages/backend
COPY services/worker ./services/worker
RUN pip install --no-cache-dir ./packages/backend ./services/worker
RUN mkdir -p /var/lib/all-rise/artifacts && chown -R 65532:65532 /var/lib/all-rise

FROM runtime AS validation
USER root
RUN pip install --no-cache-dir pytest ruff mypy
COPY pyproject.toml ./pyproject.toml
COPY tests ./tests
RUN ruff check packages/backend/src services/worker/src tests/test_phase6_jobs.py tests/test_phase7_publishers.py \
    && mypy packages/backend/src/all_rise/jobs services/worker/src/all_rise_worker \
    && pytest -q tests/test_phase6_jobs.py tests/test_phase7_publishers.py

FROM runtime AS production
USER 65532:65532
CMD ["dramatiq", "all_rise_worker.actors.health", "all_rise_worker.actors.tasks", "--processes", "2", "--threads", "4"]
