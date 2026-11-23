# EV Charging Demand Forecasting

Task 1 of the PowerGrid EV Analytics Programme builds an end-to-end, reproducible workflow for understanding and forecasting UK EV charging demand.

## Objectives

- Turn session-level records into continuous hourly and daily demand series.
- Separate network rollout from demand patterns using active-station and active-charger features.
- Compare three daily forecasting approaches on a chronological holdout.
- Export full-year forecasts, empirical uncertainty bands, Power BI facts/dimensions, and decision-focused EDA.

## Repository contents

```text
data/
  raw/                 Source workbook (local; excluded from Git)
  processed/           Hourly, daily, and segmented CSVs
notebooks/              EDA notebook
src/
  01_data_cleaning.py   Requested cleaning entry point
  02_eda_seasonality.py Requested EDA entry point
  03_train_models.py    Chronological evaluation and full-history refit
  04_generate_forecasts.py Power BI and horizon export entry point
  data_prep.py          Workbook validation and time-series aggregation
  eda_seasonality.py    Charts and insights report generator
  evaluate_and_forecast.py Integrated evaluation and full-history forecasting
  forecast_exports.py  Horizon-specific and Power BI export helpers
  forecasting_utils.py  Shared calendar, feature, and metric utilities
  models/               SARIMAX, Prophet, and XGBoost trainers
  run_pipeline.py       End-to-end entry point
outputs/
  figures/              EDA and model-comparison plots
  forecasts/            30/90/365-day forecasts and intervals
  metrics/              Holdout predictions and model comparison
  models/               Full-history fitted model artifacts
  powerbi_data/         Power BI facts and dimensions
powerbi/                Dashboard build guide and PBIX screenshots
reports/                Data-backed findings and recommendations
```

## Setup and run

Use Python 3.10 or later (the project has been validated with Python 3.12). In VS Code, open this folder, then select the project interpreter using **Python: Select Interpreter** → `.venv\Scripts\python.exe`.

PowerShell:

