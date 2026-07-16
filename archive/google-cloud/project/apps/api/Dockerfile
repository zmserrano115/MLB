FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY packages/backend ./packages/backend
COPY apps/api ./apps/api
RUN pip install --no-cache-dir ./packages/backend ./apps/api

FROM runtime AS validation
USER root
RUN pip install --no-cache-dir pytest httpx
COPY tests ./tests
RUN pytest -q \
    tests/test_phase3_api.py \
    tests/test_phase4_migration.py \
    tests/test_phase7_slate_api.py

FROM runtime AS production
USER 65532:65532
EXPOSE 8000
CMD ["uvicorn", "all_rise_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
