"""Run data preparation, EDA, evaluation, and full-year forecasting."""

from __future__ import annotations

import argparse
from pathlib import Path

from data_prep import DEFAULT_INPUT, prepare_datasets
from eda_seasonality import run_eda
from evaluate_and_forecast import run_evaluation_and_forecast


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    args = parser.parse_args()

    print("Step 1/3: preparing continuous demand datasets")
    prepared = prepare_datasets(args.input)
    for name, path in prepared.items():
        print(f"  {name}: {path}")

    print("\nStep 2/3: generating EDA charts and insights")
    print(f"  report: {run_eda()}")

    print("\nStep 3/3: evaluating models and exporting forecasts")
    metrics, forecasts = run_evaluation_and_forecast()
    print("\nModel comparison (ranked by holdout MAPE):")
    print(metrics.to_string(index=False))
    print(f"\nForecast records exported: {len(forecasts):,}")


if __name__ == "__main__":
    main()
