"""Prepare continuous hourly, daily, and segmented EV demand datasets."""

from __future__ import annotations

import argparse
from pathlib import Path
import warnings

import holidays
import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = PROJECT_ROOT / "data" / "raw" / "ev_charging_dataset.xlsx"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "processed"

START = pd.Timestamp("2022-01-01 00:00:00")
END = pd.Timestamp("2024-12-31 23:00:00")

STATION_COLUMNS = {"station_id", "region", "activation_year"}
CHARGER_COLUMNS = {
    "charger_id",
    "station_id",
    "charger_type",
    "installation_date",
}
SESSION_COLUMNS = {
    "session_id",
    "station_id",
    "charger_id",
    "charger_type",
    "start_timestamp",
    "session_duration_minutes",
    "energy_kwh",
    "total_cost",
    "user_type",
    "station_region",
}
SEGMENT_COLUMNS = {
    "station_region": "station_region",
    "charger_type": "charger_type",
    "user_type": "user_type",
}
AGGREGATIONS = {
    "energy_kwh": ("energy_kwh", "sum"),
    "session_count": ("session_id", "size"),
    "total_revenue": ("total_cost", "sum"),
    "avg_duration_min": ("session_duration_minutes", "mean"),
}


def _require_columns(
    frame: pd.DataFrame, required: set[str], sheet_name: str
) -> None:
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(
            f"Sheet '{sheet_name}' is missing required columns: {', '.join(missing)}"
        )


def _parse_naive_datetime(values: pd.Series, column_name: str) -> pd.Series:
    parsed = pd.to_datetime(values, errors="raise")
    if parsed.dt.tz is not None:
        raise ValueError(
            f"'{column_name}' must contain timezone-naive local timestamps."
        )
    return parsed


