"""Per-series forecast routing and method selection for Setu Supply Track 2."""

from typing import Any
import numpy as np
from setu.forecast.baselines import croston_sba, ewma, pooled_fallback, seasonal_naive


def compute_lag_autocorr(series: np.ndarray, lag: int = 7) -> float:
    """Compute lag autocorrelation on clean observations."""
    clean = series[~np.isnan(series)]
    if len(clean) <= lag + 2:
        return 0.0

    y = clean - np.mean(clean)
    denom = float(np.sum(y**2))
    if denom == 0.0:
        return 0.0

    num = float(np.sum(y[lag:] * y[:-lag]))
    return num / denom


def tune_ewma_alpha(
    train_series: np.ndarray,
    candidate_alphas: list[float] | None = None,
    val_steps: int = 14,
) -> float:
    """Select best alpha for EWMA based on rolling one-step-ahead MSE."""
    if candidate_alphas is None:
        candidate_alphas = [0.1, 0.2, 0.3, 0.5]

    clean = train_series[~np.isnan(train_series)]
    if len(clean) < val_steps + 5:
        return 0.2

    best_alpha = 0.2
    best_mse = float("inf")

    split_idx = max(5, len(clean) - val_steps)
    init_train = clean[:split_idx]
    val_actuals = clean[split_idx:]

    for a in candidate_alphas:
        level = float(init_train[0])
        for v in init_train[1:]:
            level = a * float(v) + (1.0 - a) * level

        sq_errs = []
        for act in val_actuals:
            sq_errs.append((float(act) - level) ** 2)
            level = a * float(act) + (1.0 - a) * level

        mse = float(np.mean(sq_errs)) if sq_errs else float("inf")
        if mse < best_mse:
            best_mse = mse
            best_alpha = a

    return best_alpha


def route_and_fit_series(
    site_id: str,
    item_id: str,
    series: np.ndarray,
    all_series: dict[tuple[str, str], np.ndarray],
    horizon: int,
    use_croston: bool = False,
) -> tuple[np.ndarray, str, list[str], bool]:
    """Route and fit a single (site_id, item_id) series.

    Returns
    -------
    tuple[np.ndarray, str, list[str], bool]
        (forecast_array, method_name, warnings, is_low_evidence)
    """
    warnings: list[str] = []
    low_evidence = False

    try:
        clean = series[~np.isnan(series)]
        num_obs = len(clean)
        num_nonzeros = int(np.sum(clean > 0))
        nonzero_rate = (num_nonzeros / num_obs) if num_obs > 0 else 0.0

        # Rule 1: Low evidence check (<28 valid obs or <20% nonzero)
        if num_obs < 28 or nonzero_rate < 0.20:
            low_evidence = True
            warnings.append(
                f"Series ({site_id}, {item_id}) has low evidence "
                f"({num_obs} valid obs, {nonzero_rate:.1%} nonzero); using pooled_fallback."
            )
            fc = pooled_fallback(all_series, site_id, item_id, horizon)
            return fc, "pooled_fallback", warnings, low_evidence

        # Rule 2: Intermittent demand (20% to 60% nonzero)
        if nonzero_rate < 0.60:
            if use_croston:
                fc = croston_sba(clean, horizon)
                return fc, "croston_sba", warnings, low_evidence
            else:
                warnings.append(
                    f"Series ({site_id}, {item_id}) exhibits intermittent demand "
                    f"({nonzero_rate:.1%} nonzero); using EWMA with intermittent warning flag."
                )
                fc = ewma(clean, horizon, alpha=0.1)
                return fc, "ewma_intermittent", warnings, low_evidence

        # Rule 3: Weekly seasonality (lag-7 autocorr > 0.3 with >= 14 obs)
        if num_obs >= 14:
            ac7 = compute_lag_autocorr(clean, lag=7)
            if ac7 > 0.30:
                fc = seasonal_naive(clean, horizon, season=7)
                return fc, "seasonal_naive_7", warnings, low_evidence

        # Rule 4: Standard continuous demand -> tuned EWMA
        best_alpha = tune_ewma_alpha(clean, candidate_alphas=[0.1, 0.2, 0.3, 0.5])
        fc = ewma(clean, horizon, alpha=best_alpha)
        return fc, f"ewma_alpha_{best_alpha}", warnings, low_evidence

    except Exception as exc:
        # Robust fallback: on any exception, fall back to pooled rate
        warnings.append(
            f"Series ({site_id}, {item_id}) fit encountered error: {exc!s}; fell back to pooled_fallback."
        )
        try:
            fc = pooled_fallback(all_series, site_id, item_id, horizon)
            return fc, "pooled_fallback", warnings, True
        except Exception as inner_exc:
            # Last fallback: return zero forecast, warning, never 500
            warnings.append(
                f"Pooled fallback also failed for ({site_id}, {item_id}): {inner_exc!s}; returning zero forecast."
            )
            return np.zeros(horizon, dtype=float), "omitted_fallback", warnings, True
