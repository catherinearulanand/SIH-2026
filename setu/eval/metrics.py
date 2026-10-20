"""Evaluation metrics for Setu Supply Track 2 forecasting and planning."""

import numpy as np


def mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Mean Absolute Error."""
    t = np.asarray(y_true, dtype=float)
    p = np.asarray(y_pred, dtype=float)
    mask = ~np.isnan(t) & ~np.isnan(p)
    if not np.any(mask):
        return 0.0
    return float(np.mean(np.abs(t[mask] - p[mask])))


def bias(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Mean signed forecast bias (pred - actual). Positive = overforecast."""
    t = np.asarray(y_true, dtype=float)
    p = np.asarray(y_pred, dtype=float)
    mask = ~np.isnan(t) & ~np.isnan(p)
    if not np.any(mask):
        return 0.0
    return float(np.mean(p[mask] - t[mask]))


def wape(y_true: np.ndarray, y_pred: np.ndarray) -> float | None:
    """Weighted Absolute Percentage Error (sum(|actual - pred|) / sum(actual)).

    Returns None when sum of actuals is zero.
    """
    t = np.asarray(y_true, dtype=float)
    p = np.asarray(y_pred, dtype=float)
    mask = ~np.isnan(t) & ~np.isnan(p)
    if not np.any(mask):
        return None
    actual_sum = float(np.sum(t[mask]))
    if actual_sum <= 0.0:
        return None
    abs_err_sum = float(np.sum(np.abs(t[mask] - p[mask])))
    return float(abs_err_sum / actual_sum)


def pinball_loss(y_true: np.ndarray, y_pred_q: np.ndarray, tau: float) -> float:
    """Pinball loss for quantile tau in (0, 1)."""
    t = np.asarray(y_true, dtype=float)
    q = np.asarray(y_pred_q, dtype=float)
    mask = ~np.isnan(t) & ~np.isnan(q)
    if not np.any(mask):
        return 0.0
    diff = t[mask] - q[mask]
    loss = np.maximum(tau * diff, (tau - 1.0) * diff)
    return float(np.mean(loss))


def empirical_coverage(y_true: np.ndarray, y_pred_q: np.ndarray) -> float:
    """Fraction of actual values falling at or below the quantile prediction."""
    t = np.asarray(y_true, dtype=float)
    q = np.asarray(y_pred_q, dtype=float)
    mask = ~np.isnan(t) & ~np.isnan(q)
    if not np.any(mask):
        return 0.0
    covered = np.sum(t[mask] <= q[mask])
    return float(covered / np.sum(mask))
