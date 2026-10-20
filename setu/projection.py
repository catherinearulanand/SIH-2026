"""Inventory projection, FEFO stock depletion, and replenishment draft generation for Setu Supply Track 2."""

from datetime import date, timedelta
from typing import Literal
import numpy as np

from setu.contracts import (
    Batch,
    ForecastRun,
    InboundOrder,
    ReplenishmentDraft,
    ReplenishmentSplit,
    Snapshot,
)


def project_stock_and_drafts(
    snapshot: Snapshot,
    forecast_run: ForecastRun,
    site_windows: dict[str, int],
    buffer_pct: float = 0.20,
) -> list[ReplenishmentDraft]:
    """Simulate daily FEFO inventory projection and generate replenishment drafts.

    Features:
    - Stock categorization: Usable vs Physical (Physical includes Quarantined & Damaged).
    - FEFO depletion against forecast daily demand.
    - Reservations deducted strictly once at t0 (no double counting).
    - Free capacity checked on arrival date t_arr against projected physical stock.
    - Capacity split proposed when raw requirement exceeds free storage space.
    """
    cutoff_dt = date.fromisoformat(snapshot.demand_cutoff)

    # Pre-index batches by (site_id, item_id)
    batches_by_series: dict[tuple[str, str], list[Batch]] = {}
    for b in snapshot.batches:
        batches_by_series.setdefault((b.site_id, b.item_id), []).append(b)

    # Pre-index reservations by (site_id, item_id)
    res_by_series: dict[tuple[str, str], int] = {}
    for r in snapshot.reservations:
        res_by_series[(r.site_id, r.item_id)] = res_by_series.get((r.site_id, r.item_id), 0) + r.qty_base

    # Pre-index inbound by (site_id, item_id)
    inbound_by_series: dict[tuple[str, str], list[InboundOrder]] = {}
    for o in snapshot.inbound:
        inbound_by_series.setdefault((o.site_id, o.item_id), []).append(o)

    # Pre-index daily predictions by (site_id, item_id, date)
    daily_preds: dict[tuple[str, str, str], float] = {}
    for p in forecast_run.predictions:
        daily_preds[(p.site_id, p.item_id, p.date)] = p.mean

    # Pre-index aggregate predictions by (site_id, item_id, window_days)
    agg_preds: dict[tuple[str, str, int], float] = {}
    for a in forecast_run.aggregate:
        agg_preds[(a.site_id, a.item_id, a.window_days)] = a.p90

    drafts: list[ReplenishmentDraft] = []

    for site in snapshot.sites:
        w_site = site_windows.get(site.site_id, 8)
        # Transit days L = W - 7
        transit_days = max(1, w_site - 7)
        arrival_dt = cutoff_dt + timedelta(days=transit_days)
        arrival_date_str = arrival_dt.isoformat()

        proj_days = w_site + 7  # Simulation duration

        for item in snapshot.items:
            key = (site.site_id, item.item_id)
            series_batches = batches_by_series.get(key, [])
            reservations_qty = res_by_series.get(key, 0)
            series_inbound = inbound_by_series.get(key, [])

            # Active tracking batches: dict with qty, expiry, state
            sim_batches = [
                {
                    "batch_id": b.batch_id,
                    "qty": b.qty_base,
                    "expiry": b.expiry_date,
                    "state": b.quality_state,
                }
                for b in series_batches
            ]

            # Initial stock at t0
            usable_t0 = sum(b["qty"] for b in sim_batches if b["state"] == "USABLE" and b["expiry"] > snapshot.demand_cutoff)
            allocatable_t0 = max(0, usable_t0 - reservations_qty)

            # Daily simulation
            shortage_days = 0
            unmet_qty = 0.0
            expiry_waste = 0

            # Map from date -> projected physical stock (usable + quarantined + damaged)
            projected_physical: dict[str, int] = {}

            curr_usable_qty = allocatable_t0

            for d in range(1, proj_days + 1):
                day_dt = cutoff_dt + timedelta(days=d)
                day_str = day_dt.isoformat()

                # 1. Add inbound arrivals
                day_inbound = sum(o.qty_base for o in series_inbound if o.eta == day_str)
                curr_usable_qty += day_inbound
                for o in series_inbound:
                    if o.eta == day_str:
                        sim_batches.append(
                            {
                                "batch_id": f"INB-{o.eta}",
                                "qty": o.qty_base,
                                "expiry": (day_dt + timedelta(days=item.min_shelf_days)).isoformat(),
                                "state": "USABLE",
                            }
                        )

                # 2. Check and expire batches on this day
                for b in sim_batches:
                    if b["qty"] > 0 and b["expiry"] <= day_str:
                        if b["state"] == "USABLE":
                            expiry_waste += b["qty"]
                            curr_usable_qty = max(0, curr_usable_qty - b["qty"])
                        b["qty"] = 0

                # 3. FEFO Depletion against daily forecast mean
                day_demand = daily_preds.get((site.site_id, item.item_id, day_str), 0.0)

                if curr_usable_qty >= day_demand:
                    curr_usable_qty -= day_demand
                    # Deplete batches with earliest expiry first
                    usable_active = sorted(
                        [b for b in sim_batches if b["qty"] > 0 and b["state"] == "USABLE"],
                        key=lambda x: x["expiry"],
                    )
                    rem_dem = day_demand
                    for b in usable_active:
                        take = min(b["qty"], rem_dem)
                        b["qty"] -= int(take)
                        rem_dem -= take
                        if rem_dem <= 0:
                            break
                else:
                    unmet = day_demand - curr_usable_qty
                    shortage_days += 1
                    unmet_qty += unmet
                    curr_usable_qty = 0.0
                    for b in sim_batches:
                        if b["state"] == "USABLE":
                            b["qty"] = 0

                # Physical stock includes usable + quarantined + damaged
                phys_stock = sum(b["qty"] for b in sim_batches if b["qty"] > 0)
                projected_physical[day_str] = phys_stock

            # 4. Replenishment Target & Raw Requirement
            # Determine target from P90 over W days or mean + buffer
            p90_w = agg_preds.get((site.site_id, item.item_id, w_site), 0.0)
            inbound_horizon = sum(o.qty_base for o in series_inbound if o.eta <= (cutoff_dt + timedelta(days=w_site)).isoformat())

            # Target calculation (rounded up to integer)
            policy_mode: Literal["quantile", "mean_plus_buffer"] = "quantile"
            target_int = int(np.ceil(p90_w))

            q_raw = max(0, target_int - allocatable_t0 - inbound_horizon)

            # 5. Storage Capacity Check on Arrival Date
            storage_cap = site.storage_capacity_base.get(item.item_id, 1000)
            phys_on_arrival = projected_physical.get(arrival_date_str, usable_t0)
            capacity_free = max(0, storage_cap - phys_on_arrival)

            split: list[ReplenishmentSplit] = []
            if q_raw <= capacity_free:
                proposed_qty = q_raw
                capacity_gap = 0
                if proposed_qty > 0:
                    split.append(ReplenishmentSplit(qty=proposed_qty, arrival=arrival_date_str))
            else:
                proposed_qty = capacity_free
                capacity_gap = q_raw - capacity_free
                if proposed_qty > 0:
                    split.append(ReplenishmentSplit(qty=proposed_qty, arrival=arrival_date_str))

                # Find first future day where capacity clears for the gap
                later_arrival = None
                for d in range(transit_days + 1, proj_days + 1):
                    check_dt = (cutoff_dt + timedelta(days=d)).isoformat()
                    future_free = storage_cap - projected_physical.get(check_dt, phys_on_arrival)
                    if future_free >= capacity_gap:
                        later_arrival = check_dt
                        break

                if later_arrival is None:
                    later_arrival = (cutoff_dt + timedelta(days=proj_days)).isoformat()

                if capacity_gap > 0:
                    split.append(ReplenishmentSplit(qty=capacity_gap, arrival=later_arrival))

            drafts.append(
                ReplenishmentDraft(
                    site=site.site_id,
                    item=item.item_id,
                    target=target_int,
                    allocatable=allocatable_t0,
                    inbound_in_horizon=inbound_horizon,
                    proposed_qty=proposed_qty,
                    capacity_free=capacity_free,
                    capacity_gap=capacity_gap,
                    split=split,
                    shortage_days_projected=shortage_days,
                    unmet_projected_qty=round(unmet_qty, 2),
                    expiry_waste_projected=expiry_waste,
                    policy_mode=policy_mode,
                    inputs_ref={
                        "snapshot_id": snapshot.snapshot_id,
                        "lead_window_days": w_site,
                        "arrival_date": arrival_date_str,
                        "storage_capacity": storage_cap,
                        "projected_physical_on_arrival": phys_on_arrival,
                    },
                )
            )

    return drafts
