"""Deterministic synthetic fixture generator for Setu Supply Track 2.

Seed: 26251
Generates:
  - fixtures/SNAP-26251-150.json (days 0-149, cutoff 2026-05-30)
  - fixtures/truth.json (days 150-179, 2026-05-31 to 2026-06-29)
  - fixtures/demand_raw.csv (dirty CSV for Track 1 import validation)
"""

import csv
import json
from datetime import date, timedelta
from pathlib import Path
import numpy as np

from setu.contracts import (
    Batch,
    DemandRecord,
    InboundOrder,
    Item,
    Reservation,
    Site,
    Snapshot,
)

SEED = 26251
START_DATE = date(2026, 1, 1)
TOTAL_DAYS = 180
CUTOFF_DAY = 149  # Day 149 is 2026-05-30 (0-indexed days 0..149 = 150 days)

FIXTURES_DIR = Path(__file__).resolve().parent

ITEMS = [
    Item(item_id="RATION-PACK", base_unit="pack", mass_kg_per_unit=2.5, min_shelf_days=180, priority=1),
    Item(item_id="WATER-20L", base_unit="can", mass_kg_per_unit=20.0, min_shelf_days=365, priority=1),
    Item(item_id="BLANKET", base_unit="unit", mass_kg_per_unit=1.2, min_shelf_days=720, priority=2),
    Item(item_id="SOCKS", base_unit="pair", mass_kg_per_unit=0.1, min_shelf_days=720, priority=4),
    Item(item_id="BANDAGE-PACK", base_unit="pack", mass_kg_per_unit=0.5, min_shelf_days=365, priority=2),
    Item(item_id="ORS-BOX", base_unit="box", mass_kg_per_unit=0.3, min_shelf_days=365, priority=3),
]

SITES = [
    Site(
        site_id="FICTIONAL-A",
        node_id="NODE-A",
        storage_capacity_base={
            "RATION-PACK": 600,
            "WATER-20L": 250,
            "BLANKET": 400,
            "SOCKS": 1000,
            "BANDAGE-PACK": 500,
            "ORS-BOX": 600,
        },
        delivery_window_h=48.0,
    ),
    Site(
        site_id="FICTIONAL-B",
        node_id="NODE-B",
        storage_capacity_base={
            "RATION-PACK": 500,
            "WATER-20L": 200,
            "BLANKET": 350,
            "SOCKS": 800,
            "BANDAGE-PACK": 400,
            "ORS-BOX": 500,
        },
        delivery_window_h=48.0,
    ),
    Site(
        site_id="FICTIONAL-C",
        node_id="NODE-C",
        storage_capacity_base={
            "RATION-PACK": 450,
            "WATER-20L": 180,
            "BLANKET": 300,
            "SOCKS": 700,
            "BANDAGE-PACK": 350,
            "ORS-BOX": 450,
        },
        delivery_window_h=48.0,
    ),
    Site(
        site_id="FICTIONAL-D",
        node_id="NODE-D",
        storage_capacity_base={
            "RATION-PACK": 550,
            "WATER-20L": 220,
            "BLANKET": 380,
            "SOCKS": 900,
            "BANDAGE-PACK": 450,
            "ORS-BOX": 550,
        },
        delivery_window_h=48.0,
    ),
]


