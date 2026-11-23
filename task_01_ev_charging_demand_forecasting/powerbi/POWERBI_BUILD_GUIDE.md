# Power BI Desktop Build Guide

Build the report from the CSVs in `outputs/powerbi_data/`. Refresh or run `python src/run_pipeline.py` before loading data.

## 1. Load the CSV files

1. Open Power BI Desktop → **Get data** → **Text/CSV**.
2. Load each of these files (select **Transform Data** if you need to adjust types):
   - `powerbi_forecast_master.csv` (in `outputs/forecasts/`; the requested actual/forecast horizon table)
   - `fact_historical_daily.csv`
   - `fact_forecast_daily.csv`
   - `fact_hourly_profile.csv`
   - `fact_historical_segmented.csv`
   - `fact_station_daily.csv`
   - `fact_charger_type_daily.csv`
   - `fact_hourly_forecast.csv`
   - `dim_date.csv`
   - `dim_stations.csv`
   - `dim_charger_types.csv`
   - `dim_horizon.csv`
   - `model_metrics.csv`
3. Set all `date` and `timestamp` fields to Date and Date/Time respectively. Set numeric energy and price fields to Decimal Number; counts and date keys to Whole Number. Set `dim_date[date]` as the model's date column if Power BI prompts.
4. Rename tables to the exact CSV basenames if Power BI did not use them automatically.

## 2. Configure relationships

In **Model view**, create these active, single-direction, one-to-many relationships from dimensions to facts:

| One side | Many side | Key |
|---|---|---|
| `dim_date[date]` | `fact_historical_daily[date]` | date |
| `dim_date[date]` | `fact_forecast_daily[date]` | date |
| `dim_date[date]` | `fact_hourly_profile[date]` | date |
| `dim_date[date]` | `fact_historical_segmented[date]` | date |
| `dim_date[date]` | `fact_station_daily[date]` | date |
| `dim_date[date]` | `fact_charger_type_daily[date]` | date |
| `dim_date[date]` | `fact_hourly_forecast[date]` | date |
| `dim_date[date]` | `powerbi_forecast_master[Date]` | date |
| `dim_stations[station_id]` | `fact_station_daily[station_id]` | station |
| `dim_charger_types[charger_type]` | `fact_charger_type_daily[charger_type]` | charger type |
| `dim_horizon[horizon_flag]` | `fact_forecast_daily[horizon_flag]` | forecast horizon |

Do not relate `model_metrics` to the date dimension; it is a model-level evaluation table. Use `fact_historical_segmented[segment_dimension]` as a visual/page filter when comparing region, charger type, and user type. Avoid bidirectional relationships.

## 3. Add DAX measures

Create these measures (adjust table/column quoting only if Power BI renamed your tables):

```DAX
Total Historical kWh =
SUM ( fact_historical_daily[energy_kwh] )

Forecast kWh =
VAR BestModel =
    MAXX (
        TOPN ( 1, ALL ( model_metrics ), model_metrics[mape_pct], ASC ),
        model_metrics[model]
    )
RETURN
    CALCULATE (
        SUM ( fact_forecast_daily[yhat] ),
        fact_forecast_daily[model] = BestModel
    )

Forecast Upper CI =
VAR BestModel =
    MAXX (
        TOPN ( 1, ALL ( model_metrics ), model_metrics[mape_pct], ASC ),
        model_metrics[model]
    )
RETURN
    CALCULATE (
        SUM ( fact_forecast_daily[upper_95] ),
        fact_forecast_daily[model] = BestModel
    )

Forecast Lower CI =
VAR BestModel =
    MAXX (
        TOPN ( 1, ALL ( model_metrics ), model_metrics[mape_pct], ASC ),
        model_metrics[model]
    )
RETURN
    CALCULATE (
        SUM ( fact_forecast_daily[lower_95] ),
        fact_forecast_daily[model] = BestModel
    )

Best Model Name =
    MAXX (
        TOPN ( 1, ALL ( model_metrics ), model_metrics[mape_pct], ASC ),
        model_metrics[model]
    )

Best Model MAPE =
    MINX ( ALL ( model_metrics ), model_metrics[mape_pct] )

Best Model RMSE =
    MINX ( ALL ( model_metrics ), model_metrics[rmse_kwh] )

Forecasted Demand =
CALCULATE (
    SUM ( powerbi_forecast_master[Best_Model_Forecast] ),
    powerbi_forecast_master[Record_Type] = "Forecast"
)

Actual or Forecast Demand =
    SUM ( powerbi_forecast_master[Actual_Demand] ) + [Forecasted Demand]

MoM Demand Growth % =
VAR CurrentMonthDemand = [Total Historical kWh]
VAR PreviousMonthDemand =
    CALCULATE (
        [Total Historical kWh],
        DATEADD ( dim_date[date], -1, MONTH )
    )
RETURN
    DIVIDE ( CurrentMonthDemand - PreviousMonthDemand, PreviousMonthDemand )

Peak Day Demand =
    MAXX (
        VALUES ( dim_date[date] ),
        CALCULATE ( [Total Historical kWh] )
    )

Peak Hour Share % =
DIVIDE (
    CALCULATE (
        SUM ( fact_hourly_profile[energy_kwh] ),
        fact_hourly_profile[hour] >= 10,
        fact_hourly_profile[hour] <= 14
    ),
    SUM ( fact_hourly_profile[energy_kwh] )
)

YoY Demand Growth % =
VAR CurrentYearEnergy = [Total Historical kWh]
VAR PriorYearEnergy =
    CALCULATE (
        [Total Historical kWh],
        DATEADD ( dim_date[date], -1, YEAR )
    )
RETURN
    DIVIDE ( CurrentYearEnergy - PriorYearEnergy, PriorYearEnergy )

Nominal Energy Capacity kWh =
SUMX (
    fact_charger_type_daily,
    fact_charger_type_daily[active_chargers]
        * RELATED ( dim_charger_types[max_power_kW] )
        * 24
    )

Nominal Capacity Load Proxy % =
DIVIDE (
    SUM ( fact_charger_type_daily[energy_kwh] ),
    [Nominal Energy Capacity kWh]
)
```

