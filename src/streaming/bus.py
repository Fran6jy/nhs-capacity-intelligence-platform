"""Pluggable event bus: real Kafka when configured, in-memory otherwise.

Both backends expose the same `publish(topic, key, value)` /
`poll(timeout)` API, so producer and consumer code is identical whether you
run against Confluent Kafka in production or the batch simulation locally.

Selection:
* `STREAM_BACKEND=kafka` **and** `KAFKA_BOOTSTRAP` set **and** the
  `confluent_kafka` driver importable  -> KafkaBus
* otherwise                                                  -> InMemoryBus
"""
from __future__ import annotations

import os
import queue
from typing import Protocol

from src.utils.logging import get_logger

log = get_logger("streaming.bus")


class Message:
    __slots__ = ("topic", "key", "value")

    def __init__(self, topic: str, key: str | None, value: str) -> None:
        self.topic = topic
        self.key = key
        self.value = value


class EventBus(Protocol):
    def publish(self, topic: str, key: str | None, value: str) -> None: ...
    def poll(self, timeout: float = 1.0) -> Message | None: ...
    def flush(self) -> None: ...
    def close(self) -> None: ...


class InMemoryBus:
    """Thread-safe in-process queue — the batch-simulation backend.

    Singleton-per-process so a producer and consumer constructed separately
    still share the same queue (mirrors a real broker's shared log).
    """

    _q: queue.Queue[Message] = queue.Queue()

    def publish(self, topic: str, key: str | None, value: str) -> None:
        self._q.put(Message(topic, key, value))

    def poll(self, timeout: float = 1.0) -> Message | None:
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def flush(self) -> None:  # no-op: publish is synchronous
        return None

    def close(self) -> None:
        return None


class KafkaBus:
    """Confluent-Kafka backed bus for production deployments."""

    def __init__(self, bootstrap: str, group_id: str, topics: list[str]) -> None:
        from confluent_kafka import Consumer, Producer  # lazy import

        self._producer = Producer({"bootstrap.servers": bootstrap})
        self._consumer = Consumer(
            {
                "bootstrap.servers": bootstrap,
                "group.id": group_id,
                "auto.offset.reset": "earliest",
            }
        )
        if topics:
            self._consumer.subscribe(topics)

    def publish(self, topic: str, key: str | None, value: str) -> None:
        self._producer.produce(topic, key=key, value=value)
        self._producer.poll(0)

    def poll(self, timeout: float = 1.0) -> Message | None:
        msg = self._consumer.poll(timeout)
        if msg is None or msg.error():
            return None
        return Message(
            msg.topic(),
            msg.key().decode() if msg.key() else None,
            msg.value().decode(),
        )

    def flush(self) -> None:
        self._producer.flush()

    def close(self) -> None:
        self._producer.flush()
        self._consumer.close()


def get_bus(group_id: str = "nhs-stream", topics: list[str] | None = None) -> EventBus:
    """Return the configured bus, falling back to the in-memory simulation."""
    backend = os.getenv("STREAM_BACKEND", "memory").lower()
    bootstrap = os.getenv("KAFKA_BOOTSTRAP")
    if backend == "kafka" and bootstrap:
        try:
            log.info("bus.kafka", bootstrap=bootstrap, group=group_id)
            return KafkaBus(bootstrap, group_id, topics or [])
        except Exception as exc:  # noqa: BLE001 — driver missing / broker down
            log.warning("bus.kafka_failed", error=str(exc))
    log.info("bus.in_memory_simulation")
    return InMemoryBus()
