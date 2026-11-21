# PowerGrid EV Analytics Programme

A 16-task analytics programme for EV charging data, built with Python, Power BI,
and GitHub. Each task belongs in its own `task_NN_*` directory so its code,
data, documentation, and outputs remain independent.

## Task status

| Task | Directory | Status |
|---|---|---|
| 01 — EV charging demand forecasting | `task_01_ev_charging_demand_forecasting/` | Pipeline and forecast exports ready; Power BI report pending |
| 02–16 | `task_NN_*` | Add as each task is defined |

Task 1 covers session-data validation, hourly and daily aggregation, seasonal
analysis, chronological model evaluation, and 30/90/365-day demand forecasts.
See its README for methodology, dataset-quality findings, model comparison,
Power BI guidance, and operating recommendations.

## Setup

Use Python 3.10 or later. Install the shared and Task 1 dependencies from the
repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python task_01_ev_charging_demand_forecasting\src\run_pipeline.py
```

Raw workbooks, local virtual environments, caches, and fitted model binaries
are excluded by `.gitignore`. Keep source data local unless its licence and
publication status have been confirmed.
