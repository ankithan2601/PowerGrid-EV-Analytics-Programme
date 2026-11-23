"""Export long-form model results as Task 1 and Power BI forecast tables."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FORECASTS_DIR = PROJECT_ROOT / "outputs" / "forecasts"
FIGURES_DIR = PROJECT_ROOT / "outputs" / "figures"
HORIZONS = (("30D", 30), ("90D", 90), ("365D", 365))
EXPORT_COLUMNS = [
    "Date",
    "SARIMA_Forecast",
    "Prophet_Forecast",
    "Prophet_Lower",
    "Prophet_Upper",
    "XGBoost_Forecast",
    "Best_Model_Forecast",
    "Day_Of_Week",
    "Month",
    "Is_Weekend",
]
MASTER_COLUMNS = [
    "Date",
    "Record_Type",
    "Horizon",
    "Actual_Demand",
    "SARIMA_Forecast",
    "Prophet_Forecast",
    "Prophet_Lower",
    "Prophet_Upper",
    "XGBoost_Forecast",
    "Best_Model_Forecast",
    "Day_Of_Week",
    "Month",
    "Is_Weekend",
]
MODEL_COLUMN_NAMES = {
    "SARIMAX": "SARIMA_Forecast",
    "Prophet": "Prophet_Forecast",
    "XGBoost": "XGBoost_Forecast",
}


def _calendar_columns(dates: pd.DatetimeIndex) -> dict[str, object]:
    return {
        "Day_Of_Week": dates.day_name(),
        "Month": dates.month,
        "Is_Weekend": (dates.dayofweek >= 5).astype("int8"),
    }


def _wide_horizon(
    horizon_rows: pd.DataFrame, best_model: str, horizon: str
) -> pd.DataFrame:
    selected = horizon_rows.loc[horizon_rows["horizon_flag"] == horizon].copy()
    if selected.empty:
        raise ValueError(f"No forecast rows are available for horizon {horizon}.")

    point = selected.pivot(index="date", columns="model", values="yhat").sort_index()
    required_models = set(MODEL_COLUMN_NAMES)
    if required_models.difference(point.columns):
        missing = sorted(required_models.difference(point.columns))
        raise ValueError(
            f"Forecast output for {horizon} is missing models: {', '.join(missing)}."
        )
    if best_model not in point.columns:
        raise ValueError(f"Best model {best_model!r} is missing from forecast rows.")

    dates = pd.DatetimeIndex(point.index, name="Date")
    prophet_intervals = (
        selected.loc[selected["model"] == "Prophet"]
        .set_index("date")
        .reindex(dates)
    )
    result = pd.DataFrame(
        {
            "Date": dates,
            "SARIMA_Forecast": point["SARIMAX"].to_numpy(),
            "Prophet_Forecast": point["Prophet"].to_numpy(),
            "Prophet_Lower": prophet_intervals["lower_95"].to_numpy(),
            "Prophet_Upper": prophet_intervals["upper_95"].to_numpy(),
            "XGBoost_Forecast": point["XGBoost"].to_numpy(),
            "Best_Model_Forecast": point[best_model].to_numpy(),
        }
    )
    for column, values in _calendar_columns(dates).items():
        result[column] = values
    return result[EXPORT_COLUMNS]


def _save_forecast_plot(
    daily: pd.DataFrame, forecast: pd.DataFrame, horizon: str, days: int
) -> Path:
    context_days = min(365, max(90, days))
    historical = daily.tail(context_days)
    figure, axis = plt.subplots(figsize=(13, 5))
    axis.plot(
        historical.index,
        historical["energy_kwh"],
        label="Actual",
        color="#16324F",
        linewidth=1.5,
    )
    axis.plot(
        forecast["Date"],
        forecast["SARIMA_Forecast"],
        label="SARIMAX",
        linewidth=1.1,
    )
    axis.plot(
        forecast["Date"],
        forecast["Prophet_Forecast"],
        label="Prophet",
        linewidth=1.1,
    )
    axis.fill_between(
        forecast["Date"],
        forecast["Prophet_Lower"],
        forecast["Prophet_Upper"],
        alpha=0.15,
        label="Prophet empirical 95% interval",
    )
    axis.plot(
        forecast["Date"],
        forecast["XGBoost_Forecast"],
        label="XGBoost",
        linewidth=1.1,
    )
    axis.set(
        title=f"Daily EV demand: {days}-day forecast",
        xlabel="Date",
        ylabel="Energy (kWh)",
    )
    axis.grid(alpha=0.25)
    axis.legend(ncol=2)
    figure.tight_layout()
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    output = FIGURES_DIR / f"forecast_{days}d.png"
    figure.savefig(output, dpi=180)
    plt.close(figure)
    return output


def export_task_forecasts(
    daily: pd.DataFrame,
    forecasts: pd.DataFrame,
    metrics: pd.DataFrame,
) -> dict[str, Path]:
    """Write horizon-specific forecasts, a Power BI master, and forecast plots."""
    required_forecast_columns = {
        "date",
        "model",
        "horizon_flag",
        "yhat",
        "lower_95",
        "upper_95",
    }
    missing_forecast_columns = required_forecast_columns.difference(forecasts.columns)
    if missing_forecast_columns:
        raise ValueError(
            "Forecast results are missing columns: "
            + ", ".join(sorted(missing_forecast_columns))
        )
    if "model" not in metrics or "mape_pct" not in metrics or metrics.empty:
        raise ValueError("Model metrics must include model and mape_pct values.")
    if "energy_kwh" not in daily.columns or not isinstance(daily.index, pd.DatetimeIndex):
        raise ValueError("Daily history must be indexed by date and include energy_kwh.")

    best_model = str(
        metrics.sort_values(["mape_pct", "rmse_kwh"], kind="stable")
        .iloc[0]["model"]
    )
    FORECASTS_DIR.mkdir(parents=True, exist_ok=True)
    metrics_path = FORECASTS_DIR / "model_metrics.csv"
    metrics.to_csv(metrics_path, index=False)

    export_frames: dict[str, pd.DataFrame] = {}
    outputs: dict[str, Path] = {"model_metrics": metrics_path}
    for horizon, days in HORIZONS:
        frame = _wide_horizon(forecasts, best_model, horizon)
        if len(frame) != days:
            raise ValueError(
                f"Expected {days} daily rows for {horizon}, found {len(frame)}."
            )
        export_frames[horizon] = frame
        path = FORECASTS_DIR / f"forecast_{days}d.csv"
        frame.to_csv(path, index=False, date_format="%Y-%m-%d")
        outputs[f"forecast_{days}d"] = path
        outputs[f"figure_{days}d"] = _save_forecast_plot(
            daily, frame, horizon, days
        )

    historical_dates = pd.DatetimeIndex(daily.index, name="Date")
    history = pd.DataFrame(
        {
            "Date": historical_dates,
            "Record_Type": "Actual",
            "Horizon": "Historical",
            "Actual_Demand": daily["energy_kwh"].to_numpy(dtype=float),
            **{
                column: np.nan
                for column in EXPORT_COLUMNS
                if column not in {"Date", "Day_Of_Week", "Month", "Is_Weekend"}
            },
            **_calendar_columns(historical_dates),
        }
    )

    future_rows = []
    for horizon, _days in HORIZONS:
        future = export_frames[horizon].copy()
        future.insert(1, "Record_Type", "Forecast")
        future.insert(2, "Horizon", horizon)
        future.insert(3, "Actual_Demand", np.nan)
        future_rows.append(future[MASTER_COLUMNS])

    master = pd.concat(
        [history[MASTER_COLUMNS], *future_rows],
        ignore_index=True,
    ).sort_values(["Date", "Record_Type", "Horizon"], kind="stable")
    master_path = FORECASTS_DIR / "powerbi_forecast_master.csv"
    master.to_csv(master_path, index=False, date_format="%Y-%m-%d")
    outputs["powerbi_forecast_master"] = master_path
    return outputs