def _validate_inputs(
    stations: pd.DataFrame,
    chargers: pd.DataFrame,
    sessions: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    _require_columns(stations, STATION_COLUMNS, "stations")
    _require_columns(chargers, CHARGER_COLUMNS, "chargers")
    _require_columns(sessions, SESSION_COLUMNS, "sessions")

    frames_and_columns = (
        (stations, STATION_COLUMNS, "stations"),
        (chargers, CHARGER_COLUMNS, "chargers"),
        (sessions, SESSION_COLUMNS, "sessions"),
    )
    for frame, columns, sheet_name in frames_and_columns:
        null_columns = sorted(frame[list(columns)].columns[frame[list(columns)].isna().any()])
        if null_columns:
            raise ValueError(
                f"Sheet '{sheet_name}' contains nulls in required columns: "
                f"{', '.join(null_columns)}"
            )

    stations = stations.copy()
    chargers = chargers.copy()
    sessions = sessions.copy()

    if stations["station_id"].duplicated().any():
        raise ValueError("Sheet 'stations' contains duplicate station_id values.")
    if chargers["charger_id"].duplicated().any():
        raise ValueError("Sheet 'chargers' contains duplicate charger_id values.")
    if sessions["session_id"].duplicated().any():
        raise ValueError("Sheet 'sessions' contains duplicate session_id values.")

    stations["activation_year"] = pd.to_numeric(
        stations["activation_year"], errors="raise"
    ).astype(int)
    chargers["installation_date"] = _parse_naive_datetime(
        chargers["installation_date"], "installation_date"
    )
    sessions["start_timestamp"] = _parse_naive_datetime(
        sessions["start_timestamp"], "start_timestamp"
    )
    for column in ("energy_kwh", "session_duration_minutes", "total_cost"):
        sessions[column] = pd.to_numeric(sessions[column], errors="raise")
        if (sessions[column] < 0).any():
            raise ValueError(f"Session column '{column}' contains negative values.")

    unknown_stations = set(sessions["station_id"]).difference(stations["station_id"])
    unknown_chargers = set(sessions["charger_id"]).difference(chargers["charger_id"])
    if unknown_stations:
        raise ValueError("Sessions reference station_id values absent from 'stations'.")
    if unknown_chargers:
        raise ValueError("Sessions reference charger_id values absent from 'chargers'.")
    installation_dates = chargers.set_index("charger_id")["installation_date"]
    session_install_dates = sessions["charger_id"].map(installation_dates)
    preinstallation_sessions = int(
        (sessions["start_timestamp"] < session_install_dates).sum()
    )
    if preinstallation_sessions:
        warnings.warn(
            f"{preinstallation_sessions:,} sessions predate their charger's "
            "installation_date. Capacity features will use cumulative annual "
            "installation totals as January 1 step changes, rather than exact "
            "installation timestamps.",
            UserWarning,
            stacklevel=2,
        )

    return stations, chargers, sessions


def _iqr_outlier_count(values: pd.Series) -> int:
    first_quartile, third_quartile = values.quantile([0.25, 0.75])
    spread = third_quartile - first_quartile
    return int(
        (
            values.lt(first_quartile - 1.5 * spread)
            | values.gt(third_quartile + 1.5 * spread)
        ).sum()
    )


def _print_dataset_inspection(
    stations: pd.DataFrame,
    chargers: pd.DataFrame,
    sessions: pd.DataFrame,
) -> None:
    print("Dataset inspection:")
    for name, frame, key in (
        ("stations", stations, "station_id"),
        ("chargers", chargers, "charger_id"),
        ("sessions", sessions, "session_id"),
    ):
        duplicates = int(frame[key].duplicated().sum())
        print(
            f"  {name}: {len(frame):,} rows, {len(frame.columns)} columns, "
            f"{int(frame.isna().sum().sum()):,} missing cells, "
            f"{duplicates:,} duplicate {key} values"
        )
        print(f"    columns: {', '.join(map(str, frame.columns))}")

    timestamps = sessions["start_timestamp"]
    print(
        "  session timestamp: "
        f"{timestamps.min()} to {timestamps.max()} (timezone-naive local values)"
    )
    for column in ("energy_kwh", "session_duration_minutes", "total_cost"):
        values = sessions[column]
        print(
            f"  {column}: min={values.min():g}, max={values.max():g}, "
            f"negative={int(values.lt(0).sum()):,}, "
            f"IQR outliers={_iqr_outlier_count(values):,}"
        )


def _capacity_features(
    index: pd.DatetimeIndex,
    stations: pd.DataFrame,
    chargers: pd.DataFrame,
) -> pd.DataFrame:
    # Treat each year's installed capacity as active from January 1. Exact
    # installation timestamps conflict with session activity in this workbook.
    activation_years = np.sort(stations["activation_year"].to_numpy())
    active_stations = np.searchsorted(activation_years, index.year, side="right")

    additions = chargers.groupby(chargers["installation_date"].dt.year).size().sort_index()
    annual_capacity = additions.cumsum()
    years = annual_capacity.index.to_numpy(dtype=int)
    capacity = annual_capacity.to_numpy(dtype=int)
    positions = np.searchsorted(years, index.year, side="right") - 1
    active_chargers = np.zeros(len(index), dtype="int64")
    has_capacity = positions >= 0
    active_chargers[has_capacity] = capacity[positions[has_capacity]]

    return pd.DataFrame(
        {
            "active_stations": active_stations.astype("int64"),
            "active_chargers": active_chargers.astype("int64"),
        },
        index=index,
    )


def _aggregate_sessions(
    sessions: pd.DataFrame, bucket: str, index: pd.DatetimeIndex
) -> pd.DataFrame:
    grouped = sessions.groupby(sessions["start_timestamp"].dt.floor(bucket)).agg(
        **AGGREGATIONS
    )
    grouped.index.name = "timestamp" if bucket == "h" else "date"
    result = grouped.reindex(index)
    result[["energy_kwh", "session_count", "total_revenue", "avg_duration_min"]] = (
        result[
            ["energy_kwh", "session_count", "total_revenue", "avg_duration_min"]
        ].fillna(0)
    )
    result["session_count"] = result["session_count"].astype("int64")
    return result


def _calendar_features(index: pd.DatetimeIndex) -> pd.DataFrame:
    holiday_calendar = holidays.country_holidays(
        "GB", years=range(index.min().year, index.max().year + 1)
    )
    return pd.DataFrame(
        {
            "day_of_week": index.dayofweek,
            "is_weekend": (index.dayofweek >= 5).astype("int8"),
            "month": index.month,
            "quarter": index.quarter,
            "year": index.year,
            "is_uk_bank_holiday": [
                int(day.date() in holiday_calendar) for day in index
            ],
        },
        index=index,
    )


def _segmented_daily(sessions: pd.DataFrame) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    dated_sessions = sessions.assign(date=sessions["start_timestamp"].dt.normalize())

    for dimension, source_column in SEGMENT_COLUMNS.items():
        segment = (
            dated_sessions.groupby(["date", source_column], as_index=False)
            .agg(**AGGREGATIONS)
            .rename(columns={source_column: "segment_value"})
        )
        segment.insert(1, "segment_dimension", dimension)
        rows.append(segment)

    result = pd.concat(rows, ignore_index=True)
    return result.sort_values(
        ["date", "segment_dimension", "segment_value"], kind="stable"
    ).reset_index(drop=True)


def prepare_datasets(
    input_path: Path = DEFAULT_INPUT,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Path]:
    """Validate the workbook and write the three processed CSV datasets."""
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    if not input_path.is_file():
        raise FileNotFoundError(
            f"Input workbook not found: {input_path}. Place it at "
            f"'{DEFAULT_INPUT}' or pass --input with its location."
        )

    workbook = pd.ExcelFile(input_path, engine="openpyxl")
    expected_sheets = {"stations", "chargers", "sessions"}
    missing_sheets = sorted(expected_sheets.difference(workbook.sheet_names))
    if missing_sheets:
        raise ValueError(
            "Workbook is missing required sheets: " + ", ".join(missing_sheets)
        )

    stations, chargers, sessions = _validate_inputs(
        pd.read_excel(workbook, sheet_name="stations"),
        pd.read_excel(workbook, sheet_name="chargers"),
        pd.read_excel(workbook, sheet_name="sessions"),
    )
    _print_dataset_inspection(stations, chargers, sessions)

    hourly_index = pd.date_range(START, END, freq="h", name="timestamp")
    daily_index = pd.date_range(START.normalize(), END.normalize(), freq="D", name="date")

    hourly = _aggregate_sessions(sessions, "h", hourly_index)
    hourly = hourly.join(_capacity_features(hourly_index, stations, chargers))

    daily = _aggregate_sessions(sessions, "D", daily_index)
    daily = daily.join(_capacity_features(daily_index, stations, chargers))
    daily = daily.join(_calendar_features(daily_index))

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "hourly": output_dir / "hourly_demand.csv",
        "daily": output_dir / "daily_demand.csv",
        "segmented": output_dir / "daily_demand_segmented.csv",
    }
    hourly.to_csv(outputs["hourly"], index_label="timestamp")
    daily.to_csv(outputs["daily"], index_label="date", date_format="%Y-%m-%d")
    _segmented_daily(sessions).to_csv(
        outputs["segmented"], index=False, date_format="%Y-%m-%d"
    )

    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build continuous EV charging demand time series from Excel."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="Path to ev_charging_dataset.xlsx (default: data/raw/).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for processed CSV files (default: data/processed/).",
    )
    args = parser.parse_args()

    outputs = prepare_datasets(args.input, args.output_dir)
    print("Processed datasets written:")
    for name, path in outputs.items():
        print(f"  {name}: {path}")
    print(
        "Capacity assumption: stations use activation_year and chargers use "
        "cumulative annual installation totals as January 1 step changes."
    )


if __name__ == "__main__":
    main()
