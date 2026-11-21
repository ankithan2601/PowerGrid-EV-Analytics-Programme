"""Generate seasonal charts and a data-backed EDA report."""

from eda_seasonality import run_eda


if __name__ == "__main__":
    print(f"EDA report written: {run_eda()}")
