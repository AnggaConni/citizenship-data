#!/usr/bin/env python3
"""Build an authenticated UN Comtrade country-level trade snapshot for geopark analysis.

The snapshot is committed as public aggregate data. API credentials are used only
inside GitHub Actions and are never written to JSON or exposed to browser code.
These national trade indicators are context, not estimates of geopark-level impact.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPORTERS = (
    "IDN", "MYS", "THA", "VNM", "PHL", "CHN", "JPN", "KOR", "IND", "LKA",
    "NPL", "BGD", "PAK", "IRN", "TUR", "KAZ", "UZB", "KGZ", "TJK", "MNG",
    "AUS", "NZL", "PNG", "FJI", "CAN", "USA", "MEX", "BRA", "CHL", "PER",
    "URY", "COL", "ECU", "NIC", "CUB", "ESP", "PRT", "FRA", "DEU", "ITA",
    "GRC", "HRV", "ROU", "POL", "CZE", "SVK", "HUN", "SVN", "AUT", "CHE",
    "BEL", "NLD", "LUX", "GBR", "IRL", "ISL", "NOR", "SWE", "FIN", "MAR",
    "SEN", "KEN", "ETH", "UGA", "TZA", "ZAF", "JOR", "OMN", "SAU", "AZE",
    "GEO", "ARM", "ALB", "MKD", "SRB", "BIH", "BGR", "EST", "LVA", "LTU",
    "UKR", "RUS", "AND", "GTM", "HND", "SLV", "ARG", "BOL", "CRI", "PAN",
)
REPORTERS_URL = "https://comtradeapi.un.org/files/v1/app/reference/Reporters.json"
TRADE_URL = "https://comtradeapi.un.org/data/v1/get/C/A/HS"
USER_AGENT = "RegionalScienceObservatory/1.0 (public open-data research prototype)"
MAX_RECORDS = 5000


def request_json(url: str, *, headers: dict[str, str] | None = None, timeout: int = 60,
                 retries: int = 4) -> dict[str, Any]:
    request_headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    request_headers.update(headers or {})
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers=request_headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("UN Comtrade returned a non-object JSON response")
                return payload
        except urllib.error.HTTPError as error:
            last_error = error
            if error.code not in (429, 500, 502, 503, 504) or attempt >= retries:
                raise RuntimeError(f"UN Comtrade HTTP {error.code} for request") from error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as error:
            last_error = error
            if attempt >= retries:
                raise RuntimeError(f"UN Comtrade request failed: {error}") from error
        time.sleep(min(2 ** attempt, 12))
    raise RuntimeError(f"UN Comtrade request failed: {last_error}")


def reporter_lookup(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in payload.get("results", []):
        iso3 = str(row.get("reporterCodeIsoAlpha3") or "").strip().upper()
        if iso3 not in REPORTERS or row.get("isGroup") or row.get("entryExpiredDate"):
            continue
        try:
            code = int(row.get("reporterCode"))
        except (TypeError, ValueError):
            continue
        result[iso3] = {
            "reporterCode": code,
            "countryName": str(row.get("reporterDesc") or row.get("text") or iso3),
        }
    return result


def number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 and parsed < float("inf") else None


def aggregate_products(rows: list[dict[str, Any]]) -> dict[int, dict[str, dict[str, Any]]]:
    """Aggregate product groups by year and HS code without mixing years."""
    grouped: dict[int, dict[str, dict[str, Any]]] = {}
    for row in rows:
        raw_year = str(row.get("period") or "")
        if not raw_year.isdigit():
            continue
        year = int(raw_year)
        code = str(row.get("cmdCode") or "").strip()
        if not code or code.upper() in {"TOTAL", "AG2", "0"}:
            continue
        value = number(row.get("primaryValue"))
        product_map = grouped.setdefault(year, {})
        item = product_map.setdefault(code, {
            "code": code,
            "name": str(row.get("cmdDesc") or row.get("cmdCode") or "HS product group"),
            "valueUsd": 0.0,
            "hasValue": False,
            "records": 0,
        })
        item["records"] += 1
        if value is not None:
            item["valueUsd"] += value
            item["hasValue"] = True
        if not item["name"] or item["name"] == code:
            item["name"] = str(row.get("cmdDesc") or item["name"])
    return grouped


def build_country_record(iso3: str, reporter: dict[str, Any], rows: list[dict[str, Any]],
                         years_queried: list[int]) -> dict[str, Any]:
    grouped = aggregate_products(rows)
    nonempty_years = sorted(year for year, products in grouped.items()
                            if any(item["hasValue"] for item in products.values()))
    if not nonempty_years:
        return {
            "iso3": iso3,
            "reporterCode": reporter["reporterCode"],
            "countryName": reporter["countryName"],
            "available": False,
            "latestYear": None,
            "totalImportUsd": None,
            "recordCount": len(rows),
            "productCount": 0,
            "products": [],
            "yearsQueried": years_queried,
            "note": "No product-level import records were returned for the requested years.",
        }
    latest_year = nonempty_years[-1]
    products = list(grouped[latest_year].values())
    products = [item for item in products if item["hasValue"]]
    products.sort(key=lambda item: item["valueUsd"], reverse=True)
    total = sum(item["valueUsd"] for item in products)
    return {
        "iso3": iso3,
        "reporterCode": reporter["reporterCode"],
        "countryName": reporter["countryName"],
        "available": True,
        "latestYear": latest_year,
        "totalImportUsd": round(total, 2),
        "recordCount": sum(item["records"] for item in grouped[latest_year].values()),
        "productCount": len(products),
        "products": [
            {"code": item["code"], "name": item["name"],
             "valueUsd": round(item["valueUsd"], 2), "year": latest_year,
             "records": item["records"]}
            for item in products[:100]
        ],
        "yearsAvailable": nonempty_years,
        "yearsQueried": years_queried,
        "note": "Sum of returned HS 2-digit product-group imports for the latest available year; national total may be incomplete if source coverage is truncated.",
    }


def build_snapshot(api_key: str, *, now: datetime | None = None,
                   reporters: tuple[str, ...] = REPORTERS,
                   sleep_seconds: float = 0.2) -> dict[str, Any]:
    if not api_key.strip():
        raise ValueError("UN_COMTRADE_API_KEY is required; refusing to build a preview-limited snapshot.")
    now = now or datetime.now(timezone.utc)
    end_year = now.year - 1
    years = list(range(end_year - 3, end_year + 1))
    ref = reporter_lookup(request_json(REPORTERS_URL))
    countries: dict[str, Any] = {}
    failures: list[dict[str, str]] = []
    for index, iso3 in enumerate(reporters):
        reporter = ref.get(iso3)
        if not reporter:
            failures.append({"iso3": iso3, "reason": "Reporter code not found in UN Comtrade reference."})
            continue
        params = {
            "reporterCode": reporter["reporterCode"],
            "period": ",".join(map(str, years)),
            "cmdCode": "AG2",
            "flowCode": "M",
            "partnerCode": "0",
            "maxrecords": str(MAX_RECORDS),
            "includeDesc": "true",
        }
        url = TRADE_URL + "?" + urllib.parse.urlencode(params)
        try:
            payload = request_json(url, headers={"Ocp-Apim-Subscription-Key": api_key})
            rows = payload.get("data", [])
            if not isinstance(rows, list):
                raise RuntimeError("Unexpected data field in UN Comtrade response")
            countries[iso3] = build_country_record(iso3, reporter, rows, years)
            print(f"{iso3}: {len(rows)} records; {countries[iso3]['productCount']} products; year={countries[iso3]['latestYear']}")
        except Exception as error:  # Continue for other countries; expose each provider failure.
            failures.append({"iso3": iso3, "reason": str(error)[:300]})
            print(f"WARNING {iso3}: {error}")
        if index + 1 < len(reporters):
            time.sleep(max(0, sleep_seconds))
    available = sum(1 for item in countries.values() if item.get("available"))
    if not countries:
        raise RuntimeError("No UN Comtrade country records could be built.")
    return {
        "metadata": {
            "status": "ready",
            "source": "UN Comtrade API",
            "sourceUrl": "https://comtradeplus.un.org/",
            "mode": "authenticated",
            "generatedAt": now.isoformat().replace("+00:00", "Z"),
            "yearsQueried": years,
            "reportersRequested": len(reporters),
            "reportersIncluded": len(countries),
            "countriesAvailable": available,
            "maxRecordsPerCountry": MAX_RECORDS,
            "failures": failures,
            "interpretation": "National annual merchandise imports from reported HS 2-digit product groups. Not geopark-level revenue, tourism spend, employment, local production or community income.",
        },
        "countries": countries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="data/geopark-economic-trade.json")
    args = parser.parse_args()
    payload = build_snapshot(os.environ.get("UN_COMTRADE_API_KEY", ""))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output} with {payload['metadata']['countriesAvailable']} available country snapshots.")


if __name__ == "__main__":
    main()
