"""Evaluate daily models chronologically and retrain for future forecasts."""

from evaluate_and_forecast import run_evaluation_and_forecast


if __name__ == "__main__":
    metrics, forecasts = run_evaluation_and_forecast()
    print("\nHoldout metrics:")
    print(metrics.to_string(index=False))
    print(f"\nForecast records exported: {len(forecasts):,}")