```powershell
cd "path\to\PowerGrid-EV-Analytics-Programme\task_01_ev_charging_demand_forecasting"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Place `ev_charging_dataset.xlsx` in `data/raw/`. The source workbook is excluded by `.gitignore` because it is approximately 27 MB. Then run:

```powershell
python src/run_pipeline.py
```

The same pipeline stages are available through the numbered entry points:

```powershell
python src/01_data_cleaning.py
python src/02_eda_seasonality.py
python src/03_train_models.py
python src/04_generate_forecasts.py
```

`03_train_models.py` performs both the chronological holdout evaluation and the
full-history refit. `04_generate_forecasts.py` formats those model results into
the horizon-specific and Power BI exports; it does not train the models again.

To rebuild only the processed CSVs:

```powershell
python src/data_prep.py
```

The pipeline regenerates the data, EDA, model comparisons, forecasts, and Power BI exports. It does not overwrite the source workbook.

## Methodology

The daily target is `energy_kwh`. The holdout is **2024-10-01 through 2024-12-31**; training ends on **2024-09-30**. The trainers compare:

| Model | Daily design |
|---|---|
| SARIMAX | Weekly seasonal ARIMA, with active chargers as an exogenous regressor |
| Prophet | Weekly/yearly seasonality, UK holidays, and active chargers as a regressor |
| XGBoost | Recursive lags (1/7/14/28), prior rolling mean/std (7/28), cyclical time, weekend, and active chargers |

Models are ranked by holdout MAPE; RMSE and MAE are also reported. Future forecasts use the full 2022–2024 history and a fixed **199 active-charger** scenario. The 80% and 95% bands are symmetric empirical bands calibrated from each model's absolute holdout errors; they are uncertainty estimates, not guarantees of coverage under future distribution shift.

The same three model families are also evaluated for short-term hourly planning using the final seven days of 2024 as a separate holdout. Hourly SARIMAX uses 24-hour seasonality and a trailing 180-day fit window; Prophet uses weekly/yearly plus daily seasonality; XGBoost uses hourly lags (1/24/168/336), rolling windows (24/168), cyclical time, weekend, and active chargers. The models then produce a seven-day January 2025 hourly scenario.

Station activation is only supplied as a year, so station counts are treated as active from January 1 of that year. Although charger installation dates are present, **88,466 session rows predate the installation date recorded for their charger**. To avoid a contradictory within-year capacity timeline, charger capacity uses cumulative annual installation totals as January 1 step changes (43, 102, and 199). The pipeline warns about this data inconsistency.

## Dataset inspection and cleaning

The source workbook has `stations` (33 rows), `chargers` (199 rows), and
`sessions` (294,024 rows) sheets. The session timestamp is `start_timestamp`;
the forecast target is `energy_kwh`. Other session fields include `session_id`,
station and charger IDs, duration, cost, user type, and region. Session starts
range from **2022-01-01 01:30** to **2024-12-31 23:50**; the workbook provides
timezone-naive values.

The inspection found no missing cells in the three sheets, no duplicate entity
keys (`station_id`, `charger_id`, or `session_id` in their respective tables),
no unparseable timestamps, and no negative energy, duration, or cost values.
Using the 1.5×IQR rule, `energy_kwh` and `session_duration_minutes` have no
outliers; `total_cost` has 4,284. Cost outliers are retained (not capped or
removed) because the target is energy and the values are not negative. The
cleaning script prints these checks when it builds the processed data. It
rejects malformed, null, duplicate-key, or negative required data explicitly
rather than silently changing source records. Empty time buckets are filled
with zero energy and zero sessions.

## Model comparison

`outputs/metrics/model_comparison_metrics.csv` is the authoritative, pipeline-generated comparison table (ranked by holdout MAPE). Refresh this README table after each pipeline run:

| Rank | Model | MAPE (%) | RMSE (kWh) | MAE (kWh) |
|---:|---|---:|---:|---:|
| 1 | XGBoost | 3.87 | 1,087.40 | 829.55 |
| 2 | SARIMAX | 3.91 | 1,019.44 | 835.48 |
| 3 | Prophet | 6.75 | 1,625.97 | 1,369.36 |

These are from the most recent run; the generated metrics CSV is authoritative. XGBoost wins by MAPE, while SARIMAX has the lowest RMSE; select a model based on the error profile most relevant to the planning use case.

The separate hourly holdout (last 7 days of 2024) ranked XGBoost at **33.07% MAPE**, SARIMAX at **41.57%**, and Prophet at **83.59%**. The hourly result is based on only one weekly window and is especially sensitive to near-zero hours, so treat it as a short-term diagnostic rather than a stable long-run model ranking.

## Insights and outputs

See [the EDA report](reports/task1_insights.md) for quantified weekday/weekend, hour-of-day, monthly/quarterly, regional, and user-type patterns with operational recommendations.

Key reproducible outputs:

- `data/processed/hourly_demand.csv`, `daily_demand.csv`, and `daily_demand_segmented.csv`
- `outputs/metrics/model_comparison_metrics.csv` and `holdout_predictions.csv`
- `outputs/metrics/hourly_model_comparison_metrics.csv` and `hourly_holdout_predictions.csv`
- `outputs/forecasts/daily_forecasts_all_models.csv` and `daily_forecast_best_model_365d.csv`
- `outputs/forecasts/forecast_30d.csv`, `forecast_90d.csv`, `forecast_365d.csv`,
  `powerbi_forecast_master.csv`, and `model_metrics.csv`
- `outputs/forecasts/hourly_short_term_forecasts.csv`
- `outputs/figures/` for EDA, actual-vs-predicted, and 30/90/365-day forecast plots
- `outputs/powerbi_data/` for dashboard facts and dimensions, including short-term hourly forecasts

## Power BI

Follow [the Power BI build guide](powerbi/POWERBI_BUILD_GUIDE.md). Save the finished report as `powerbi/task01_ev_demand_dashboard.pbix` and export documentation images to `powerbi/screenshots/`.

## GitHub submission

From the repository root, use the task branch for this submission. Keep the raw
workbook local unless you have confirmed it is appropriate to publish.

```powershell
git switch task-01-demand-forecasting
git add .gitignore README.md requirements.txt task_01_ev_charging_demand_forecasting
git diff --cached --check
git status --short
git commit -m "Update Task 1 EV demand forecasting"
git push
```

Before committing, confirm generated outputs are appropriate to publish. The
raw workbook and local virtual environment are intentionally ignored.