def generate_series_demand(site_id: str, item_id: str, rng: np.random.Generator) -> list[DemandRecord]:
    """Generate 180 days of demand records with injected patterns, missing values, and stockouts."""
    site_mult = {"FICTIONAL-A": 1.2, "FICTIONAL-B": 1.0, "FICTIONAL-C": 0.8, "FICTIONAL-D": 1.1}[site_id]
    records = []

    # Local simulated inventory to track realistic stockouts
    sim_stock = 150.0 * site_mult

    for day_idx in range(TOTAL_DAYS):
        current_date = START_DATE + timedelta(days=day_idx)
        date_str = current_date.isoformat()
        weekday = current_date.weekday()  # 0=Monday, 6=Sunday

        # Periodic stock replenishment in simulation every 14 days
        if day_idx % 14 == 0:
            sim_stock += 120.0 * site_mult

        # Generate base requested demand according to item pattern
        if item_id == "RATION-PACK":
            # Weekly seasonality: higher demand on weekends (Fri/Sat/Sun)
            weekend_boost = 1.4 if weekday in (4, 5, 6) else 0.85
            base = rng.normal(26.0 * site_mult * weekend_boost, 4.0)
            req = max(2.0, base)
        elif item_id == "WATER-20L":
            # Weekly seasonality: midweek & weekend peaks
            weekend_boost = 1.3 if weekday in (2, 5, 6) else 0.9
            base = rng.normal(20.0 * site_mult * weekend_boost, 3.5)
            req = max(1.0, base)
        elif item_id == "BLANKET":
            # Intermittent burst: 80% zero, 20% burst
            if rng.random() < 0.22:
                req = float(rng.integers(15, 45)) * site_mult
            else:
                req = 0.0
        elif item_id == "SOCKS":
            # Steady Poisson/Normal
            req = max(0.0, float(rng.poisson(8.0 * site_mult)))
        elif item_id == "BANDAGE-PACK":
            # Intermittent: 65% zero, 35% burst
            if rng.random() < 0.35:
                req = float(rng.integers(8, 28)) * site_mult
            else:
                req = 0.0
        elif item_id == "ORS-BOX":
            # Steady with small noise
            req = max(1.0, float(rng.poisson(12.0 * site_mult)))
        else:
            req = 5.0

        # Inject 3% random missing days
        if rng.random() < 0.03:
            records.append(
                DemandRecord(
                    site_id=site_id,
                    item_id=item_id,
                    date=date_str,
                    requested=None,
                    issued=0.0,
                    unmet=None,
                    missing_flag=True,
                    stockout_flag=False,
                )
            )
            continue

        # Simulate stockout when sim_stock is insufficient
        req_val = round(req, 1)
        if sim_stock >= req_val:
            issued_val = req_val
            unmet_val = 0.0
            stockout_flag = False
            sim_stock -= issued_val
        else:
            issued_val = max(0.0, round(sim_stock, 1))
            unmet_val = round(req_val - issued_val, 1)
            stockout_flag = True
            sim_stock = 0.0

            # Realistic label bias: unmet and true requested demand missing on ~30% of stockout days
            if rng.random() < 0.30:
                unmet_val = None
                req_val = None

        records.append(
            DemandRecord(
                site_id=site_id,
                item_id=item_id,
                date=date_str,
                requested=req_val,
                issued=issued_val,
                unmet=unmet_val,
                missing_flag=False,
                stockout_flag=stockout_flag,
            )
        )

    return records


def generate_batches_and_inventory(rng: np.random.Generator):
    """Generate initial batches, reservations, and inbound orders."""
    batches = []
    reservations = []
    inbound = []

    batch_counter = 1
    cutoff_date = START_DATE + timedelta(days=CUTOFF_DAY)

    for site in SITES:
        for item in ITEMS:
            # Generate 2-3 batches per item per site
            num_batches = int(rng.integers(2, 4))
            for b_idx in range(num_batches):
                # Staggered expiry: some short (30-60 days), some medium (180 days), some long (360 days)
                shelf_offset = int(rng.choice([35, 60, 120, 240, 400]))
                expiry_dt = cutoff_date + timedelta(days=shelf_offset)

                # Quality state: default USABLE, inject 1 QUARANTINED and 1 DAMAGED across dataset
                state = "USABLE"
                if site.site_id == "FICTIONAL-B" and item.item_id == "BANDAGE-PACK" and b_idx == 0:
                    state = "QUARANTINED"
                elif site.site_id == "FICTIONAL-C" and item.item_id == "RATION-PACK" and b_idx == 0:
                    state = "DAMAGED"

                qty = int(rng.integers(40, 150))
                batches.append(
                    Batch(
                        batch_id=f"BAT-{batch_counter:04d}",
                        site_id=site.site_id,
                        item_id=item.item_id,
                        qty_base=qty,
                        expiry_date=expiry_dt.isoformat(),
                        quality_state=state,
                    )
                )
                batch_counter += 1

            # Reservations at t0 for certain sites/items
            if rng.random() < 0.4:
                res_qty = int(rng.integers(10, 30))
                reservations.append(
                    Reservation(
                        site_id=site.site_id,
                        item_id=item.item_id,
                        qty_base=res_qty,
                    )
                )

            # Inbound shipments arriving during horizon
            if rng.random() < 0.35:
                inbound_days = int(rng.integers(5, 18))
                inbound_dt = cutoff_date + timedelta(days=inbound_days)
                inbound_qty = int(rng.integers(30, 80))
                inbound.append(
                    InboundOrder(
                        site_id=site.site_id,
                        item_id=item.item_id,
                        qty_base=inbound_qty,
                        eta=inbound_dt.isoformat(),
                    )
                )

    return batches, reservations, inbound


