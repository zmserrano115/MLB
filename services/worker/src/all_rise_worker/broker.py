import os

import dramatiq
from dramatiq.brokers.redis import RedisBroker

# Dramatiq's RedisBroker constructor currently lacks type annotations.
broker = RedisBroker(  # type: ignore[no-untyped-call]
    url=os.getenv("REDIS_BROKER_URL", "redis://localhost:6379/1")
)
dramatiq.set_broker(broker)
