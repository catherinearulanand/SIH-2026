"""Snapshot provider seam for Setu Supply Track 2."""

import re
from pathlib import Path
from setu.contracts import Snapshot

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
SNAPSHOT_ID_REGEX = re.compile(r"^[A-Za-z0-9-]{1,64}$")


def load_snapshot(snapshot_id: str) -> Snapshot:
    """Load a snapshot by ID.

    Currently reads from local JSON fixtures.
    When Track 1 database lands, this function is updated to query Track 1's DB.
    """
    if not SNAPSHOT_ID_REGEX.match(snapshot_id):
        raise ValueError(f"Invalid snapshot_id: {snapshot_id}")

    fixture_path = FIXTURES_DIR / f"{snapshot_id}.json"
    if fixture_path.exists():
        return Snapshot.model_validate_json(fixture_path.read_text(encoding="utf-8"))

    raise FileNotFoundError(f"Snapshot '{snapshot_id}' not found")
