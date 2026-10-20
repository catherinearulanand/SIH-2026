"""Pure NumPy baseline forecasting models for Setu Supply Track 2."""

import numpy as np


def seasonal_naive(series: np.ndarray, horizon: int, season: int = 7) -> np.ndarray:
    """Seasonal naive forecast repeating the last seasonal cycle.

    Parameters
    ----------
    series : np.ndarray
        Historical observations (1D array, NaN-free).
    horizon : int
        Number of steps ahead to forecast.
    season : int
        Seasonal period length (default 7 for weekly seasonality).

    Returns
    -------
    np.ndarray
        Array of length `horizon` with seasonal forecast values.
    """
    clean = series[~np.isnan(series)]
    if len(clean) == 0:
        return np.zeros(horizon, dtype=float)

    if len(clean) < season:
        # Not enough history for full cycle; repeat available clean values
        reps = int(np.ceil(horizon / len(clean)))
        forecast = np.tile(clean, reps)[:horizon]
    else:
        last_cycle = clean[-season:]
        reps = int(np.ceil(horizon / season))
        forecast = np.tile(last_cycle, reps)[:horizon]

    return np.maximum(0.0, forecast.astype(float))


def ewma(series: np.ndarray, horizon: int, alpha: float = 0.2) -> np.ndarray:
    """Exponentially Weighted Moving Average (EWMA) point forecast.

    Forecast across the horizon is a flat line at the final smoothed level.

    Parameters
    ----------
    series : np.ndarray
        Historical observations (1D array).
    horizon : int
        Number of steps ahead.
    alpha : float
        Smoothing factor in (0, 1].

    Returns
    -------
    np.ndarray
        Array of length `horizon` with the smoothed forecast level.
    """
    clean = series[~np.isnan(series)]
    if len(clean) == 0:
        return np.zeros(horizon, dtype=float)

    level = float(clean[0])
    for val in clean[1:]:
        level = alpha * float(val) + (1.0 - alpha) * level

    level = max(0.0, level)
    return np.full(horizon, level, dtype=float)


def croston_sba(series: np.ndarray, horizon: int, alpha: float = 0.1) -> np.ndarray:
    """Syntetos-Boylan Approximation (SBA) of Croston's intermittent demand method.

    Parameters
    ----------
    series : np.ndarray
        Historical observations (1D array).
    horizon : int
        Forecast horizon.
    alpha : float
        Smoothing factor for demand size and inter-arrival intervals.

    Returns
    -------
    np.ndarray
        Array of length `horizon` with flat expected demand rate.
    """
    clean = series[~np.isnan(series)]
    nonzeros = np.where(clean > 0)[0]

    if len(nonzeros) == 0:
        return np.zeros(horizon, dtype=float)

    if len(nonzeros) == 1:
        rate = float(clean[nonzeros[0]]) / len(clean)
        return np.full(horizon, max(0.0, rate), dtype=float)

    # Initial estimates
    z = float(clean[nonzeros[0]])  # demand size
    p = 1.0  # inter-arrival interval
    t_prev = nonzeros[0]

    for t in nonzeros[1:]:
        interval = float(t - t_prev)
        size = float(clean[t])
        z = alpha * size + (1.0 - alpha) * z
        p = alpha * interval + (1.0 - alpha) * p
        t_prev = t

    # Syntetos-Boylan debiasing factor (1 - alpha/2)
    sba_factor = 1.0 - (alpha / 2.0)
    rate = max(0.0, (z / p) * sba_factor) if p > 0 else 0.0

    return np.full(horizon, rate, dtype=float)


def pooled_fallback(
    all_series: dict[tuple[str, str], np.ndarray],
    target_site: str,
    target_item: str,
    horizon: int,
) -> np.ndarray:
    """Pooled item-rate fallback scaled by site activity share.

    Parameters
    ----------
    all_series : dict[tuple[str, str], np.ndarray]
        Mapping from (site_id, item_id) to historical 1D demand array.
    target_site : str
        Site requiring fallback.
    target_item : str
        Item requiring fallback.
    horizon : int
        Forecast horizon.

    Returns
    -------
    np.ndarray
        Flat forecast array across horizon.
    """
    # 1. Item-average rate across all sites
    item_rates = []
    for (s_id, i_id), vals in all_series.items():
        if i_id == target_item:
            clean = vals[~np.isnan(vals)]
            if len(clean) > 0:
                item_rates.append(float(np.mean(clean)))

    item_mean = float(np.mean(item_rates)) if item_rates else 0.0

    # 2. Site activity share across all items
    site_total = 0.0
    all_total = 0.0
    for (s_id, i_id), vals in all_series.items():
        clean = vals[~np.isnan(vals)]
        total = float(np.sum(clean)) if len(clean) > 0 else 0.0
        all_total += total
        if s_id == target_site:
            site_total += total

    # Relative site activity ratio (normalized to ~1.0 on balanced network)
    num_sites = len({s for s, _ in all_series.keys()}) or 1
    site_share = (site_total / all_total * num_sites) if all_total > 0 else 1.0

    rate = max(0.0, item_mean * site_share)
    return np.full(horizon, rate, dtype=float)
