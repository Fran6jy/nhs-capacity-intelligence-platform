"""Real-time ingestion layer.

A pluggable event bus (`bus.py`) that runs against a real Kafka cluster when
one is configured (`KAFKA_BOOTSTRAP` + the `confluent-kafka` driver), and falls
back to an in-process queue — a *batch simulation* — otherwise. This keeps the
streaming pipeline runnable on a laptop with no infrastructure while exposing
the exact same producer/consumer API used in production.
"""
