"""Generate seasonal charts and a data-backed EV demand insights report."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from forecasting_utils import PROJECT_ROOT


PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
FIGURES_DIR = PROJECT_ROOT / "outputs" / "figures"
REPORT_PATH = PROJECT_ROOT / "reports" / "task1_insights.md"


def _read_data() -> tuple[
    pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame
]:
    daily = pd.read_csv(PROCESSED_DIR / "daily_demand.csv", parse_dates=["date"])
    hourly = pd.read_csv(
        PROCESSED_DIR / "hourly_demand.csv", parse_dates=["timestamp"]
    )
    segmented = pd.read_csv(
        PROCESSED_DIR / "daily_demand_segmented.csv", parse_dates=["date"]
    )
    workbook = PROJECT_ROOT / "data" / "raw" / "ev_charging_dataset.xlsx"
    sessions = pd.read_excel(
        workbook,
        sheet_name="sessions",
        usecols=["charger_id", "start_timestamp", "energy_kwh", "user_type"],
        engine="openpyxl",
    )
    sessions["start_timestamp"] = pd.to_datetime(sessions["start_timestamp"])
    chargers = pd.read_excel(
        workbook,
        sheet_name="chargers",
        usecols=["charger_id", "installation_date"],
        engine="openpyxl",
    )
    chargers["installation_date"] = pd.to_datetime(chargers["installation_date"])
    return daily, hourly, segmented, sessions, chargers


def _write_charts(
    daily: pd.DataFrame,
    hourly: pd.DataFrame,
    segmented: pd.DataFrame,
    sessions: pd.DataFrame,
) -> None:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    sns.set_theme(style="whitegrid")

    profile = hourly.assign(
        hour=hourly["timestamp"].dt.hour,
        day_type=hourly["timestamp"].dt.dayofweek.map(
            lambda value: "Weekend" if value >= 5 else "Weekday"
        ),
    )
    hourly_profile = profile.groupby(["day_type", "hour"], as_index=False)[
        "energy_kwh"
    ].mean()
    figure, axis = plt.subplots(figsize=(11, 5))
    sns.lineplot(
        data=hourly_profile,
        x="hour",
        y="energy_kwh",
        hue="day_type",
        marker="o",
        ax=axis,
    )
    axis.set(title="Average hourly energy by day type", xlabel="Hour of day", ylabel="kWh")
    figure.tight_layout()
    figure.savefig(FIGURES_DIR / "hourly_daytype_profile.png", dpi=160)
    plt.close(figure)

    heatmap = profile.assign(day_of_week=profile["timestamp"].dt.dayofweek).pivot_table(
        index="day_of_week", columns="hour", values="energy_kwh", aggfunc="mean"
    )
    figure, axis = plt.subplots(figsize=(14, 5))
    sns.heatmap(heatmap, cmap="YlOrRd", ax=axis, cbar_kws={"label": "Mean kWh"})
    axis.set(
        title="Hour-of-day × day-of-week demand",
        xlabel="Hour of day",
        ylabel="Day of week (Monday=0)",
    )
    figure.tight_layout()
    figure.savefig(FIGURES_DIR / "hour_day_heatmap.png", dpi=160)
    plt.close(figure)

    monthly = daily.assign(
        month_start=daily["date"].dt.to_period("M").dt.to_timestamp(),
        kwh_per_charger=daily["energy_kwh"]
        / daily["active_chargers"].replace(0, pd.NA),
    )
    monthly = monthly.groupby("month_start", as_index=False).agg(
        mean_daily_kwh=("energy_kwh", "mean"),
        mean_daily_kwh_per_charger=("kwh_per_charger", "mean"),
    )
    figure, (axis, normalized_axis) = plt.subplots(
        2, 1, figsize=(12, 8), sharex=True
    )
    axis.plot(monthly["month_start"], monthly["mean_daily_kwh"], color="#176B87")
    axis.set(title="Monthly mean daily energy", ylabel="Mean daily kWh")
    normalized_axis.plot(
        monthly["month_start"],
        monthly["mean_daily_kwh_per_charger"],
        color="#E36B2C",
    )
    normalized_axis.set_ylabel("Mean daily kWh / active charger")
    axis.grid(alpha=0.25)
    normalized_axis.grid(alpha=0.25)
    figure.tight_layout()
    figure.savefig(FIGURES_DIR / "monthly_seasonality.png", dpi=160)
    plt.close(figure)

    regions = segmented.loc[
        segmented["segment_dimension"] == "station_region"
    ].groupby("segment_value")["energy_kwh"].sum().sort_values(ascending=False)
    figure, axis = plt.subplots(figsize=(11, 5))
    regions.sort_values().plot.barh(ax=axis, color="#3A7D44")
    axis.set(title="Historical energy by region", xlabel="Energy (kWh)", ylabel="")
    figure.tight_layout()
    figure.savefig(FIGURES_DIR / "regional_demand.png", dpi=160)
    plt.close(figure)

    users = segmented.loc[segmented["segment_dimension"] == "user_type"]
    user_totals = users.groupby("segment_value")["energy_kwh"].sum().sort_values(
        ascending=False
    )
    figure, axis = plt.subplots(figsize=(8, 5))
    user_totals.plot.bar(ax=axis, color="#E36B2C")
    axis.set(title="Historical energy by user type", ylabel="Energy (kWh)", xlabel="")
    axis.tick_params(axis="x", rotation=25)
    figure.tight_layout()
    figure.savefig(FIGURES_DIR / "user_type_demand.png", dpi=160)
    plt.close(figure)

    sessions = sessions.assign(
        date=sessions["start_timestamp"].dt.normalize(),
        hour=sessions["start_timestamp"].dt.hour,
        load_group=sessions["user_type"].map(
            lambda value: "Public" if value == "public" else "Commercial"
        ),
    )
    user_hourly = sessions.groupby(["load_group", "hour"])["energy_kwh"].sum()
    full_grid = pd.MultiIndex.from_product(
        [["Commercial", "Public"], range(24)], names=["load_group", "hour"]
    )
    user_hourly = user_hourly.reindex(full_grid, fill_value=0).rename(
        "energy_kwh"
    ).reset_index()
    user_hourly["mean_hourly_kwh"] = user_hourly["energy_kwh"] / daily["date"].nunique()
    figure, axis = plt.subplots(figsize=(11, 5))
    sns.lineplot(
        data=user_hourly,
        x="hour",
        y="mean_hourly_kwh",
        hue="load_group",
        marker="o",
        ax=axis,
    )
    axis.set(
        title="Mean hourly load: commercial vs public",
        xlabel="Hour of day",
        ylabel="Mean kWh per calendar day",
    )
    figure.tight_layout()
    figure.savefig(FIGURES_DIR / "commercial_public_hourly_profile.png", dpi=160)
    plt.close(figure)

def _build_report(
    daily: pd.DataFrame,
    hourly: pd.DataFrame,
    segmented: pd.DataFrame,
    sessions: pd.DataFrame,
    chargers: pd.DataFrame,
) -> str:
    daily = daily.copy()
    hourly = hourly.copy()
    daily["day_type"] = daily["is_weekend"].map({0: "Weekday", 1: "Weekend"})
    daily["energy_per_active_charger"] = daily["energy_kwh"] / daily[
        "active_chargers"
    ].replace(0, pd.NA)
    weekly = daily.groupby("day_type").agg(
        mean_daily_kwh=("energy_kwh", "mean"),
        mean_kwh_per_active_charger=("energy_per_active_charger", "mean"),
    )
    weekday_total = float(weekly.loc["Weekday", "mean_daily_kwh"])
    weekend_total = float(weekly.loc["Weekend", "mean_daily_kwh"])
    weekday_per_charger = float(weekly.loc["Weekday", "mean_kwh_per_active_charger"])
    weekend_per_charger = float(weekly.loc["Weekend", "mean_kwh_per_active_charger"])
    weekday_shift = (weekend_total / weekday_total - 1) * 100
    per_charger_shift = (weekend_per_charger / weekday_per_charger - 1) * 100

    hourly["hour"] = hourly["timestamp"].dt.hour
    peak_hours = hourly.loc[hourly["hour"].between(10, 14), "energy_kwh"].sum()
    overnight_hours = hourly.loc[hourly["hour"].between(0, 5), "energy_kwh"].sum()
    total_hourly = hourly["energy_kwh"].sum()
    peak_share = peak_hours / total_hourly * 100
    hourly["date"] = hourly["timestamp"].dt.normalize()
    mean_peak_slot = (
        hourly.loc[hourly["hour"].between(10, 14)]
        .groupby("date")["energy_kwh"]
        .sum()
        .mean()
    )
    mean_overnight_slot = (
        hourly.loc[hourly["hour"].between(0, 5)]
        .groupby("date")["energy_kwh"]
        .sum()
        .mean()
    )

    daily["month"] = daily["date"].dt.month
    daily["quarter"] = daily["date"].dt.quarter
    monthly = daily.groupby("month")["energy_kwh"].mean()
    quarter = daily.groupby("quarter")["energy_kwh"].mean()
    daily["kwh_per_active_charger"] = daily["energy_kwh"] / daily[
        "active_chargers"
    ].replace(0, pd.NA)
    monthly_per_charger = daily.groupby("month")["kwh_per_active_charger"].mean()
    quarter_per_charger = daily.groupby("quarter")[
        "kwh_per_active_charger"
    ].mean()
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    peak_month = int(monthly.idxmax())
    low_month = int(monthly.idxmin())
    peak_month_per_charger = int(monthly_per_charger.idxmax())
    low_month_per_charger = int(monthly_per_charger.idxmin())
    peak_quarter = int(quarter.idxmax())
    low_quarter = int(quarter.idxmin())
    peak_quarter_per_charger = int(quarter_per_charger.idxmax())
    low_quarter_per_charger = int(quarter_per_charger.idxmin())

    regions = (
        segmented.loc[segmented["segment_dimension"] == "station_region"]
        .groupby("segment_value")["energy_kwh"]
        .sum()
        .sort_values(ascending=False)
    )
    total_regional = regions.sum()
    top_region = str(regions.index[0])
    top_region_share = float(regions.iloc[0] / total_regional * 100)
    top_three_share = float(regions.iloc[:3].sum() / total_regional * 100)

    users = (
        segmented.loc[segmented["segment_dimension"] == "user_type"]
        .groupby("segment_value")["energy_kwh"]
        .sum()
    )
    commercial_types = {"fleet", "delivery", "taxi"}
    commercial_kwh = float(
        users.loc[users.index.isin(commercial_types)].sum()
    )
    public_kwh = float(users.get("public", 0.0))
    total_user_kwh = float(users.sum())
    commercial_share = commercial_kwh / total_user_kwh * 100
    public_share = public_kwh / total_user_kwh * 100
    sessions["date"] = sessions["start_timestamp"].dt.normalize()
    sessions["hour"] = sessions["start_timestamp"].dt.hour
    session_install_dates = sessions["charger_id"].map(
        chargers.set_index("charger_id")["installation_date"]
    )
    preinstallation_sessions = int(
        (sessions["start_timestamp"] < session_install_dates).sum()
    )
    daily_by_user = sessions.pivot_table(
        index="date", columns="user_type", values="energy_kwh", aggfunc="sum", fill_value=0
    ).reindex(index=pd.DatetimeIndex(daily["date"]), fill_value=0)
    weekday_mask = daily.set_index("date")["is_weekend"] == 0
    weekend_mask = daily.set_index("date")["is_weekend"] == 1
    user_profile_rows = []
    user_hour_profiles: dict[str, pd.Series] = {}
    for user in sorted(users.index):
        sessions_for_user = sessions.loc[sessions["user_type"] == user]
        profile = sessions_for_user.pivot_table(
            index="date",
            columns="hour",
            values="energy_kwh",
            aggfunc="sum",
            fill_value=0,
        ).reindex(index=pd.DatetimeIndex(daily["date"]), columns=range(24), fill_value=0)
        mean_hourly = profile.mean(axis=0)
        user_hour_profiles[user] = mean_hourly
        energy_profile = daily_by_user[user] if user in daily_by_user.columns else 0
        user_profile_rows.append(
            (
                user,
                float(users[user]),
                float(users[user] / total_user_kwh * 100),
                float(energy_profile.loc[weekday_mask.index[weekday_mask]].mean()),
                float(energy_profile.loc[weekend_mask.index[weekend_mask]].mean()),
                float(profile.loc[:, 10:14].to_numpy().sum() / profile.to_numpy().sum() * 100),
                int(mean_hourly.idxmax()),
            )
        )
    user_share_lines = "\n".join(
        f"| {user} | {energy:,.0f} | {share:.1f}% | {weekday:,.1f} | "
        f"{weekend:,.1f} | {peak_share:.1f}% | {peak_hour:02d}:00 |"
        for user, energy, share, weekday, weekend, peak_share, peak_hour in sorted(
            user_profile_rows, key=lambda row: row[1], reverse=True
        )
    )
    combined_hourly = pd.DataFrame(user_hour_profiles)
    combined_hourly["Commercial"] = combined_hourly[
        [user for user in ("fleet", "delivery", "taxi") if user in combined_hourly]
    ].sum(axis=1)
    combined_hourly["Public"] = combined_hourly.get("public", 0.0)
    commercial_peak_hour = int(combined_hourly["Commercial"].idxmax())
    public_peak_hour = int(combined_hourly["Public"].idxmax())

    return f"""# Task 1: EV Charging Demand — EDA and Insights

