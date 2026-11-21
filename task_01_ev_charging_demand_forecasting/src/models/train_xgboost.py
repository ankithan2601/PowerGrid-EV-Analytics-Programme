"""Recursive supervised XGBoost forecasting with lag and calendar features."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
from xgboost import XGBRegressor

from forecasting_utils import xgb_features_for_date


def _hourly_features(
    history: pd.Series | np.ndarray,
    timestamp: pd.Timestamp,
    active_chargers: int,
) -> dict[str, float]:
    values = (
        history.to_numpy(dtype=float)
        if isinstance(history, pd.Series)
        else np.asarray(history, dtype=float)
    )
    if len(values) < 336:
        raise ValueError("At least 336 historical hourly values are required.")
    features: dict[str, float] = {
        f"lag_{lag}": float(values[-lag]) for lag in (1, 24, 168, 336)
    }
    for window in (24, 168):
        rolling_values = values[-window:]
        features[f"rolling_mean_{window}"] = float(rolling_values.mean())
        features[f"rolling_std_{window}"] = float(rolling_values.std(ddof=1))
    dow = timestamp.dayofweek
    hour = timestamp.hour
    day_of_year = timestamp.dayofyear
    features.update(
        {
            "hour_sin": float(math.sin(2 * math.pi * hour / 24)),
            "hour_cos": float(math.cos(2 * math.pi * hour / 24)),
            "dow_sin": float(math.sin(2 * math.pi * dow / 7)),
            "dow_cos": float(math.cos(2 * math.pi * dow / 7)),
            "doy_sin": float(math.sin(2 * math.pi * day_of_year / 365.25)),
            "doy_cos": float(math.cos(2 * math.pi * day_of_year / 365.25)),
            "is_weekend": float(dow >= 5),
            "active_chargers": float(active_chargers),
        }
    )
    return features


def _training_features(frame: pd.DataFrame, frequency: str) -> pd.DataFrame:
    if frequency == "h":
        lookback = 336
        feature_builder = _hourly_features
    else:
        lookback = 28
        feature_builder = xgb_features_for_date
    rows = []
    values = frame["energy_kwh"].to_numpy(dtype=float)
    for position in range(lookback, len(frame)):
        row = feature_builder(
            values[:position] if frequency == "h" else frame["energy_kwh"].iloc[:position],
            frame.index[position],
            int(frame["active_chargers"].iloc[position]),
        )
        rows.append(row)
    return pd.DataFrame(rows, index=frame.index[lookback:])


def fit_predict(
    train: pd.DataFrame,
    future: pd.DataFrame,
    model_path: Path | None = None,
    frequency: str = "D",
) -> pd.Series:
    lookback = 336 if frequency == "h" else 28
    if len(train) <= lookback:
        raise ValueError(
            f"XGBoost requires more than {lookback} {frequency!r} training observations."
        )
    features = _training_features(train, frequency)
    target = train.loc[features.index, "energy_kwh"].astype(float)
    model = XGBRegressor(
        objective="reg:squarederror",
        n_estimators=500,
        max_depth=4,
        learning_rate=0.03,
        subsample=0.9,
        colsample_bytree=0.9,
        reg_lambda=5.0,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(features, target)
    if model_path is not None:
        model_path.parent.mkdir(parents=True, exist_ok=True)
        model.save_model(model_path)

    history = train["energy_kwh"].astype(float).copy()
    predictions: list[float] = []
    for date, row in future.iterrows():
        feature_builder = _hourly_features if frequency == "h" else xgb_features_for_date
        feature = feature_builder(history, date, int(row["active_chargers"]))
        prediction = max(0.0, float(model.predict(pd.DataFrame([feature]))[0]))
        predictions.append(prediction)
        history.loc[date] = prediction
    return pd.Series(predictions, index=future.index, name="yhat")
