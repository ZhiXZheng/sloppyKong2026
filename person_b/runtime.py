"""Injectable, reproducible protocol identifiers and simulation timestamps."""

from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5


# Supply reproducible IDs and timezone-aware story timestamps to protocol producers.
class Runtime:
    # Separate deterministic identity namespaces from wall-clock time.
    def __init__(self, namespace="floodnet", epoch=None):
        self.namespace = namespace
        self.epoch = epoch or datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.counter = 0

    # Derive a unique stable UUID from the namespace and monotonic local counter.
    def new_id(self, kind):
        self.counter += 1
        return uuid5(NAMESPACE_URL, f"{self.namespace}/{kind}/{self.counter}")

    # Advance the configured story epoch by simulation ticks.
    def timestamp(self, tick):
        return self.epoch + timedelta(seconds=tick)