## Data and method

The findings below are calculated from the supplied 2022–2024 session records and the processed continuous hourly/daily files. Network rollout is material: comparisons include both total demand and average demand per active charger where relevant. Station active counts use `activation_year` as a January 1 step change. {preinstallation_sessions:,} sessions have a start timestamp earlier than their charger's recorded installation date, so charger capacity is also represented as a January 1 step change using cumulative annual installation totals (43, 102, and 199 chargers). This avoids using contradictory within-year installation dates as an exact exposure timeline. These are descriptive findings, not causal estimates.

## Weekday and weekend demand

| Day type | Mean daily energy (kWh) | Mean daily kWh per active charger |
|---|---:|---:|
| Weekday | {weekday_total:,.1f} | {weekday_per_charger:,.1f} |
| Weekend | {weekend_total:,.1f} | {weekend_per_charger:,.1f} |

Weekend total mean demand is {weekday_shift:+.1f}% relative to weekdays; the per-active-charger comparison is {per_charger_shift:+.1f}%. Use the per-charger comparison when setting routine staffing and capacity baselines, and the total-demand comparison for network-wide procurement.

## Hour-of-day profile

Hours 10:00–14:00 account for {peak_share:.1f}% of energy across the observed period. Mean daily energy summed across those five hours is {mean_peak_slot:,.1f} kWh, compared with {mean_overnight_slot:,.1f} kWh during 00:00–05:00. Prioritize staffing and charger availability around the measured peak window; use the overnight profile to identify practical windows for maintenance and any flexible procurement or charging incentives.