def generate_dirty_csv(demand_records: list[DemandRecord], batches: list[Batch], rng: np.random.Generator, path: Path):
    """Write dirty CSV for Track 1 import validation."""
    rows = []
    batch_ids = [b.batch_id for b in batches] + ["UNKNOWN-BATCH-999"]

    for r in demand_records[:200]:  # sample 200 records
        unit_str = "pack"
        if rng.random() < 0.15:
            unit_str = rng.choice(["kgs", "boxes", "PIECES", "unknown_unit"])

        batch_ref = rng.choice(batch_ids) if rng.random() < 0.3 else ""

        rows.append({
            "site_id": r.site_id,
            "item_id": r.item_id,
            "date": r.date,
            "requested": r.requested if r.requested is not None else "",
            "issued": r.issued,
            "unmet": r.unmet if r.unmet is not None else "",
            "unit": unit_str,
            "batch_ref": batch_ref,
        })

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["site_id", "item_id", "date", "requested", "issued", "unmet", "unit", "batch_ref"]
        )
        writer.writeheader()
        writer.writerows(rows)


def main():
    rng = np.random.default_rng(SEED)

    # 1. Generate all demand series (180 days)
    all_demand: list[DemandRecord] = []
    for site in SITES:
        for item in ITEMS:
            series = generate_series_demand(site.site_id, item.item_id, rng)
            all_demand.extend(series)

    # 2. Generate inventory, batches, reservations, inbound
    batches, reservations, inbound = generate_batches_and_inventory(rng)

    cutoff_date = START_DATE + timedelta(days=CUTOFF_DAY)
    cutoff_str = cutoff_date.isoformat()  # "2026-05-30"

    # 3. Partition demand: days <= cutoff for snapshot, days > cutoff for truth
    snapshot_demand = [d for d in all_demand if d.date <= cutoff_str]
    truth_demand = [d for d in all_demand if d.date > cutoff_str]

    # 4. Build Snapshot object
    snapshot = Snapshot(
        snapshot_id="SNAP-26251-150",
        as_of=cutoff_str,
        demand_cutoff=cutoff_str,
        items=ITEMS,
        sites=SITES,
        batches=batches,
        reservations=reservations,
        inbound=inbound,
        demand=snapshot_demand,
        graph_version="setu_supply_graph_v1",
        source_versions={"fixtures_gen": "1.0.0", "seed": str(SEED)},
    )

    # 5. Write fixtures/SNAP-26251-150.json
    snapshot_path = FIXTURES_DIR / "SNAP-26251-150.json"
    snapshot_path.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
    print(f"Wrote snapshot: {snapshot_path} ({len(snapshot_demand)} demand rows)")

    # 6. Write fixtures/truth.json (evaluation only)
    truth_path = FIXTURES_DIR / "truth.json"
    truth_payload = {
        "cutoff": cutoff_str,
        "seed": SEED,
        "truth_days": TOTAL_DAYS - CUTOFF_DAY - 1,
        "start_date": (cutoff_date + timedelta(days=1)).isoformat(),
        "end_date": (START_DATE + timedelta(days=TOTAL_DAYS - 1)).isoformat(),
        "demand": [d.model_dump() for d in truth_demand],
    }
    truth_path.write_text(json.dumps(truth_payload, indent=2), encoding="utf-8")
    print(f"Wrote truth: {truth_path} ({len(truth_demand)} demand rows)")

    # 7. Write fixtures/demand_raw.csv
    dirty_path = FIXTURES_DIR / "demand_raw.csv"
    generate_dirty_csv(all_demand, batches, rng, dirty_path)
    print(f"Wrote dirty demand raw: {dirty_path}")


if __name__ == "__main__":
    main()
