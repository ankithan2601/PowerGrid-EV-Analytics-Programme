"""Evaluate daily demand models and export forecasts and Power BI facts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from forecasting_utils import (
    DAILY_PATH,
    FORECAST_END,
    FORECAST_START,
    TEST_END,
    TEST_START,
    TRAIN_END,
    calibrated_intervals,
    load_daily,
    make_future_frame,
    metric_values,
)
from forecast_exports import export_task_forecasts
from models.train_prophet import fit_predict as prophet_predict
from models.train_sarima import fit_predict as sarima_predict
from models.train_xgboost import fit_predict as xgboost_predict


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_WORKBOOK = PROJECT_ROOT / "data" / "raw" / "ev_charging_dataset.xlsx"
METRICS_DIR = PROJECT_ROOT / "outputs" / "metrics"
FIGURES_DIR = PROJECT_ROOT / "outputs" / "figures"
FORECASTS_DIR = PROJECT_ROOT / "outputs" / "forecasts"
POWERBI_DIR = PROJECT_ROOT / "outputs" / "powerbi_data"
MODELS_DIR = PROJECT_ROOT / "outputs" / "models"

MODELS = {
    "SARIMAX": sarima_predict,
    "Prophet": prophet_predict,
    "XGBoost": xgboost_predict,
}


def _export_powerbi(
    daily: pd.DataFrame,
    forecast_rows: pd.DataFrame,
    metrics: pd.DataFrame,
    hourly_forecasts: pd.DataFrame,
) -> None:
    POWERBI_DIR.mkdir(parents=True, exist_ok=True)
    historical = daily.reset_index().rename(columns={"date": "date"})
    historical.to_csv(POWERBI_DIR / "fact_historical_daily.csv", index=False)
    forecast_rows.to_csv(POWERBI_DIR / "fact_forecast_daily.csv", index=False)
    metrics.to_csv(POWERBI_DIR / "model_metrics.csv", index=False)

    hourly_path = PROJECT_ROOT / "data" / "processed" / "hourly_demand.csv"
    hourly = pd.read_csv(hourly_path, parse_dates=["timestamp"])
    hourly["date"] = hourly["timestamp"].dt.normalize()
    hourly["hour"] = hourly["timestamp"].dt.hour
    hourly["day_of_week"] = hourly["timestamp"].dt.dayofweek
    hourly["is_weekend"] = (hourly["day_of_week"] >= 5).astype("int8")
    hourly.to_csv(POWERBI_DIR / "fact_hourly_profile.csv", index=False)
    hourly_forecasts.to_csv(
        POWERBI_DIR / "fact_hourly_forecast.csv", index=False
    )

    segmented_path = PROJECT_ROOT / "data" / "processed" / "daily_demand_segmented.csv"
    segmented = pd.read_csv(segmented_path, parse_dates=["date"])
    segmented.to_csv(POWERBI_DIR / "fact_historical_segmented.csv", index=False)

    sessions = pd.read_excel(
        RAW_WORKBOOK,
        sheet_name="sessions",
        usecols=[
            "station_id",
            "charger_id",
            "charger_type",
            "start_timestamp",
            "energy_kwh",
            "session_id",
        ],
        engine="openpyxl",
    )
    sessions["date"] = pd.to_datetime(sessions["start_timestamp"]).dt.normalize()
    station_fact = (
        sessions.groupby(["date", "station_id"], as_index=False)
        .agg(energy_kwh=("energy_kwh", "sum"), session_count=("session_id", "size"))
    )
    station_fact.to_csv(POWERBI_DIR / "fact_station_daily.csv", index=False)

    chargers = pd.read_excel(
        RAW_WORKBOOK,
        sheet_name="chargers",
        usecols=["charger_id", "charger_type", "max_power_kW", "installation_date"],
        engine="openpyxl",
    )
    chargers["installation_date"] = pd.to_datetime(chargers["installation_date"])
    charger_types = sorted(chargers["charger_type"].unique())
    charger_dim = (
        chargers.groupby("charger_type", as_index=False)
        .agg(
            charger_count=("charger_id", "nunique"),
            max_power_kW=("max_power_kW", "max"),
        )
        .rename(columns={"charger_type": "charger_type"})
    )
    charger_dim.to_csv(POWERBI_DIR / "dim_charger_types.csv", index=False)

    daily_dates = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    charger_fact = (
        sessions.assign(date=sessions["date"])
        .groupby(["date", "charger_type"], as_index=False)
        .agg(energy_kwh=("energy_kwh", "sum"), session_count=("session_id", "size"))
    )
    full_charger_index = pd.MultiIndex.from_product(
        [daily_dates, charger_types], names=["date", "charger_type"]
    )
    charger_fact = charger_fact.set_index(["date", "charger_type"]).reindex(
        full_charger_index
    )
    charger_fact[["energy_kwh", "session_count"]] = charger_fact[
        ["energy_kwh", "session_count"]
    ].fillna(0)
    charger_fact["session_count"] = charger_fact["session_count"].astype("int64")
    active_by_type = []
    for day, charger_type in full_charger_index:
        annual_additions = (
            chargers.loc[chargers["charger_type"] == charger_type]
            .groupby(chargers["installation_date"].dt.year)
            .size()
            .sort_index()
        )
        annual_capacity = annual_additions.cumsum()
        years = annual_capacity.index.to_numpy(dtype=int)
        positions = np.searchsorted(years, day.year, side="right") - 1
        active_by_type.append(
            int(annual_capacity.iloc[positions]) if positions >= 0 else 0
        )
    charger_fact["active_chargers"] = active_by_type
    charger_fact.reset_index().to_csv(
        POWERBI_DIR / "fact_charger_type_daily.csv", index=False
    )

    stations = pd.read_excel(
        RAW_WORKBOOK, sheet_name="stations", engine="openpyxl"
    )
    stations.to_csv(POWERBI_DIR / "dim_stations.csv", index=False)

    calendar = pd.date_range(daily.index.min(), FORECAST_END, freq="D", name="date")
    date_dim = make_future_frame(calendar).reset_index()
    date_dim = date_dim.drop(columns=["active_stations", "active_chargers"])
    historical_capacity = daily[
        ["active_stations", "active_chargers"]
    ].reset_index()
    date_dim = date_dim.merge(historical_capacity, on="date", how="left")
    date_dim["active_stations"] = date_dim["active_stations"].fillna(33).astype("int64")
    date_dim["active_chargers"] = date_dim["active_chargers"].fillna(199).astype("int64")
    date_dim["date_key"] = date_dim["date"].dt.strftime("%Y%m%d").astype("int64")
    date_dim["day_name"] = date_dim["date"].dt.day_name()
    date_dim["month_name"] = date_dim["date"].dt.month_name()
    date_dim["is_forecast_period"] = (date_dim["date"] >= FORECAST_START).astype("int8")
    date_dim.to_csv(POWERBI_DIR / "dim_date.csv", index=False)

    pd.DataFrame(
        {
            "horizon_flag": ["30D", "90D", "365D"],
            "horizon_days": [30, 90, 365],
            "sort_order": [1, 2, 3],
        }
    ).to_csv(POWERBI_DIR / "dim_horizon.csv", index=False)


def _run_hourly_short_term() -> pd.DataFrame:
    hourly_path = PROJECT_ROOT / "data" / "processed" / "hourly_demand.csv"
    hourly = pd.read_csv(hourly_path, parse_dates=["timestamp"]).set_index("timestamp")
    test = hourly.tail(24 * 7)
    train = hourly.iloc[:-len(test)]
    sarima_train = train.tail(24 * 180)
    predictors = {
        "SARIMAX": lambda fit_data, future: sarima_predict(
            fit_data, future, seasonal_period=24
        ),
        "Prophet": lambda fit_data, future: prophet_predict(
            fit_data, future, frequency="h"
        ),
        "XGBoost": lambda fit_data, future: xgboost_predict(
            fit_data, future, frequency="h"
        ),
    }
    training = {
        "SARIMAX": sarima_train,
        "Prophet": train,
        "XGBoost": train,
    }
    rows = []
    predictions: dict[str, pd.Series] = {}
    for name, predictor in predictors.items():
        print(f"Evaluating hourly {name} on the final 7 historical days...")
        prediction = predictor(training[name], test)
        predictions[name] = prediction
        rows.append(
            {
                "model": name,
                "train_start": training[name].index.min(),
                "train_end": training[name].index.max(),
                "test_start": test.index.min(),
                "test_end": test.index.max(),
                **metric_values(test["energy_kwh"], prediction),
            }
        )
    metrics = pd.DataFrame(rows).sort_values(
        ["mape_pct", "rmse_kwh"], kind="stable"
    )
    metrics.insert(0, "rank", range(1, len(metrics) + 1))
    metrics.to_csv(METRICS_DIR / "hourly_model_comparison_metrics.csv", index=False)
    prediction_frame = pd.DataFrame(
        {"actual_kwh": test["energy_kwh"], **predictions}
    )
    prediction_frame.to_csv(
        METRICS_DIR / "hourly_holdout_predictions.csv", index_label="timestamp"
    )

    figure, axis = plt.subplots(figsize=(13, 5))
    axis.plot(test.index, test["energy_kwh"], label="Actual", color="#16324F")
    for name, prediction in predictions.items():
        axis.plot(prediction.index, prediction, label=name, linewidth=1.2)
    axis.set(title="Hourly energy: final 7-day holdout", ylabel="Energy (kWh)")
    axis.legend()
    axis.grid(alpha=0.25)
    figure.tight_layout()
    figure.savefig(FIGURES_DIR / "hourly_model_holdout.png", dpi=160)
    plt.close(figure)

    future_index = pd.date_range(
        "2025-01-01 00:00:00", periods=24 * 7, freq="h", name="timestamp"
    )
    future = make_future_frame(future_index, active_chargers=199)
    forecast_rows = []
    for name, predictor in predictors.items():
        print(f"Refitting hourly {name} for the next 7 days...")
        fit_data = hourly.tail(24 * 180) if name == "SARIMAX" else hourly
        point = predictor(fit_data, future)
        errors = (test["energy_kwh"] - predictions[name]).abs().to_numpy()
        intervals = calibrated_intervals(point, errors).reset_index()
        intervals["model"] = name
        intervals["active_chargers"] = 199
        forecast_rows.append(intervals)
    forecasts = pd.concat(forecast_rows, ignore_index=True)
    forecasts = forecasts[
        [
            "timestamp",
            "model",
            "active_chargers",
            "yhat",
            "lower_80",
            "upper_80",
            "lower_95",
            "upper_95",
        ]
    ]
    forecasts.insert(1, "date", forecasts["timestamp"].dt.normalize())
    forecasts.to_csv(
        FORECASTS_DIR / "hourly_short_term_forecasts.csv", index=False
    )
    print("\nHourly holdout metrics (final seven days of 2024):")
    print(metrics.to_string(index=False))
    return forecasts


def _save_holdout_plot(
    name: str, actual: pd.Series, predicted: pd.Series
) -> None:
    figure, axis = plt.subplots(figsize=(12, 5))
    axis.plot(actual.index, actual, label="Actual", color="#16324F", linewidth=1.8)
    axis.plot(
        predicted.index,
        predicted,
        label=f"{name} forecast",
        color="#E36B2C",
        linewidth=1.8,
    )
    axis.set(title=f"{name}: daily demand holdout", ylabel="Energy (kWh)")
    axis.legend()
    axis.grid(alpha=0.25)
    figure.tight_layout()
    figure.savefig(FIGURES_DIR / f"{name.lower()}_holdout.png", dpi=160)
    plt.close(figure)


def run_evaluation_and_forecast(
    daily_path: Path = DAILY_PATH,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    daily = load_daily(daily_path)
    train = daily.loc[:TRAIN_END]
    test = daily.loc[TEST_START:TEST_END]
    if train.empty or len(test) != 92:
        raise ValueError(
            "Expected a daily training set through 2024-09-30 and 92 holdout days "
            "from 2024-10-01 through 2024-12-31."
        )

    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    FORECASTS_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    holdout_predictions: dict[str, pd.Series] = {}
    metric_rows: list[dict[str, object]] = []
    for name, predictor in MODELS.items():
        print(f"Evaluating {name} on {test.index.min().date()} to {test.index.max().date()}...")
        prediction = predictor(train, test)
        holdout_predictions[name] = prediction
        metric_rows.append(
            {
                "model": name,
                "train_start": train.index.min().date(),
                "train_end": train.index.max().date(),
                "test_start": test.index.min().date(),
                "test_end": test.index.max().date(),
                **metric_values(test["energy_kwh"], prediction),
            }
        )
        _save_holdout_plot(name, test["energy_kwh"], prediction)

    metrics = pd.DataFrame(metric_rows).sort_values(
        ["mape_pct", "rmse_kwh"], kind="stable"
    )
    metrics.insert(0, "rank", range(1, len(metrics) + 1))
    metrics.to_csv(METRICS_DIR / "model_comparison_metrics.csv", index=False)
    prediction_frame = pd.DataFrame(
        {
            "actual_kwh": test["energy_kwh"],
            **{name: values for name, values in holdout_predictions.items()},
        }
    )
    prediction_frame.to_csv(METRICS_DIR / "holdout_predictions.csv", index_label="date")

    best_model = str(metrics.iloc[0]["model"])
    print(f"Best model by holdout MAPE: {best_model}")
    future_index = pd.date_range(FORECAST_START, FORECAST_END, freq="D", name="date")
    future = make_future_frame(future_index, active_chargers=199)
    full_forecasts: dict[str, pd.DataFrame] = {}
    forecast_rows: list[pd.DataFrame] = []
    for name, predictor in MODELS.items():
        print(f"Refitting {name} on the full 2022-2024 history...")
        suffix = {"SARIMAX": ".pkl", "Prophet": ".json", "XGBoost": ".json"}[name]
        point = predictor(
            daily,
            future,
            model_path=MODELS_DIR / f"{name.lower()}{suffix}",
        )
        absolute_errors = (
            test["energy_kwh"] - holdout_predictions[name]
        ).abs().to_numpy()
        intervals = calibrated_intervals(point, absolute_errors)
        intervals.index.name = "date"
        intervals["model"] = name
        intervals["active_chargers"] = 199
        full_forecasts[name] = intervals.reset_index()
        for horizon, days in (("30D", 30), ("90D", 90), ("365D", 365)):
            horizon_frame = intervals.iloc[:days].reset_index()
            horizon_frame["model"] = name
            horizon_frame["active_chargers"] = 199
            horizon_frame["horizon_flag"] = horizon
            forecast_rows.append(horizon_frame)

    forecasts = pd.concat(forecast_rows, ignore_index=True)
    forecasts = forecasts[
        [
            "date",
            "model",
            "horizon_flag",
            "active_chargers",
            "yhat",
            "lower_80",
            "upper_80",
            "lower_95",
            "upper_95",
        ]
    ]
    forecasts.to_csv(FORECASTS_DIR / "daily_forecasts_all_models.csv", index=False)
    best_forecast = full_forecasts[best_model]
    best_forecast.to_csv(
        FORECASTS_DIR / "daily_forecast_best_model_365d.csv", index=False
    )
    task_exports = export_task_forecasts(daily, forecasts, metrics)
    print("\nTask forecast exports:")
    for name, path in task_exports.items():
        print(f"  {name}: {path}")
    hourly_forecasts = _run_hourly_short_term()
    _export_powerbi(daily, forecasts, metrics, hourly_forecasts)
    return metrics, forecasts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--daily", type=Path, default=DAILY_PATH)
    args = parser.parse_args()
    metrics, forecasts = run_evaluation_and_forecast(args.daily)
    print("\nHoldout metrics:")
    print(metrics.to_string(index=False))
    print(f"\nForecast rows exported: {len(forecasts):,}")
    print(f"Outputs: {PROJECT_ROOT / 'outputs'}")


if __name__ == "__main__":
    main()