![Hourly day-type profile](../outputs/figures/hourly_daytype_profile.png)

![Hour-by-weekday heatmap](../outputs/figures/hour_day_heatmap.png)

## Monthly and quarterly seasonality

Mean daily demand is highest in {month_names[peak_month - 1]} ({monthly.loc[peak_month]:,.1f} kWh/day) and lowest in {month_names[low_month - 1]} ({monthly.loc[low_month]:,.1f} kWh/day). After normalizing for active chargers, the highest monthly mean is {month_names[peak_month_per_charger - 1]} ({monthly_per_charger.loc[peak_month_per_charger]:,.1f} kWh/charger/day) and the lowest is {month_names[low_month_per_charger - 1]} ({monthly_per_charger.loc[low_month_per_charger]:,.1f} kWh/charger/day). By quarter, total demand peaks in Q{peak_quarter} ({quarter.loc[peak_quarter]:,.1f} kWh/day) and is lowest in Q{low_quarter} ({quarter.loc[low_quarter]:,.1f} kWh/day); normalized demand peaks in Q{peak_quarter_per_charger} ({quarter_per_charger.loc[peak_quarter_per_charger]:,.1f} kWh/charger/day) and is lowest in Q{low_quarter_per_charger} ({quarter_per_charger.loc[low_quarter_per_charger]:,.1f} kWh/charger/day). Review both series before attributing changes to seasonality.

