"""A&E attendance producer — emits events onto the bus."""
from __future__ import annotations

import random
import time
from datetime import datetime, timedelta, timezone

from src.streaming.bus import EventBus, get_bus
from src.streaming.events import TOPIC_AE_ATTENDANCE, generate_event
from src.utils.logging import get_logger

log = get_logger("streaming.producer")


def run_producer(
    n_events: int = 2_000,
    rate_per_sec: float = 200.0,
    bus: EventBus | None = None,
    spread_minutes: int = 0,
) -> int:
    """Emit ``n_events`` A&E attendances at roughly ``rate_per_sec``.

    Returns the number of events published. Partition key is the hospital_id so
    a real Kafka topic keeps per-site ordering. When ``spread_minutes`` > 0 the
    event timestamps are distributed across the last N minutes — used to seed a
    realistic per-minute curve for the live dashboard rather than one spike.
    """
    bus = bus or get_bus(topics=[TOPIC_AE_ATTENDANCE])
    interval = 1.0 / rate_per_sec if rate_per_sec > 0 else 0.0
    now = datetime.now(timezone.utc)
    published = 0
    for i in range(n_events):
        ts = None
        if spread_minutes > 0:
            # Weight toward the present so the curve trends up to "now".
            offset = (1 - random.random() ** 2) * spread_minutes
            ts = now - timedelta(minutes=offset)
        event = generate_event(now=ts)
        bus.publish(TOPIC_AE_ATTENDANCE, key=event.hospital_id, value=event.to_json())
        published += 1
        if interval and i % 50 == 0:
            time.sleep(interval * 50)
    bus.flush()
    log.info("producer.done", published=published)
    return published


if __name__ == "__main__":
    run_producer()
