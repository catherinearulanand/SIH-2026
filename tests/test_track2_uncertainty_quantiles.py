"""Test 3: Aggregate quantiles come from summed sample paths, proving sum(daily P90) > aggregate P90."""

import numpy as np
from setu.forecast.uncertainty import compute_aggregate_quantiles, generate_block_bootstrap_paths


def test_aggregate_p90_strictly_less_than_sum_of_daily_p90s():
    """Under independent errors, the sum of daily 90th percentiles strictly overestimates

    the variance of the multi-day aggregate lead-time demand:
        sum_{t=1}^W Daily_P90_t > Aggregate_P90_W
    """
    rng = np.random.default_rng(26251)
    horizon = 14
    window = 10
    num_paths = 2000

    fitted_mean = np.full(horizon, 50.0, dtype=float)
    # i.i.d. zero-mean normal residuals
    residuals = rng.normal(0.0, 10.0, size=100)

    paths = generate_block_bootstrap_paths(
        fitted_mean=fitted_mean,
        residuals=residuals,
        horizon=horizon,
        num_paths=num_paths,
        block_size=1,  # i.i.d draws
        rng=rng,
    )

    # 1. Marginal daily P90s
    daily_p90s = [float(np.percentile(paths[:, t], 90)) for t in range(window)]
    sum_of_daily_p90s = sum(daily_p90s)

    # 2. True aggregate P90 from summed sample paths
    aggs = compute_aggregate_quantiles("TEST-SITE", "TEST-ITEM", paths, windows=[window])
    aggregate_p90 = aggs[0].p90

    # Theoretical check:
    # Expected sum = 50 * 10 = 500
    # Sum of daily P90s = 10 * (50 + 1.2815 * 10) = 628.15
    # Aggregate P90 = 500 + 1.2815 * sqrt(10) * 10 = 500 + 40.52 = 540.52
    # 628.15 > 540.52
    assert sum_of_daily_p90s > aggregate_p90
    difference = sum_of_daily_p90s - aggregate_p90
    assert difference > 40.0, f"Expected substantial difference, got {difference}"
