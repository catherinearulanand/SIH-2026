"""Paired supply simulation: Track 2 forecast order-up-to policy vs a fixed (s, S) rule at MATCHED average stock.

What is simulated, per (site, item) series, over `horizon_days` starting the day after the snapshot as-of date:
  * the same starting stock for both policies (usable, unexpired batches minus reservations), the same
    confirmed inbound orders, the same storage cap (quarantined/damaged goods still occupy space),
  * FEFO issue and expiry of the starting batches (expiry waste is counted),
  * a review every REVIEW_DAYS days; an order placed at review arrives `lead` days later (lead = W - R),
  * orders are truncated to the free storage space; replenishment lots are assumed long-dated (shelf life of
    the item), and supply from the external source is assumed unlimited.

Policies (both see only data up to the snapshot cutoff):
  * forecast_policy: order up to the Track 2 aggregate P90 over the site's L+R window (the same number the
    replenishment draft uses). Series with no forecast fall back to mean * W and are counted.
  * fixed_matched: order up to S = k * mean daily demand when the position drops to s = 0.4 * S, with k
    calibrated (on separate calibration paths) so its average stock equals the forecast policy's.
  * fixed_6d: the old arbitrary heuristic (k = 6 days of cover), shown only for transparency.

Demand paths are 7-day block bootstraps of each series' own history (common random numbers across policies),
plus - when the held-out truth is supplied - the actual future path. Missing days count as zero demand.
Supply fill-rate gains are only meaningful at matched stock, so the matched comparison is the headline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

from setu.contracts import ForecastRun, Snapshot

REVIEW_DAYS = 7
BLOCK = 7
FIXED_S_FRACTION = 0.4
UNMATCHED_K = 6.0
CALIBRATION_SEEDS = tuple(range(1000, 1010))
METRICS = ("fill_rate_pct", "unmet_qty", "shortage_days", "avg_stock", "peak_stock", "expiry_waste")


@dataclass
class Series:
    site: str
    item: str
    hist: np.ndarray                      # clean daily requested history (no NaN)
    mu: float
    lead: int
    cap: int
    other_phys: int                       # quarantined/damaged units that still occupy space
    shelf_days: int
    lots: list[list[int]]                 # [expiry_day, qty], earliest first
    inbound: list[tuple[int, int]]        # (arrival_day, qty)
    target: float                         # forecast aggregate P90 over the L+R window
    fallback: bool = False


def _day_index(d: str, origin: date) -> int:
    return (date.fromisoformat(d) - origin).days


def build_series(snapshot: Snapshot, fc_run: ForecastRun, site_windows: dict[str, int]) -> list[Series]:
    origin = date.fromisoformat(snapshot.as_of) + timedelta(days=1)  # day 0 of the simulation
    items = {i.item_id: i for i in snapshot.items}
    p90 = {(a.site_id, a.item_id, a.window_days): a.p90 for a in fc_run.aggregate}
    out: list[Series] = []
    for site in snapshot.sites:
        w = site_windows[site.site_id]
        for item in snapshot.items:
            key = (site.site_id, item.item_id)
            hist = np.array(
                [d.requested for d in snapshot.demand
                 if (d.site_id, d.item_id) == key and d.requested is not None and d.date <= snapshot.demand_cutoff],
                dtype=float,
            )
            mu = float(hist.mean()) if hist.size else 0.0
            lots = sorted(
                ([_day_index(b.expiry_date, origin), b.qty_base]
                 for b in snapshot.batches
                 if (b.site_id, b.item_id) == key and b.quality_state == "USABLE"
                 and _day_index(b.expiry_date, origin) >= 0),
                key=lambda x: x[0],
            )
            reserved = sum(r.qty_base for r in snapshot.reservations if (r.site_id, r.item_id) == key)
            for lot in lots:                       # reservations ship first (FEFO)
                take = min(lot[1], reserved)
                lot[1] -= take
                reserved -= take
            lots = [l for l in lots if l[1] > 0]
            other = sum(b.qty_base for b in snapshot.batches
                        if (b.site_id, b.item_id) == key and b.quality_state != "USABLE")
            target = p90.get((site.site_id, item.item_id, w))
            out.append(Series(
                site=site.site_id, item=item.item_id, hist=hist, mu=mu, lead=max(1, w - REVIEW_DAYS),
                cap=site.storage_capacity_base.get(item.item_id, 0), other_phys=other,
                shelf_days=items[item.item_id].min_shelf_days, lots=lots,
                inbound=[(_day_index(i.eta, origin), i.qty_base) for i in snapshot.inbound
                         if (i.site_id, i.item_id) == key and _day_index(i.eta, origin) >= 0],
                target=float(target) if target is not None else mu * w, fallback=target is None,
            ))
    return out


def bootstrap_path(hist: np.ndarray, horizon: int, rng: np.random.Generator) -> np.ndarray:
    if hist.size == 0:
        return np.zeros(horizon)
    n_blocks = -(-horizon // BLOCK)
    starts = rng.integers(0, max(1, hist.size - BLOCK + 1), size=n_blocks)
    return np.concatenate([hist[s:s + BLOCK] for s in starts])[:horizon]


def simulate_series(s: Series, demand: np.ndarray, policy: str, k: float = UNMATCHED_K) -> dict:
    """One series, one demand path, one policy. policy: 'forecast' or 'fixed' (uses k)."""
    lots = [list(l) for l in s.lots]
    pipeline = list(s.inbound)
    requested = issued = unmet = waste = 0.0
    shortage_days = 0
    stocks: list[float] = []
    for day in range(len(demand)):
        for arr in [p for p in pipeline if p[0] == day]:
            lots.append([day + s.shelf_days, arr[1]])
        pipeline = [p for p in pipeline if p[0] > day]
        lots.sort(key=lambda x: x[0])
        waste += sum(l[1] for l in lots if l[0] <= day)
        lots = [l for l in lots if l[0] > day]

        stock = sum(l[1] for l in lots)
        if day % REVIEW_DAYS == 0:
            position = stock + sum(q for _, q in pipeline)
            if policy == "forecast":
                order = max(0.0, s.target - position)
            else:
                big_s = k * s.mu
                order = max(0.0, big_s - position) if position <= FIXED_S_FRACTION * big_s else 0.0
            order = min(order, max(0, s.cap - s.other_phys - position))
            if int(order) > 0:
                pipeline.append((day + s.lead, int(order)))

        need = float(demand[day])
        requested += need
        left = need
        for l in lots:                                   # FEFO issue
            take = min(l[1], left)
            l[1] -= take
            left -= take
            if left <= 0:
                break
        lots = [l for l in lots if l[1] > 0]
        issued += need - left
        unmet += left
        shortage_days += left > 0
        stocks.append(float(sum(l[1] for l in lots)))
    return {"requested": requested, "issued": issued, "unmet": unmet, "shortage_days": shortage_days,
            "stocks": np.array(stocks), "waste": waste}


def _run(series: list[Series], paths: dict[tuple[str, str], np.ndarray], policy: str, k: float = UNMATCHED_K) -> dict:
    res = [simulate_series(s, paths[(s.site, s.item)], policy, k) for s in series]
    daily_total = np.sum([r["stocks"] for r in res], axis=0)
    req = sum(r["requested"] for r in res)
    return {
        "fill_rate_pct": 100.0 * sum(r["issued"] for r in res) / req if req > 0 else 100.0,
        "unmet_qty": sum(r["unmet"] for r in res),
        "shortage_days": float(sum(r["shortage_days"] for r in res)),
        "avg_stock": float(daily_total.mean()),
        "peak_stock": float(daily_total.max()),
        "expiry_waste": sum(r["waste"] for r in res),
    }


def _paths(series: list[Series], seed: int, horizon: int) -> dict[tuple[str, str], np.ndarray]:
    return {(s.site, s.item): bootstrap_path(s.hist, horizon, np.random.default_rng([seed, i]))
            for i, s in enumerate(series)}


def calibrate_k(series: list[Series], horizon: int, tol: float = 0.01) -> float:
    """Find k so the fixed rule's mean stock matches the forecast policy's on separate calibration paths."""
    cal = [_paths(series, sd, horizon) for sd in CALIBRATION_SEEDS]
    goal = float(np.mean([_run(series, p, "forecast")["avg_stock"] for p in cal]))
    lo, hi = 0.1, 80.0
    for _ in range(30):
        mid = (lo + hi) / 2
        got = float(np.mean([_run(series, p, "fixed", mid)["avg_stock"] for p in cal]))
        if abs(got - goal) <= tol * max(goal, 1.0):
            return mid
        lo, hi = (mid, hi) if got < goal else (lo, mid)
    return (lo + hi) / 2


def _mean(rows: list[dict]) -> dict:
    return {m: round(float(np.mean([r[m] for r in rows])), 2) for m in METRICS}


def _paired(a: list[dict], b: list[dict]) -> dict:
    out = {}
    for m in METRICS:
        d = np.array([x[m] - y[m] for x, y in zip(a, b)])
        half = 1.96 * d.std(ddof=1) / np.sqrt(len(d)) if len(d) > 1 else float("nan")
        out[m] = {"mean": round(float(d.mean()), 2), "ci95": [round(float(d.mean() - half), 2), round(float(d.mean() + half), 2)]}
    return out


def run_paired_simulation(
    snapshot: Snapshot, fc_run: ForecastRun, site_windows: dict[str, int],
    truth: dict[tuple[str, str], np.ndarray] | None = None, num_seeds: int = 20, horizon_days: int = 30,
) -> dict:
    series = build_series(snapshot, fc_run, site_windows)
    k = calibrate_k(series, horizon_days)
    boot = [_paths(series, sd, horizon_days) for sd in range(num_seeds)]
    f = [_run(series, p, "forecast") for p in boot]
    m = [_run(series, p, "fixed", k) for p in boot]
    u = [_run(series, p, "fixed", UNMATCHED_K) for p in boot]
    out = {
        "assumptions": {
            "horizon_days": horizon_days, "review_days": REVIEW_DAYS, "series": len(series),
            "forecast_fallback_series": sum(s.fallback for s in series),
            "fixed_rule": f"S = k*mean daily demand, s = {FIXED_S_FRACTION}*S; matched k = {k:.2f} days of cover",
            "demand": "7-day block bootstrap of each series' history; missing days = 0; common random numbers",
            "supply": "external source unlimited; orders truncated to free storage; replenishment lots long-dated",
            "start_stock": "usable unexpired batches minus reservations, plus confirmed inbound (both policies)",
        },
        "bootstrap": {
            "n_paths": num_seeds,
            "forecast_policy": _mean(f), "fixed_matched": _mean(m), "fixed_6d_unmatched": _mean(u),
            "paired_forecast_minus_fixed_matched": _paired(f, m),
        },
    }
    if truth is not None:
        actual = {key: np.nan_to_num(arr[:horizon_days], nan=0.0) for key, arr in truth.items()}
        actual = {(s.site, s.item): actual.get((s.site, s.item), np.zeros(horizon_days)) for s in series}
        out["actual_holdout"] = {
            "forecast_policy": {m_: round(v, 2) for m_, v in _run(series, actual, "forecast").items()},
            "fixed_matched": {m_: round(v, 2) for m_, v in _run(series, actual, "fixed", k).items()},
            "fixed_6d_unmatched": {m_: round(v, 2) for m_, v in _run(series, actual, "fixed", UNMATCHED_K).items()},
            "note": "single realised path; no confidence interval",
        }
    return out
