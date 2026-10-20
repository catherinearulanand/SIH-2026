"""Uncertainty quantification via block-bootstrap sample paths for Setu Supply Track 2."""

from datetime import date, timedelta
import numpy as np
from setu.contracts import AggregatePrediction

RANGE_METHOD = "block-bootstrap residuals (uncalibrated scenario envelope)"


def generate_block_bootstrap_paths(
    fitted_mean: np.ndarray,
    residuals: np.ndarray,
    horizon: int,
    num_paths: int = 500,
    block_size: int = 7,
    rng: np.random.Generator | None = None,
) -> np.ndarray:
    """Generate future demand sample paths using block-bootstrap residuals.

    Parameters
    ----------
    fitted_mean : np.ndarray
        Array of length `horizon` with expected demand per day.
    residuals : np.ndarray
        In-sample residuals e_t = y_t - y_hat_t (1D array, NaN-free).
    horizon : int
        Number of days ahead.
    num_paths : int
        Number of bootstrap sample paths (default 500).
    block_size : int
        Length of consecutive residual blocks (default 7).
    rng : np.random.Generator | None
        Random generator for reproducibility.

    Returns
    -------
    np.ndarray
        Array of shape (num_paths, horizon) with non-negative simulated paths.
    """
    if rng is None:
        rng = np.random.default_rng(26251)

    clean_res = residuals[~np.isnan(residuals)]
    n_res = len(clean_res)

    if n_res == 0:
        # No residuals available; return flat mean paths
        return np.tile(fitted_mean, (num_paths, 1))

    paths = np.zeros((num_paths, horizon), dtype=float)

    if n_res < block_size:
        # Series too short for block-bootstrap; use simple iid bootstrap
        for b in range(num_paths):
            res_sample = rng.choice(clean_res, size=horizon, replace=True)
            paths[b] = np.maximum(0.0, fitted_mean + res_sample)
        return paths

    # Block bootstrap: extract overlapping blocks
    num_blocks_needed = int(np.ceil(horizon / block_size))
    max_start = n_res - block_size

    for b in range(num_paths):
        path_residuals = []
        for _ in range(num_blocks_needed):
            start_idx = rng.integers(0, max_start + 1)
            path_residuals.extend(clean_res[start_idx : start_idx + block_size])

        res_draw = np.array(path_residuals[:horizon], dtype=float)
        paths[b] = np.maximum(0.0, fitted_mean + res_draw)

    return paths


def compute_aggregate_quantiles(
    site_id: str,
    item_id: str,
    paths: np.ndarray,
    windows: list[int],
) -> list[AggregatePrediction]:
    """Compute P10, P50, and P90 of summed sample paths over specified windows.

    Aggregate quantiles are derived from summed sample paths across each window,
    NEVER by summing marginal daily P90s.
    """
    aggregates: list[AggregatePrediction] = []
    num_paths, horizon = paths.shape

    for w in sorted(set(windows)):
        if w > horizon:
            continue
        # Sum each sample path over the first w days
        path_sums = np.sum(paths[:, :w], axis=1)

        p10 = float(np.percentile(path_sums, 10))
        p50 = float(np.percentile(path_sums, 50))
        p90 = float(np.percentile(path_sums, 90))

        aggregates.append(
            AggregatePrediction(
                site_id=site_id,
                item_id=item_id,
                window_days=w,
                p10=round(p10, 2),
                p50=round(p50, 2),
                p90=round(p90, 2),
            )
        )

    return aggregates
