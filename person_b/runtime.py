"""Injectable, reproducible protocol identifiers and simulation timestamps."""

from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5


class Runtime:
    def __init__(self, namespace="floodnet", epoch=None):
        self.namespace = namespace
        self.epoch = epoch or datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.counter = 0

    def new_id(self, kind):
        self.counter += 1
        return uuid5(NAMESPACE_URL, f"{self.namespace}/{kind}/{self.counter}")

    def timestamp(self, tick):
        return self.epoch + timedelta(seconds=tick)
