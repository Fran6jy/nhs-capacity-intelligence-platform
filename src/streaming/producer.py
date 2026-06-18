"""A&E attendance producer — emits events onto the bus."""
from __future__ import annotations

import time

from src.streaming.bus import EventBus, get_bus
from src.streaming.events import TOPIC_AE_ATTENDANCE, generate_event
from src.utils.logging import get_logger

log = get_logger("streaming.producer")


def run_producer(
    n_events: int = 2_000,
    rate_per_sec: float = 200.0,
    bus: EventBus | None = None,
) -> int:
    """Emit ``n_events`` A&E attendances at roughly ``rate_per_sec``.

    Returns the number of events published. Partition key is the hospital_id so
    a real Kafka topic keeps per-site ordering.
    """
    bus = bus or get_bus(topics=[TOPIC_AE_ATTENDANCE])
    interval = 1.0 / rate_per_sec if rate_per_sec > 0 else 0.0
    published = 0
    for i in range(n_events):
        event = generate_event()
        bus.publish(TOPIC_AE_ATTENDANCE, key=event.hospital_id, value=event.to_json())
        published += 1
        if interval and i % 50 == 0:
            time.sleep(interval * 50)
    bus.flush()
    log.info("producer.done", published=published)
    return published


if __name__ == "__main__":
    run_producer()
