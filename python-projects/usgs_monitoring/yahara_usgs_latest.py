#!/usr/bin/env python3
"""
Fetch latest USGS water temp, discharge, and gage height for selected Yahara-area sites.

Parameters:
  00010 = Water temperature, deg C
  00060 = Discharge, ft^3/s
  00065 = Gage height, ft
"""

from __future__ import annotations

import requests


SITES = [
    "05429000",
    "05428500",
    "05428000",
    "05427880",
    "05427948",
]

PARAMETERS = {
    "00010": "Water Temp",
    "00060": "Discharge",
    "00065": "Gage Height",
}

UNITS_FALLBACK = {
    "00010": "deg C",
    "00060": "ft³/s",
    "00065": "ft",
}


def fetch_usgs_values(sites: list[str], parameter_codes: list[str]) -> dict:
    """Fetch recent instantaneous USGS values for sites and parameters."""
    url = "https://waterservices.usgs.gov/nwis/iv/"

    params = {
        "format": "json",
        "sites": ",".join(sites),
        "parameterCd": ",".join(parameter_codes),
        "period": "P1D",
        "siteStatus": "all",
    }

    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def parse_latest_values(data: dict) -> list[dict]:
    """Parse the latest available value from each returned time series."""
    results = []

    time_series = data.get("value", {}).get("timeSeries", [])

    for series in time_series:
        source_info = series.get("sourceInfo", {})
        variable = series.get("variable", {})

        site_code = source_info.get("siteCode", [{}])[0].get("value", "unknown")
        site_name = source_info.get("siteName", "unknown")

        param_code = variable.get("variableCode", [{}])[0].get("value", "unknown")
        param_name = PARAMETERS.get(param_code, variable.get("variableName", param_code))

        unit = (
            variable.get("unit", {}).get("unitCode")
            or UNITS_FALLBACK.get(param_code, "")
        )

        values_blocks = series.get("values", [])
        if not values_blocks:
            continue

        values = values_blocks[0].get("value", [])
        if not values:
            continue

        latest = values[-1]

        results.append(
            {
                "site_code": site_code,
                "site_name": site_name,
                "parameter_code": param_code,
                "parameter_name": param_name,
                "value": latest.get("value"),
                "unit": unit,
                "timestamp": latest.get("dateTime"),
                "qualifiers": ",".join(latest.get("qualifiers", [])),
            }
        )

    return results


def print_results(results: list[dict]) -> None:
    """Print latest values grouped by site."""
    by_site: dict[str, list[dict]] = {}

    for row in results:
        by_site.setdefault(row["site_code"], []).append(row)

    for site_code in sorted(by_site):
        site_rows = by_site[site_code]
        site_name = site_rows[0]["site_name"]

        print(f"\n{site_code} — {site_name}")
        print("-" * 72)

        for row in sorted(site_rows, key=lambda x: x["parameter_code"]):
            qualifier_text = f" [{row['qualifiers']}]" if row["qualifiers"] else ""
            print(
                f"{row['parameter_name']:14s} "
                f"({row['parameter_code']}): "
                f"{row['value']} {row['unit']} "
                f"at {row['timestamp']}{qualifier_text}"
            )


def main() -> None:
    """Run the USGS data fetch and display results."""
    data = fetch_usgs_values(SITES, list(PARAMETERS.keys()))
    results = parse_latest_values(data)

    if not results:
        print("No recent values returned.")
        return

    print_results(results)


if __name__ == "__main__":
    main()
