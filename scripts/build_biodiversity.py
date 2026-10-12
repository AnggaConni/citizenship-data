#!/usr/bin/env python3
"""Build country-level GBIF occurrence samples and density-grid GeoJSON.

The output is a capped exploratory sample. Grid cells summarize returned
occurrence records; they are not species-range boundaries or habitat polygons.
Uses only the Python standard library.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_BASE = "https://api.gbif.org/v1"
REPOSITORY_URL = "https://github.com/AnggaConni/citizenship-data"
PAGE_SIZE = 300
MAX_RECORDS_PER_COUNTRY = 9900  # Keep search offsets below 10,000.
DEFAULT_RECORDS_PER_COUNTRY = 300
USER_AGENT = "OpenDataExplorers-BiodiversityPipeline/1.0"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "biodiversity"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def request_json(endpoint: str, params: dict | None = None, retries: int = 3) -> dict | list:
    url = f"{API_BASE}/{endpoint.lstrip('/')}"
    if params:
        url += "?" + urlencode(params)
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        request = Request(url, headers={
            "Accept": "application/json",
            "User-Agent": f"{USER_AGENT} (+{REPOSITORY_URL})",
        })
        try:
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            last_error = exc
            if exc.code not in (408, 425, 429, 500, 502, 503, 504) or attempt >= retries:
                break
        except (URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            last_error = exc
            if attempt >= retries:
                break
        time.sleep(min(8.0, 1.2 * (2 ** attempt)))
    raise RuntimeError(f"GBIF request failed for {url}: {last_error}") from last_error


def normalize_country(item: object) -> dict | None:
    if isinstance(item, dict):
        code = str(
            item.get("iso2") or item.get("iso2Code") or item.get("alpha2")
            or item.get("code") or ""
        ).strip().upper()
        name = str(
            item.get("title") or item.get("name") or item.get("label")
            or item.get("description") or code
        ).strip()
    elif isinstance(item, str):
        value = item.strip()
        if not re.fullmatch(r"[A-Za-z]{2}", value):
            return None
        code, name = value.upper(), value
    else:
        return None
    if not re.fullmatch(r"[A-Z]{2}", code) or code in {"XX", "ZZ"}:
        return None
    return {"code": code, "name": name or code}


def get_countries() -> list[dict]:
    raw = request_json("enumeration/country")
    if not isinstance(raw, list):
        raise RuntimeError("GBIF country enumeration response was not a list.")
    countries_by_code = {}
    for item in raw:
        country = normalize_country(item)
        if country:
            countries_by_code[country["code"]] = country
    if not countries_by_code:
        raise RuntimeError("No usable country codes were returned by GBIF.")
    return sorted(countries_by_code.values(), key=lambda row: row["name"].casefold())


def slugify_country(name: str, code: str = "") -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    text = text.lower().replace("&", " and ")
    slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return slug or code.lower() or "unknown-country"


def country_filenames(countries: list[dict]) -> dict[str, str]:
    bases = {row["code"]: slugify_country(row["name"], row["code"]) for row in countries}
    counts = Counter(bases.values())
    return {
        code: (f"{slug}-{code.lower()}" if counts[slug] > 1 else slug) + ".json"
        for code, slug in bases.items()
    }


def valid_coordinates(record: dict) -> tuple[float, float] | None:
    try:
        lat = float(record.get("decimalLatitude"))
        lon = float(record.get("decimalLongitude"))
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def stable_record_id(record: dict) -> str:
    key = record.get("key")
    if key not in (None, ""):
        return str(key)
    coords = valid_coordinates(record)
    return "|".join([
        str(record.get("speciesKey") or record.get("taxonKey") or record.get("scientificName") or ""),
        str(coords[0] if coords else ""),
        str(coords[1] if coords else ""),
        str(record.get("eventDate") or record.get("year") or ""),
    ])


def unique_records(records: list[dict]) -> list[dict]:
    seen: set[str] = set()
    output = []
    for record in records:
        identifier = stable_record_id(record)
        if identifier not in seen:
            seen.add(identifier)
            output.append(record)
    return output


def fetch_country_records(country_code: str, maximum: int) -> tuple[list[dict], int, int, list[dict]]:
    """Return unique records, GBIF total count, raw row count and page errors."""
    first = request_json("occurrence/search", {
        "country": country_code,
        "hasCoordinate": "true",
        "hasGeospatialIssue": "false",
        "limit": min(PAGE_SIZE, maximum),
        "offset": 0,
    })
    if not isinstance(first, dict):
        raise RuntimeError("GBIF occurrence response was not an object.")
    total = max(0, int(first.get("count") or 0))
    target = min(total, maximum)
    if target == 0:
        return [], total, 0, []

    all_rows: list[dict] = []
    errors: list[dict] = []
    offset = 0
    while offset < target:
        limit = min(PAGE_SIZE, target - offset)
        if offset == 0:
            page = first
        else:
            time.sleep(0.15)
            try:
                page = request_json("occurrence/search", {
                    "country": country_code,
                    "hasCoordinate": "true",
                    "hasGeospatialIssue": "false",
                    "limit": limit,
                    "offset": offset,
                })
            except RuntimeError as exc:
                errors.append({"offset": offset, "message": str(exc)[:500]})
                break
        rows = page.get("results", []) if isinstance(page, dict) else []
        if not isinstance(rows, list) or not rows:
            if offset < target:
                errors.append({"offset": offset, "message": "GBIF returned an empty page before the sample target."})
            break
        all_rows.extend(row for row in rows if isinstance(row, dict))
        offset += len(rows)
        if len(rows) < limit:
            if offset < target:
                errors.append({"offset": offset, "message": "Short page received before the expected sample target."})
            break
    raw_count = len(all_rows)
    return unique_records(all_rows), total, raw_count, errors


def occurrence_feature(record: dict, country: dict) -> dict | None:
    coordinates = valid_coordinates(record)
    if coordinates is None:
        return None
    lat, lon = coordinates
    media = record.get("media") if isinstance(record.get("media"), list) else []
    image_url = next((
        str(item.get("identifier")) for item in media
        if isinstance(item, dict)
        and str(item.get("identifier", "")).startswith(("https://", "http://"))
        and ("image" in str(item.get("type", "")).lower()
             or "stillimage" in str(item.get("type", "")).lower()
             or re.search(r"\.(jpe?g|png|webp|gif)(\?|$)", str(item.get("identifier", "")), re.I))
    ), None)
    props = {
        "gbif_id": record.get("key"),
        "taxon_key": record.get("speciesKey") or record.get("taxonKey"),
        "scientific_name": record.get("species") or record.get("scientificName")
                           or record.get("acceptedScientificName"),
        "taxon_rank": record.get("taxonRank"),
        "kingdom": record.get("kingdom"),
        "phylum": record.get("phylum"),
        "class": record.get("class"),
        "order": record.get("order"),
        "family": record.get("family"),
        "genus": record.get("genus"),
        "country_code": country["code"],
        "country": country["name"],
        "event_date": record.get("eventDate"),
        "year": record.get("year"),
        "basis_of_record": record.get("basisOfRecord"),
        "dataset_key": record.get("datasetKey"),
        "institution_code": record.get("institutionCode"),
        "recorded_by": record.get("recordedBy"),
        "coordinate_uncertainty_m": record.get("coordinateUncertaintyInMeters"),
        "license": record.get("license"),
        "image_url": image_url,
        "source_url": f"https://www.gbif.org/occurrence/{record.get('key')}" if record.get("key") else None,
    }
    props = {key: value for key, value in props.items() if value not in (None, "")}
    return {
        "type": "Feature",
        "id": str(record.get("key") or stable_record_id(record)),
        "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
        "properties": props,
    }


def density_class(count: int) -> str:
    if count >= 50:
        return "50+"
    if count >= 10:
        return "10-49"
    if count >= 3:
        return "3-9"
    return "1-2"


def distribution_grid(point_features: list[dict], grid_size: float = 0.5) -> dict:
    """Aggregate point records into rectangular degree cells for a density overlay."""
    if not (0 < grid_size <= 10):
        raise ValueError("grid_size must be greater than 0 and no more than 10 degrees.")
    cells: dict[tuple[float, float], dict] = defaultdict(lambda: {
        "observations": 0, "taxa": set(), "kingdoms": Counter()
    })
    for feature in point_features:
        lon, lat = feature["geometry"]["coordinates"]
        x0 = max(-180.0, min(180.0 - grid_size, math.floor(lon / grid_size) * grid_size))
        y0 = max(-90.0, min(90.0 - grid_size, math.floor(lat / grid_size) * grid_size))
        x0, y0 = round(x0, 6), round(y0, 6)
        cell = cells[(x0, y0)]
        props = feature.get("properties", {})
        cell["observations"] += 1
        taxon = props.get("taxon_key") or props.get("scientific_name")
        if taxon:
            cell["taxa"].add(str(taxon))
        kingdom = props.get("kingdom")
        if kingdom:
            cell["kingdoms"][str(kingdom)] += 1

    features = []
    for (x0, y0), values in sorted(cells.items(), key=lambda pair: (pair[0][1], pair[0][0])):
        x1, y1 = round(min(180.0, x0 + grid_size), 6), round(min(90.0, y0 + grid_size), 6)
        if x1 <= x0 or y1 <= y0:
            continue
        polygon = [[
            [x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]
        ]]
        count = values["observations"]
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": polygon},
            "properties": {
                "observation_count": count,
                "unique_taxa_count": len(values["taxa"]),
                "density_class": density_class(count),
                "grid_size_degrees": grid_size,
                "kingdom_counts": dict(sorted(values["kingdoms"].items())),
            },
        })
    return {"type": "FeatureCollection", "features": features}


def build_dataset(country: dict, records: list[dict], total: int, raw_count: int,
                  page_errors: list[dict], maximum: int, grid_size: float) -> dict:
    points = []
    for record in records:
        feature = occurrence_feature(record, country)
        if feature is not None:
            points.append(feature)
    taxa = {
        str(feature["properties"].get("taxon_key") or feature["properties"].get("scientific_name"))
        for feature in points
        if feature["properties"].get("taxon_key") or feature["properties"].get("scientific_name")
    }
    complete = not page_errors and len(records) >= min(total, maximum)
    generated = utc_now()
    grid = distribution_grid(points, grid_size)
    return {
        "dataset_type": "GBIF country biodiversity sample",
        "schema_version": 1,
        "generated_at_utc": generated,
        "repository": REPOSITORY_URL,
        "source": {
            "name": "Global Biodiversity Information Facility (GBIF)",
            "api": "https://api.gbif.org/v1/occurrence/search",
            "documentation": "https://techdocs.gbif.org/en/openapi/v1/occurrence",
            "attribution_note": "Record licences and attribution requirements vary by source dataset. Check each original GBIF record before reuse.",
        },
        "country": {"code": country["code"], "name": country["name"]},
        "query": {
            "country": country["code"],
            "hasCoordinate": True,
            "hasGeospatialIssue": False,
            "maximum_records_per_country": maximum,
            "grid_size_degrees": grid_size,
            "page_size": PAGE_SIZE,
        },
        "summary": {
            "total_matching_records_reported_by_gbif": total,
            "raw_rows_received": raw_count,
            "unique_occurrence_records": len(records),
            "mapped_occurrence_points": len(points),
            "unique_taxa_in_sample": len(taxa),
            "distribution_grid_cells": len(grid["features"]),
            "is_sample": total > len(records) or bool(page_errors) or len(points) < total,
            "complete_for_requested_sample": complete,
            "failed_pages": page_errors,
            "interpretation": "A capped sample of georeferenced occurrence records, not a census of all biodiversity or a confirmed species range.",
        },
        "observations_geojson": {"type": "FeatureCollection", "features": points},
        "distribution_geojson": grid,
    }


def read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n",
        encoding="utf-8",
    )


def run(country_filter: str, maximum: int, grid_size: float, output_dir: Path) -> int:
    if not 1 <= maximum <= MAX_RECORDS_PER_COUNTRY:
        raise ValueError(f"max_records must be between 1 and {MAX_RECORDS_PER_COUNTRY}.")
    if not (0 < grid_size <= 10):
        raise ValueError("grid_size must be greater than 0 and no more than 10 degrees.")

    countries = get_countries()
    filename_by_code = country_filenames(countries)
    selected = country_filter.strip().upper()
    if selected != "ALL":
        choices = [row for row in countries if row["code"] == selected]
        if not choices:
            raise ValueError(f"Country code {selected!r} was not found in GBIF's country enumeration.")
        countries_to_process = choices
    else:
        countries_to_process = countries

    index_path = output_dir / "index.json"
    old_index = read_json(index_path) or {}
    entries_by_code = {
        entry.get("code"): entry for entry in old_index.get("countries", [])
        if isinstance(entry, dict) and entry.get("code")
    }
    if selected == "ALL":
        entries_by_code = {}

    failures = 0
    for number, country in enumerate(countries_to_process, start=1):
        code = country["code"]
        filename = filename_by_code[code]
        file_path = output_dir / filename
        print(f"[{number}/{len(countries_to_process)}] {country['name']} ({code})", flush=True)
        try:
            records, total, raw_count, page_errors = fetch_country_records(code, maximum)
            dataset = build_dataset(country, records, total, raw_count, page_errors, maximum, grid_size)
            write_json(file_path, dataset)
            summary = dataset["summary"]
            status = "partial" if page_errors or not summary["complete_for_requested_sample"] else "updated"
            entries_by_code[code] = {
                "code": code,
                "name": country["name"],
                "file": filename,
                "available": True,
                "status": status,
                "generated_at_utc": dataset["generated_at_utc"],
                "summary": {
                    "total_matching_records": total,
                    "unique_occurrence_records": summary["unique_occurrence_records"],
                    "mapped_occurrence_points": summary["mapped_occurrence_points"],
                    "unique_taxa_in_sample": summary["unique_taxa_in_sample"],
                    "distribution_grid_cells": summary["distribution_grid_cells"],
                    "is_sample": summary["is_sample"],
                    "complete_for_requested_sample": summary["complete_for_requested_sample"],
                    "file_size_bytes": file_path.stat().st_size,
                },
            }
            if page_errors:
                failures += 1
            print(
                f"  {status}: {summary['mapped_occurrence_points']} mapped points, "
                f"{summary['unique_taxa_in_sample']} taxa, "
                f"{summary['distribution_grid_cells']} grid cells "
                f"(GBIF count: {total:,})",
                flush=True,
            )
        except Exception as exc:
            failures += 1
            previous = read_json(file_path) if file_path.exists() else None
            previous_summary = previous.get("summary", {}) if previous else {}
            entries_by_code[code] = {
                "code": code,
                "name": country["name"],
                "file": filename if previous else None,
                "available": bool(previous),
                "status": "error",
                "error": str(exc)[:500],
                "last_successful_generated_at_utc": previous.get("generated_at_utc") if previous else None,
                "summary": {
                    "total_matching_records": previous_summary.get("total_matching_records_reported_by_gbif", 0),
                    "unique_occurrence_records": previous_summary.get("unique_occurrence_records", 0),
                    "mapped_occurrence_points": previous_summary.get("mapped_occurrence_points", 0),
                    "unique_taxa_in_sample": previous_summary.get("unique_taxa_in_sample", 0),
                    "distribution_grid_cells": previous_summary.get("distribution_grid_cells", 0),
                    "file_size_bytes": file_path.stat().st_size if previous else 0,
                },
            }
            print(f"  ERROR: {exc}", file=sys.stderr, flush=True)

    ordered_entries = sorted(entries_by_code.values(), key=lambda row: str(row.get("name", "")).casefold())
    write_json(index_path, {
        "dataset_type": "GBIF country dataset index",
        "schema_version": 1,
        "generated_at_utc": utc_now(),
        "source": "https://api.gbif.org/v1/enumeration/country",
        "countries_attempted_this_run": len(countries_to_process),
        "country_count_in_index": len(ordered_entries),
        "available_country_count": sum(bool(row.get("available")) for row in ordered_entries),
        "error_or_partial_count": sum(row.get("status") in ("error", "partial") for row in ordered_entries),
        "default_sample_cap_per_country": maximum,
        "grid_size_degrees": grid_size,
        "countries": ordered_entries,
        "note": "Samples are capped and may be incomplete. Distribution grid cells summarize returned occurrence records; they do not represent confirmed habitat or range boundaries.",
    })
    print(f"Updated {index_path}. Countries with partial results or errors: {failures}.", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--country", default="ALL", help="GBIF ISO-2 country code, or ALL (default).")
    parser.add_argument("--max-records", type=int, default=DEFAULT_RECORDS_PER_COUNTRY,
                        help=f"Maximum records sampled per country, 1–{MAX_RECORDS_PER_COUNTRY}; default {DEFAULT_RECORDS_PER_COUNTRY}.")
    parser.add_argument("--grid-size", type=float, default=0.5, help="Grid-cell size in degrees; default 0.5.")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR, help="Output directory (default: repo/biodiversity).")
    args = parser.parse_args()
    try:
        return run(args.country, args.max_records, args.grid_size, args.output_dir)
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
