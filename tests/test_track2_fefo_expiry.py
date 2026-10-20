"""Test 5: Expired, quarantined, and damaged batches never count as usable stock in projection."""

from setu.contracts import (
    AggregatePrediction,
    Batch,
    DailyPrediction,
    ForecastRun,
    Item,
    Site,
    Snapshot,
)
from setu.projection import project_stock_and_drafts


def test_unusable_and_expired_batches_excluded():
    cutoff = "2026-05-30"
    item = Item(item_id="WATER-20L", base_unit="can", mass_kg_per_unit=20.0, min_shelf_days=365, priority=1)
    site = Site(
        site_id="FICTIONAL-A",
        node_id="NODE-A",
        storage_capacity_base={"WATER-20L": 500},
        delivery_window_h=48.0,
    )

    batches = [
        # Batch 1: Expired before/at cutoff date -> unusable
        Batch(
            batch_id="BAT-EXPIRED",
            site_id="FICTIONAL-A",
            item_id="WATER-20L",
            qty_base=50,
            expiry_date="2026-05-20",
            quality_state="USABLE",
        ),
        # Batch 2: Quarantined -> unusable
        Batch(
            batch_id="BAT-QUARANTINED",
            site_id="FICTIONAL-A",
            item_id="WATER-20L",
            qty_base=40,
            expiry_date="2026-10-01",
            quality_state="QUARANTINED",
        ),
        # Batch 3: Damaged -> unusable
        Batch(
            batch_id="BAT-DAMAGED",
            site_id="FICTIONAL-A",
            item_id="WATER-20L",
            qty_base=30,
            expiry_date="2026-10-01",
            quality_state="DAMAGED",
        ),
        # Batch 4: Valid usable batch
        Batch(
            batch_id="BAT-VALID",
            site_id="FICTIONAL-A",
            item_id="WATER-20L",
            qty_base=25,
            expiry_date="2026-12-01",
            quality_state="USABLE",
        ),
    ]

    snap = Snapshot(
        snapshot_id="SNAP-FEFO-TEST",
        as_of=cutoff,
        demand_cutoff=cutoff,
        items=[item],
        sites=[site],
        batches=batches,
        reservations=[],
        inbound=[],
        demand=[],
        graph_version="v1",
    )

    fc_run = ForecastRun(
        run_id="fc-test",
        input_snapshot_id="SNAP-FEFO-TEST",
        cutoff=cutoff,
        horizon_days=30,
        model_version="test",
        method_by_series={"FICTIONAL-A:WATER-20L": "test"},
        predictions=[DailyPrediction(site_id="FICTIONAL-A", item_id="WATER-20L", date="2026-05-31", mean=5.0)],
        aggregate=[
            AggregatePrediction(
                site_id="FICTIONAL-A",
                item_id="WATER-20L",
                window_days=8,
                p10=20.0,
                p50=40.0,
                p90=50.0,
            )
        ],
        range_method="test",
        calibrated=False,
        dataset_fingerprint="fp-test",
        seed=26251,
    )

    drafts = project_stock_and_drafts(snap, fc_run, site_windows={"FICTIONAL-A": 8})
    assert len(drafts) == 1
    d = drafts[0]

    # Only BAT-VALID (25 units) should be counted in allocatable stock!
    # BAT-EXPIRED (50), BAT-QUARANTINED (40), and BAT-DAMAGED (30) must NOT be counted!
    assert d.allocatable == 25
