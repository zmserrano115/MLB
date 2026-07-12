FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY packages/backend ./packages/backend
COPY services/worker ./services/worker
RUN pip install --no-cache-dir ./packages/backend ./services/worker

USER 65532:65532
CMD ["dramatiq", "all_rise_worker.actors.health"]

