"""Test 4: Replenishment draft exact calculation and storage capacity split."""

from setu.contracts import (
    Batch,
    DailyPrediction,
    ForecastRun,
    InboundOrder,
    Item,
    Reservation,
    Site,
    Snapshot,
)
from setu.projection import project_stock_and_drafts


def test_replenishment_draft_exact_calculation_and_capacity_split():
    """Formula invariant:

    Target (100) + Buffer (20) - Allocatable (50) - Inbound (10) = 60.
    With capacity_free = 40 on arrival date ->
      proposed_qty = 40, capacity_gap = 20, split offered.
    """
    cutoff = "2026-05-30"
    item = Item(item_id="RATION-PACK", base_unit="pack", mass_kg_per_unit=2.5, min_shelf_days=180, priority=1)
    # Storage capacity is 100 packs.
    # Today's stock: 60 physical stock, 10 reserved -> 50 allocatable usable stock.
    # On arrival date (t_arr = 2026-05-31), 60 packs remain in physical stock.
    # Free capacity = 100 - 60 = 40.
    site = Site(
        site_id="FICTIONAL-A",
        node_id="NODE-A",
        storage_capacity_base={"RATION-PACK": 100},
        delivery_window_h=48.0,
    )


    batches = [
        Batch(
            batch_id="BAT-001",
            site_id="FICTIONAL-A",
            item_id="RATION-PACK",
            qty_base=60,
            expiry_date="2026-12-31",
            quality_state="USABLE",
        )
    ]
    # Reservation of 10 packs: 60 - 10 = 50 allocatable
    reservations = [Reservation(site_id="FICTIONAL-A", item_id="RATION-PACK", qty_base=10)]
    # Inbound of 10 packs arriving within horizon
    inbound = [InboundOrder(site_id="FICTIONAL-A", item_id="RATION-PACK", qty_base=10, eta="2026-06-03")]

    snap = Snapshot(
        snapshot_id="SNAP-TEST-DRAFT",
        as_of=cutoff,
        demand_cutoff=cutoff,
        items=[item],
        sites=[site],
        batches=batches,
        reservations=reservations,
        inbound=inbound,
        demand=[],
        graph_version="v1",
    )

    # Lead time window W = L + R = 1 + 7 = 8 days.
    # Set P90 aggregate over 8 days to 120 (representing 100 base + 20 buffer)
    from setu.contracts import AggregatePrediction

    fc_run = ForecastRun(
        run_id="fc-test",
        input_snapshot_id="SNAP-TEST-DRAFT",
        cutoff=cutoff,
        horizon_days=30,
        model_version="test",
        method_by_series={"FICTIONAL-A:RATION-PACK": "test"},
        predictions=[DailyPrediction(site_id="FICTIONAL-A", item_id="RATION-PACK", date=f"2026-05-{31+d if d==0 else 60}", mean=0.0) for d in range(1)],
        aggregate=[
            AggregatePrediction(
                site_id="FICTIONAL-A",
                item_id="RATION-PACK",
                window_days=8,
                p10=80.0,
                p50=100.0,
                p90=120.0,  # Target = 120
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

    assert d.target == 120
    assert d.allocatable == 50
    assert d.inbound_in_horizon == 10
    # Raw requirement Q = 120 - 50 - 10 = 60
    # Capacity free = 90 - 50 = 40
    assert d.capacity_free == 40
    assert d.proposed_qty == 40
    assert d.capacity_gap == 20
    assert len(d.split) == 2
    assert d.split[0].qty == 40
    assert d.split[1].qty == 20
