"""Weekly seasonal SARIMAX forecasting."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from statsmodels.tsa.statespace.sarimax import SARIMAX


def fit_predict(
    train: pd.DataFrame,
    future: pd.DataFrame,
    model_path: Path | None = None,
    seasonal_period: int = 7,
) -> pd.Series:
    """Fit SARIMAX with active chargers as an exogenous regressor."""
    train_exog = train[["active_chargers"]].astype(float) / 199.0
    future_exog = future[["active_chargers"]].astype(float) / 199.0
    model = SARIMAX(
        train["energy_kwh"].astype(float),
        exog=train_exog,
        order=(1, 1, 1),
        seasonal_order=(1, 1, 1, seasonal_period),
        enforce_stationarity=False,
        enforce_invertibility=False,
        simple_differencing=False,
    )
    fitted = model.fit(disp=False, maxiter=100)
    if model_path is not None:
        model_path.parent.mkdir(parents=True, exist_ok=True)
        fitted.save(model_path)
    prediction = fitted.get_forecast(steps=len(future), exog=future_exog).predicted_mean
    prediction.index = future.index
    prediction.name = "yhat"
    return prediction.clip(lower=0)
