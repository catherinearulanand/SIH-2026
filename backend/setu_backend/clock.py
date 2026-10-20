"""UTC wall clock, replaceable in acceptance tests without changing live timestamps."""
from datetime import datetime, timezone


def utcnow():
    return datetime.now(timezone.utc)


def today():
    return utcnow().date()
