"""Prophet forecasting with weekly/yearly seasonality and UK holidays."""

from __future__ import annotations

import json
from pathlib import Path

import holidays
import pandas as pd
from prophet import Prophet
from prophet.serialize import model_to_json


def _holiday_frame(years: set[int]) -> pd.DataFrame:
    calendar = holidays.country_holidays("GB", years=years)
    rows = [{"ds": pd.Timestamp(day), "holiday": str(name)} for day, name in calendar.items()]
    return pd.DataFrame(rows)


def fit_predict(
    train: pd.DataFrame,
    future: pd.DataFrame,
    model_path: Path | None = None,
    frequency: str = "D",
) -> pd.Series:
    years = set(train.index.year).union(future.index.year)
    model = Prophet(
        weekly_seasonality=True,
        yearly_seasonality=True,
        daily_seasonality=frequency == "h",
        holidays=_holiday_frame(years),
        interval_width=0.95,
        uncertainty_samples=1000,
    )
    prophet_train = pd.DataFrame(
        {
            "ds": train.index,
            "y": train["energy_kwh"].to_numpy(dtype=float),
            "active_chargers": train["active_chargers"].to_numpy(dtype=float) / 199.0,
        }
    )
    model.add_regressor("active_chargers", standardize=False)
    model.fit(prophet_train)
    if model_path is not None:
        model_path.parent.mkdir(parents=True, exist_ok=True)
        model_path.write_text(model_to_json(model), encoding="utf-8")
    future_frame = pd.DataFrame(
        {
            "ds": future.index,
            "active_chargers": future["active_chargers"].to_numpy(dtype=float) / 199.0,
        }
    )
    prediction = model.predict(future_frame)
    return pd.Series(
        prediction["yhat"].clip(lower=0).to_numpy(),
        index=future.index,
        name="yhat",
    )
