"""Shared data loading, calendar, feature, and metric utilities."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import holidays


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DAILY_PATH = PROJECT_ROOT / "data" / "processed" / "daily_demand.csv"
HOURLY_PATH = PROJECT_ROOT / "data" / "processed" / "hourly_demand.csv"
TRAIN_END = pd.Timestamp("2024-09-30")
TEST_START = pd.Timestamp("2024-10-01")
TEST_END = pd.Timestamp("2024-12-31")
FORECAST_START = pd.Timestamp("2025-01-01")
FORECAST_END = pd.Timestamp("2025-12-31")


def load_daily(path: Path = DAILY_PATH) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"Daily dataset not found: {path}")
    frame = pd.read_csv(path, parse_dates=["date"]).sort_values("date")
    required = {"date", "energy_kwh", "active_chargers"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Daily dataset missing columns: {', '.join(sorted(missing))}")
    if frame["date"].duplicated().any() or not frame["date"].is_monotonic_increasing:
        raise ValueError("Daily dataset dates must be unique and chronological.")
    if frame["energy_kwh"].isna().any() or frame["active_chargers"].isna().any():
        raise ValueError("Daily target and active_chargers must not contain nulls.")
    return frame.set_index("date")


def make_future_frame(
    index: pd.DatetimeIndex,
    active_chargers: int = 199,
    active_stations: int = 33,
) -> pd.DataFrame:
    uk_holidays = holidays.country_holidays(
        "GB", years=range(index.min().year, index.max().year + 1)
    )
    return pd.DataFrame(
        {
            "active_chargers": active_chargers,
            "active_stations": active_stations,
            "day_of_week": index.dayofweek,
            "is_weekend": (index.dayofweek >= 5).astype("int8"),
            "month": index.month,
            "quarter": index.quarter,
            "year": index.year,
            "is_uk_bank_holiday": [
                int(day.date() in uk_holidays) for day in index
            ],
        },
        index=index,
    )


def xgb_features_for_date(
    history: pd.Series, date: pd.Timestamp, active_chargers: int
) -> dict[str, float]:
    values = history.to_numpy(dtype=float)
    if len(values) < 28:
        raise ValueError("At least 28 historical values are required for XGBoost.")
    features: dict[str, float] = {
        f"lag_{lag}": float(values[-lag]) for lag in (1, 7, 14, 28)
    }
    for window in (7, 28):
        rolling_values = values[-window:]
        features[f"rolling_mean_{window}"] = float(rolling_values.mean())
        features[f"rolling_std_{window}"] = float(rolling_values.std(ddof=1))
    dow = date.dayofweek
    month = date.month
    day_of_year = date.dayofyear
    features.update(
        {
            "dow_sin": float(np.sin(2 * np.pi * dow / 7)),
            "dow_cos": float(np.cos(2 * np.pi * dow / 7)),
            "month_sin": float(np.sin(2 * np.pi * (month - 1) / 12)),
            "month_cos": float(np.cos(2 * np.pi * (month - 1) / 12)),
            "doy_sin": float(np.sin(2 * np.pi * (day_of_year - 1) / 365.25)),
            "doy_cos": float(np.cos(2 * np.pi * (day_of_year - 1) / 365.25)),
            "is_weekend": float(dow >= 5),
            "active_chargers": float(active_chargers),
        }
    )
    return features


def metric_values(actual: pd.Series, predicted: pd.Series) -> dict[str, float]:
    joined = pd.concat(
        [actual.rename("actual"), predicted.rename("predicted")], axis=1
    ).dropna()
    if joined.empty:
        raise ValueError("Cannot calculate metrics without paired actual/predicted data.")
    nonzero = joined["actual"] != 0
    mape = (
        float(
            (
                (joined.loc[nonzero, "actual"] - joined.loc[nonzero, "predicted"]).abs()
                / joined.loc[nonzero, "actual"].abs()
            ).mean()
            * 100
        )
        if nonzero.any()
        else float("nan")
    )
    errors = joined["predicted"] - joined["actual"]
    return {
        "mape_pct": mape,
        "rmse_kwh": float(np.sqrt(np.mean(np.square(errors)))),
        "mae_kwh": float(np.mean(np.abs(errors))),
    }


def calibrated_intervals(
    point_forecast: pd.Series, absolute_holdout_errors: np.ndarray
) -> pd.DataFrame:
    """Create empirical symmetric intervals from chronological holdout errors."""
    errors = np.asarray(absolute_holdout_errors, dtype=float)
    errors = errors[np.isfinite(errors)]
    if errors.size == 0:
        raise ValueError("Holdout errors are required to calibrate forecast intervals.")
    q80, q95 = np.quantile(errors, [0.80, 0.95])
    return pd.DataFrame(
        {
            "yhat": point_forecast.clip(lower=0),
            "lower_80": (point_forecast - q80).clip(lower=0),
            "upper_80": point_forecast + q80,
            "lower_95": (point_forecast - q95).clip(lower=0),
            "upper_95": point_forecast + q95,
        },
        index=point_forecast.index,
    )
