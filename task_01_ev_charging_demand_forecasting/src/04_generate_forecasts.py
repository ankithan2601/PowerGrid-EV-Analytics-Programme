"""Build Power BI and horizon-specific exports from trained model outputs."""

from pathlib import Path

import pandas as pd

from forecast_exports import export_task_forecasts
from forecasting_utils import DAILY_PATH, PROJECT_ROOT


def main() -> None:
    forecasts_path = PROJECT_ROOT / "outputs" / "forecasts" / "daily_forecasts_all_models.csv"
    metrics_path = PROJECT_ROOT / "outputs" / "metrics" / "model_comparison_metrics.csv"
    if not forecasts_path.is_file() or not metrics_path.is_file():
        raise FileNotFoundError(
            "Run src/03_train_models.py first to generate full-history forecasts "
            "and holdout metrics."
        )

    daily = pd.read_csv(DAILY_PATH, parse_dates=["date"]).set_index("date")
    forecasts = pd.read_csv(forecasts_path, parse_dates=["date"])
    metrics = pd.read_csv(metrics_path)
    outputs = export_task_forecasts(daily, forecasts, metrics)
    print("Task forecast exports written:")
    for name, path in outputs.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
