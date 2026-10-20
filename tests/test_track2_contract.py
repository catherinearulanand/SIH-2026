"""Contract and fixture validation tests for Setu Supply Track 2."""

import pytest
from setu.contracts import Snapshot
from setu.snapshot_provider import load_snapshot


def test_snapshot_fixture_validates():
    snap = load_snapshot("SNAP-26251-150")
    assert isinstance(snap, Snapshot)
    assert snap.snapshot_id == "SNAP-26251-150"
    assert snap.as_of == "2026-05-30"
    assert snap.demand_cutoff == "2026-05-30"
    assert len(snap.items) == 6
    assert len(snap.sites) == 4
    assert len(snap.demand) == 3600  # 4 sites * 6 items * 150 days

    # Check sites have delivery_window_h
    for s in snap.sites:
        assert s.delivery_window_h == 48.0
        assert len(s.storage_capacity_base) == 6

    # Check batches quality states
    states = {b.quality_state for b in snap.batches}
    assert "USABLE" in states
    assert "QUARANTINED" in states
    assert "DAMAGED" in states


def test_load_snapshot_path_traversal_guard():
    with pytest.raises(ValueError, match="Invalid snapshot_id"):
        load_snapshot("../../etc/passwd")

    with pytest.raises(ValueError, match="Invalid snapshot_id"):
        load_snapshot("snap/with/slash")


def test_load_snapshot_missing_raises_not_found():
    with pytest.raises(FileNotFoundError, match="not found"):
        load_snapshot("SNAP-NONEXISTENT")
