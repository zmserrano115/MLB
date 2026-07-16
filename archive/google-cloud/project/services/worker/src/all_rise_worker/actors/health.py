import dramatiq

from all_rise_worker.broker import broker as broker


@dramatiq.actor
def heartbeat() -> str:
    return "ok"