`mape_pct` is stored in percentage points (for example 10.5 means 10.5%), so format `Best Model MAPE` as a decimal number with a `%` suffix or divide by 100 for Power BI percentage formatting.

The `Nominal Capacity Load Proxy %` is only a rough energy-to-nameplate upper-capacity proxy. It is not charger occupancy or a measured utilization rate; actual utilization needs connection/charging occupancy intervals and availability/outage data. `active_chargers` uses annual installation totals as January 1 step changes because 88,466 supplied sessions predate their charger installation timestamps; see the EDA report for this data-quality caveat.

## 4. Build the three report pages

### Page 1 — Executive Demand Forecast

- KPI cards: `Total Historical kWh`, `Forecast kWh`, `Best Model Name`, `Best Model MAPE`.
- Add a single-select slicer on `powerbi_forecast_master[Horizon]` for
  **Historical**, **30D**, **90D**, and **365D** (or use `dim_horizon` when
  building from `fact_forecast_daily`). Future horizons intentionally overlap.
- Line chart: `dim_date[date]` on the X-axis and `Actual or Forecast Demand` as
  the value. Use `Record_Type` and `Horizon` slicers to choose the series/window.
- For an uncertainty display, add `Forecast Upper CI` and `Forecast Lower CI` to a line/area visual or use the Analytics pane's error bars where supported.
- Table: `model_metrics[model]`, `mape_pct`, `rmse_kwh`, `mae_kwh`; sort by MAPE ascending.

For a single actual-or-forecast line measure:

```DAX
Actual or Forecast kWh =
VAR LastHistoricalDate =
    CALCULATE ( MAX ( fact_historical_daily[date] ), ALL ( dim_date ) )
RETURN
    IF (
        MAX ( dim_date[date] ) <= LastHistoricalDate,
        [Total Historical kWh],
        [Forecast kWh]
    )
```

### Page 2 — Seasonal, Weekly & Hourly Patterns

- Matrix heatmap: `fact_hourly_profile[day_of_week]` rows × `fact_hourly_profile[hour]` columns; values are average `energy_kwh`. Apply conditional background color.
- Weekday/weekend clustered bar: use `is_weekend` and average historical daily energy; add a separate view for energy per active charger if normalizing capacity.
- Monthly line: `dim_date[month_name]` or month/year hierarchy against average daily historical kWh. Sort month name by month number.
- User-type breakdown: filter `fact_historical_segmented[segment_dimension]` to `user_type`; plot energy by `segment_value`, sliced by date and day type.

### Page 3 — Regional & Charger Capacity Planning

- Regional demand: filter segmented fact to `station_region`; chart total energy by `segment_value`.
- Charger type: filter segmented fact to `charger_type`; compare daily energy by charger class. Use `Nominal Capacity Load Proxy %` only with the caveat above; do not label it measured utilization.
- Station-level load: use `fact_station_daily[energy_kwh]` by `dim_stations[station_name]`, with region slicers and `n_chargers` in tooltips.
- Short-term capacity planning: plot `fact_hourly_forecast[yhat]` with its lower/upper interval columns by `timestamp` for the first seven days of 2025.
- Add date, region, and charger-type slicers; keep the chart totals and the selected date range clear.

## 5. Save and export screenshots

Save the report as `powerbi/task01_ev_demand_dashboard.pbix`. Export each finished page as a PNG and save them in `powerbi/screenshots/` (for example `executive_forecast.png`, `seasonal_patterns.png`, and `capacity_planning.png`) for portfolio/GitHub documentation.