![Monthly seasonality](../outputs/figures/monthly_seasonality.png)

## Regional concentration

The largest regional share is {top_region} at {top_region_share:.1f}% of region-tagged energy; the three largest regions together account for {top_three_share:.1f}%. Allocate capacity review and local procurement attention in proportion to regional load, while validating utilization and station outages before adding hardware.

![Regional demand](../outputs/figures/regional_demand.png)

## User type and commercial load

| User type | Historical energy (kWh) | Share | Mean weekday kWh/day | Mean weekend kWh/day | Energy share 10:00–14:00 | Mean-load peak hour |
|---|---:|---:|---:|---:|---:|---|
{user_share_lines}

Commercial user categories (fleet, delivery, taxi) account for {commercial_share:.1f}% of categorized energy; public charging accounts for {public_share:.1f}%. The mean-load peak hours are {commercial_peak_hour:02d}:00 for combined commercial charging and {public_peak_hour:02d}:00 for public charging. Use the weekday/weekend and hourly figures to align commercial account scheduling and staffing with when that load arrives. Public-facing staffing and communications should be planned around the separate weekend and daytime profile rather than assuming a single network-wide schedule.

![Demand by user type](../outputs/figures/user_type_demand.png)

![Commercial vs public hourly profile](../outputs/figures/commercial_public_hourly_profile.png)

## Operational recommendations

1. **Capacity planning:** baseline near-term capacity from active-charger-normalized demand and the explicit rollout regressor; investigate high-utilization stations before broad expansion.
2. **Staffing:** use the measured hourly and day-type profiles to stagger coverage toward the 10:00–14:00 peak, then tune the schedule by region and user mix.
3. **Energy procurement:** combine the seasonal monthly profile with forecast scenarios and a reserve informed by the 80%/95% intervals; treat the 199-charger forecast as a fixed-capacity scenario, not an expansion plan.
4. **Commercial operations:** coordinate fleet, delivery, and taxi charging windows where the observed load profile permits, protecting public access at shared stations.

These recommendations should be revisited as new operational data arrives; the descriptive pattern can reflect both demand shifts and the network's staged rollout.
"""


def run_eda() -> Path:
    daily, hourly, segmented, sessions, chargers = _read_data()
    _write_charts(daily, hourly, segmented, sessions)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        _build_report(daily, hourly, segmented, sessions, chargers), encoding="utf-8"
    )
    return REPORT_PATH


if __name__ == "__main__":
    print(f"EDA report written: {run_eda()}")
