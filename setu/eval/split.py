"""Strict 0-indexed temporal split utilities for Setu Supply Track 2."""

from datetime import date, timedelta
from setu.contracts import DemandRecord

START_DATE = date(2026, 1, 1)

TRAIN_START_DATE = "2026-01-01"   # Day 0
TRAIN_END_DATE = "2026-04-30"     # Day 119 (120 days)

VAL_START_DATE = "2026-05-01"     # Day 120
VAL_END_DATE = "2026-05-30"       # Day 149 (30 days)

TEST_START_DATE = "2026-05-31"    # Day 150
TEST_END_DATE = "2026-06-29"      # Day 179 (30 days)


def filter_demand_by_date(
    records: list[DemandRecord],
    start_date: str,
    end_date: str,
) -> list[DemandRecord]:
    """Filter records inclusive of start_date and end_date."""
    return [r for r in records if start_date <= r.date <= end_date]


def split_train_validation(
    records: list[DemandRecord],
) -> tuple[list[DemandRecord], list[DemandRecord]]:
    """Split snapshot history into train (days 0-119) and validation (days 120-149)."""
    train = filter_demand_by_date(records, TRAIN_START_DATE, TRAIN_END_DATE)
    val = filter_demand_by_date(records, VAL_START_DATE, VAL_END_DATE)
    return train, val
