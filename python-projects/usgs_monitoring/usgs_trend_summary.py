#!/usr/bin/env python3
"""
USGS summary + trend for one monitoring location.

Defaults:
  site: 05427948
  parameter: 00010 water temperature

Examples:
  python usgs_trend_summary.py
  python usgs_trend_summary.py --site 05428500 --parameter 00065 --trend-hours 24
  python usgs_trend_summary.py --site 05428500 --parameter 00060 --history-days 30 --trend-hours 168
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

import requests


PARAMETERS = {
    "00010": "Water temperature",
    "00060": "Discharge",
    "00065": "Gage height",
}


def fetch_values(site: str, parameter: str, history_days: int) -> dict:
    """Fetch USGS instantaneous values for a site and parameter."""
    url = "https://waterservices.usgs.gov/nwis/iv/"

    params = {
        "format": "json",
        "sites": site,
        "parameterCd": parameter,
        "period": f"P{history_days}D",
        "siteStatus": "all",
    }

    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def parse_timeseries(data: dict) -> tuple[str, str, str, list[tuple[datetime, float]]]:
    """Parse USGS JSON into site metadata and sorted timestamp/value pairs."""
    series_list = data.get("value", {}).get("timeSeries", [])
    if not series_list:
        raise ValueError("No time series returned for this site/parameter.")

    series = series_list[0]
    source_info = series.get("sourceInfo", {})
    variable = series.get("variable", {})

    site_name = source_info.get("siteName", "Unknown site")
    variable_name = variable.get("variableName", "Unknown variable")
    unit = variable.get("unit", {}).get("unitCode", "")

    values_blocks = series.get("values", [])
    if not values_blocks or not values_blocks[0].get("value"):
        raise ValueError("No values returned for this site/parameter.")

    points: list[tuple[datetime, float]] = []

    for item in values_blocks[0]["value"]:
        raw_value = item.get("value")
        raw_time = item.get("dateTime")

        if raw_value is None or raw_time is None:
            continue

        try:
            value = float(raw_value)
            timestamp = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
        except ValueError:
            continue

        points.append((timestamp, value))

    points.sort(key=lambda x: x[0])

    if not points:
        raise ValueError("No numeric values found.")

    return site_name, variable_name, unit, points


def percentile(sorted_values: list[float], pct: float) -> float:
    """Calculate percentile using linear interpolation."""
    if not sorted_values:
        raise ValueError("Cannot calculate percentile of empty list.")

    if len(sorted_values) == 1:
        return sorted_values[0]

    index = (len(sorted_values) - 1) * pct
    lower = int(index)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = index - lower

    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * fraction


def summarize(points: list[tuple[datetime, float]]) -> dict:
    """Return min, quartiles, max, and current value."""
    values = sorted(value for _, value in points)
    current_time, current_value = points[-1]

    return {
        "min": values[0],
        "q1": percentile(values, 0.25),
        "median": percentile(values, 0.50),
        "q3": percentile(values, 0.75),
        "max": values[-1],
        "current_time": current_time,
        "current_value": current_value,
    }


def calculate_trend(
    points: list[tuple[datetime, float]],
    trend_hours: float,
) -> dict:
    """Calculate delta between latest value and value closest to N hours earlier."""
    current_time, current_value = points[-1]
    target_time = current_time - timedelta(hours=trend_hours)

    prior_time, prior_value = min(
        points,
        key=lambda point: abs(point[0] - target_time),
    )

    delta = current_value - prior_value

    return {
        "target_time": target_time,
        "prior_time": prior_time,
        "prior_value": prior_value,
        "delta": delta,
    }


def format_time(timestamp: datetime) -> str:
    """Format timestamp for display."""
    return timestamp.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def main() -> None:
    """Run command-line USGS trend summary."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", default="05427948", help="USGS site identifier")
    parser.add_argument(
        "--parameter",
        default="00010",
        choices=PARAMETERS.keys(),
        help="USGS parameter code",
    )
    parser.add_argument(
        "--history-days",
        type=int,
        default=7,
        help="Days of history used for min/max/quartiles",
    )
    parser.add_argument(
        "--trend-hours",
        type=float,
        default=24,
        help="Trend window in hours; valid range is 1 to 168",
    )

    args = parser.parse_args()

    if not 1 <= args.trend_hours <= 168:
        raise ValueError("--trend-hours must be between 1 and 168 hours.")

    data = fetch_values(args.site, args.parameter, args.history_days)
    site_name, variable_name, unit, points = parse_timeseries(data)

    stats = summarize(points)
    trend = calculate_trend(points, args.trend_hours)

    sign = "+" if trend["delta"] >= 0 else ""

    print(f"\nUSGS {args.site} — {site_name}")
    print(f"Parameter: {PARAMETERS.get(args.parameter, variable_name)} ({args.parameter})")
    print(f"History window: {args.history_days} days")
    print("-" * 72)

    print(f"Current: {stats['current_value']:.3f} {unit}")
    print(f"Current timestamp: {format_time(stats['current_time'])}")

    print("\nSummary statistics")
    print(f"Min:    {stats['min']:.3f} {unit}")
    print(f"Q1:     {stats['q1']:.3f} {unit}")
    print(f"Median: {stats['median']:.3f} {unit}")
    print(f"Q3:     {stats['q3']:.3f} {unit}")
    print(f"Max:    {stats['max']:.3f} {unit}")

    print(f"\nTrend over last {args.trend_hours:g} hours")
    print(f"Comparison timestamp: {format_time(trend['prior_time'])}")
    print(f"Comparison value:     {trend['prior_value']:.3f} {unit}")
    print(f"Delta:                {sign}{trend['delta']:.3f} {unit}")


if __name__ == "__main__":
    main()
