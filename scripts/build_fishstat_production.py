#!/usr/bin/env python3
"""Build a lightweight country/year FishStat series from FAO's public global-production ZIP.

The output aggregates FAO-reported species and fishing-area rows into national totals
for capture production and aquaculture production. It is a production indicator, not
a measure of seafood availability, per-capita consumption, sustainability, or food security.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

INDEX_URL = "https://www.fao.org/fishery/static/Data/"
SOURCE_PAGE = "https://www.fao.org/fishery/en/collection/global_production"
DEFAULT_START_YEAR = 2000
USER_AGENT = "RegionalScienceObservatory/1.0 (open-data research prototype)"


def norm_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def pick(row: Mapping[str, object], *keys: str) -> str:
    normalized = {norm_key(k): v for k, v in row.items()}
    for key in keys:
        value = normalized.get(norm_key(key))
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return ""


def norm_code(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if re.fullmatch(r"\d+\.0+", raw):
        return raw.split(".", 1)[0]
    return raw


def parse_number(value: object) -> float | None:
    raw = str(value or "").strip().replace(",", "")
    if not raw or raw in {"-", "..", "...", "NaN", "nan", "N/A", "n/a"}:
        return None
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def classify_source(name: str) -> str | None:
    value = re.sub(r"\s+", " ", (name or "").strip().lower())
    if "capture production" in value:
        return "Capture production"
    if "aquaculture production" in value:
        return "Aquaculture production"
    return None


def build_records(
    production_rows: Iterable[Mapping[str, object]],
    country_rows: Iterable[Mapping[str, object]],
    source_rows: Iterable[Mapping[str, object]],
    start_year: int = DEFAULT_START_YEAR,
) -> list[dict[str, object]]:
    countries: dict[str, dict[str, str]] = {}
    for row in country_rows:
        code = norm_code(pick(row, "un_code", "country_un_code", "un code"))
        name = pick(row, "name_en", "country", "name")
        if code and name:
            countries[code] = {
                "countryCode": pick(row, "iso2_code", "iso2", "iso alpha 2"),
                "countryName": name,
                "unCode": code,
            }

    source_names: dict[str, str] = {}
    for row in source_rows:
        code = norm_code(pick(row, "code", "production_source_det_code", "source_code"))
        name = pick(row, "name_en", "name", "production_source_detailed_name")
        if code and name:
            source_names[code] = name

    totals: dict[tuple[str, int, str], dict[str, object]] = {}
    for row in production_rows:
        country_key = norm_code(pick(row, "country_un_code", "un_code", "country_code"))
        country = countries.get(country_key)
        if not country:
            # Do not accidentally publish FAO regional/aggregate rows as countries.
            continue

        year_text = pick(row, "period", "year", "time_period")
        try:
            year = int(float(year_text))
        except (TypeError, ValueError):
            continue
        if year < start_year:
            continue

        measure = pick(row, "measure", "unit", "measure_code").upper()
        if measure != "Q_TLW":
            # Only tonnes in live weight are aggregated; counts of individual
            # organisms are not mixed into the biomass series.
            continue

        detailed_code = norm_code(pick(row, "production_source_det_code", "source_code"))
        detailed_name = source_names.get(
            detailed_code,
            pick(row, "production_source_detailed_name", "production_source_name"),
        )
        source = classify_source(detailed_name)
        if not source:
            continue

        value = parse_number(pick(row, "value", "quantity", "obs_value"))
        if value is None:
            continue

        key = (country_key, year, source)
        if key not in totals:
            totals[key] = {
                **country,
                "year": year,
                "unit": "tonnes live weight",
                "source": source,
                "value": 0.0,
                "componentCount": 0,
                "flags": set(),
            }
        item = totals[key]
        item["value"] = float(item["value"]) + value
        item["componentCount"] = int(item["componentCount"]) + 1
        flag = pick(row, "status", "flag", "status_flag")
        if flag:
            flags = item["flags"]
            assert isinstance(flags, set)
            flags.add(flag)

    records: list[dict[str, object]] = []
    for item in totals.values():
        value = round(float(item["value"]), 3)
        if value.is_integer():
            clean_value: int | float = int(value)
        else:
            clean_value = value
        flags = sorted(item["flags"]) if isinstance(item["flags"], set) else []
        records.append({
            "countryCode": item["countryCode"],
            "countryName": item["countryName"],
            "unCode": item["unCode"],
            "year": item["year"],
            "source": item["source"],
            "unit": item["unit"],
            "value": clean_value,
            "componentCount": item["componentCount"],
            "sourceFlags": flags,
            "sourceUrl": SOURCE_PAGE,
        })

    records.sort(key=lambda r: (str(r["countryName"]).casefold(), int(r["year"]), str(r["source"])))
    return records


def fetch_bytes(url: str, timeout: int = 90) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def latest_fishstat_release(index_html: str) -> tuple[str, str]:
    matches = re.findall(
        r"""href=["']([^"']*GlobalProduction_(\d{4}\.\d+\.\d+)\.zip)["']""",
        index_html,
        flags=re.IGNORECASE,
    )
    if not matches:
        matches = re.findall(
            r"""(GlobalProduction_(\d{4}\.\d+\.\d+)\.zip)""",
            index_html,
            flags=re.IGNORECASE,
        )
    if not matches:
        raise RuntimeError("Could not find a GlobalProduction version in FAO's official download index.")
    filename, version = max(matches, key=lambda pair: tuple(int(x) for x in pair[1].split(".")))
    return version, filename


def iter_csv_member(archive: zipfile.ZipFile, basename: str):
    wanted = basename.casefold()
    member = next((name for name in archive.namelist() if Path(name).name.casefold() == wanted), None)
    if member is None:
        available = ", ".join(Path(name).name for name in archive.namelist() if name.lower().endswith(".csv"))
        raise RuntimeError(f"Missing {basename} in FAO ZIP. CSV members found: {available[:1200]}")
    with archive.open(member) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
        yield from csv.DictReader(text)


def build_payload(start_year: int = DEFAULT_START_YEAR) -> dict[str, object]:
    index_html = fetch_bytes(INDEX_URL).decode("utf-8", errors="replace")
    version, filename = latest_fishstat_release(index_html)
    zip_url = INDEX_URL + filename
    zip_bytes = fetch_bytes(zip_url)

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        countries = list(iter_csv_member(archive, "CL_FI_COUNTRY_GROUPS.csv"))
        sources = list(iter_csv_member(archive, "CL_FI_PRODUCTION_SOURCE_DET.csv"))
        production_rows = iter_csv_member(archive, "Global_production_quantity.csv")
        records = build_records(production_rows, countries, sources, start_year=start_year)

    if not records:
        raise RuntimeError("FAO source was downloaded, but no country production records passed the filters.")
    years = [int(row["year"]) for row in records]
    return {
        "metadata": {
            "status": "ready",
            "source": "FAO FishStat — Global Production",
            "sourceUrl": SOURCE_PAGE,
            "downloadUrl": zip_url,
            "release": version,
            "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "startYear": min(years),
            "endYear": max(years),
            "recordCount": len(records),
            "countries": len({str(row["countryCode"]) for row in records}),
            "unit": "tonnes live weight",
            "aggregation": "Country-year totals by capture/aquaculture source, summed from species and FAO fishing-area rows.",
            "interpretationLimit": "Production volume is not seafood consumption, household food security, stock health, or proof of sustainable fishing. Underlying source flags can differ between component rows.",
        },
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="data/fishstat-production.json")
    parser.add_argument("--start-year", type=int, default=DEFAULT_START_YEAR)
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = build_payload(start_year=args.start_year)
    output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(
        "Wrote {count} FAO FishStat country-year records ({start}-{end}) to {path}".format(
            count=payload["metadata"]["recordCount"],
            start=payload["metadata"]["startYear"],
            end=payload["metadata"]["endYear"],
            path=output,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
