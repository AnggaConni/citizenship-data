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
UNESCO_API_BASE = "https://data.unesco.org/api/explore/v2.1"
UNESCO_DATASET_ID = "mab001"
UNESCO_DATASET_URL = "https://data.unesco.org/explore/dataset/mab001/information/"
REPOSITORY_URL = "https://github.com/AnggaConni/citizenship-data"
PAGE_SIZE = 300
MAX_RECORDS_PER_COUNTRY = 9900  # Keep search offsets below 10,000.
DEFAULT_RECORDS_PER_COUNTRY = 300
USER_AGENT = "OpenDataExplorers-BiodiversityPipeline/1.0"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "biodiversity"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def request_json(
    endpoint: str,
    params: dict | None = None,
    retries: int = 3,
    base_url: str = API_BASE,
) -> dict | list:
    url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
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
    # Keep the complete interpreted GBIF occurrence payload in GeoJSON properties.
    # Normalized aliases make common fields easier for a future UI to consume.
    # GBIF does not guarantee a narrative description for every observation.
    description_fields = (
        "description", "taxonRemarks", "occurrenceRemarks", "habitat",
        "eventRemarks", "fieldNotes", "identificationRemarks",
    )
    description_parts = []
    for field in description_fields:
        value = record.get(field)
        if isinstance(value, str) and value.strip() and value.strip() not in description_parts:
            description_parts.append(value.strip())
    description = " — ".join(description_parts) if description_parts else None

    props = dict(record)
    props.update({
        "gbif_id": record.get("key"),
        "taxon_key": record.get("speciesKey") or record.get("taxonKey"),
        "scientific_name": record.get("species") or record.get("scientificName")
                           or record.get("acceptedScientificName"),
        "country_code": country["code"],
        "country": country["name"],
        "image_url": image_url,
        "description": description,
        "source_url": f"https://www.gbif.org/occurrence/{record.get('key')}" if record.get("key") else None,
    })
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


def normalize_biosphere_record(record: dict) -> dict:
    """Normalize one UNESCO MAB DataHub record while preserving all source fields."""
    item = dict(record)
    coordinates = item.get("coordinates")
    lat = lon = None
    if isinstance(coordinates, (list, tuple)) and len(coordinates) >= 2:
        # UNESCO DataHub geo-point values are [latitude, longitude]; GeoJSON reverses that order.
        try:
            lat, lon = float(coordinates[0]), float(coordinates[1])
        except (TypeError, ValueError):
            lat = lon = None
    elif isinstance(coordinates, dict):
        try:
            lat = float(coordinates.get("lat", coordinates.get("latitude")))
            lon = float(coordinates.get("lon", coordinates.get("longitude")))
        except (TypeError, ValueError):
            lat = lon = None
    if lat is not None and lon is not None and (
        not math.isfinite(lat) or not math.isfinite(lon)
        or not (-90 <= lat <= 90 and -180 <= lon <= 180)
    ):
        lat = lon = None

    item["biosphere_id"] = item.get("mab_id") or item.get("uuid")
    item["name"] = item.get("title_en") or item.get("title") or item.get("name")
    item["country_code"] = str(item.get("iso2") or "").upper() or None
    item["country"] = item.get("country_title_en") or item.get("country")
    desc_parts = []
    for field in ("introduction_en", "ecological_characteristics_en"):
        value = item.get(field)
        if isinstance(value, str) and value.strip():
            desc_parts.append(value.strip())
    item["description"] = "\n\n".join(desc_parts) if desc_parts else item.get("description")
    item["_latitude"] = lat
    item["_longitude"] = lon
    item["source_url"] = item.get("url") or UNESCO_DATASET_URL
    return item


def biosphere_feature(record: dict) -> dict | None:
    normalized = normalize_biosphere_record(record)
    lat, lon = normalized.get("_latitude"), normalized.get("_longitude")
    if lat is None or lon is None:
        return None
    props = {key: value for key, value in normalized.items() if not key.startswith("_")}
    return {
        "type": "Feature",
        "id": str(normalized.get("biosphere_id") or normalized.get("uuid") or normalized.get("name") or ""),
        "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
        "properties": props,
    }


def fetch_biosphere_records() -> list[dict]:
    """Fetch all published records from UNESCO's public MAB DataHub dataset."""
    endpoint = f"catalog/datasets/{UNESCO_DATASET_ID}/records"
    page_size = 100
    first = request_json(endpoint, {"limit": page_size, "offset": 0}, base_url=UNESCO_API_BASE)
    if not isinstance(first, dict):
        raise RuntimeError("UNESCO DataHub response was not a JSON object.")
    total = int(first.get("total_count") or 0)
    results = first.get("results") if isinstance(first.get("results"), list) else []
    records = []
    for wrapper in results:
        fields = wrapper.get("fields") if isinstance(wrapper, dict) else None
        if isinstance(fields, dict):
            records.append(normalize_biosphere_record(fields))
    offset = len(results)
    while offset < total:
        response = request_json(
            endpoint, {"limit": page_size, "offset": offset}, base_url=UNESCO_API_BASE
        )
        page = response.get("results", []) if isinstance(response, dict) else []
        if not isinstance(page, list) or not page:
            raise RuntimeError(f"UNESCO DataHub returned an empty page at offset {offset} of {total}.")
        for wrapper in page:
            fields = wrapper.get("fields") if isinstance(wrapper, dict) else None
            if isinstance(fields, dict):
                records.append(normalize_biosphere_record(fields))
        offset += len(page)
        time.sleep(0.1)
    unique = {}
    for record in records:
        key = str(record.get("biosphere_id") or record.get("uuid") or (
            str(record.get("name")) + "|" + str(record.get("country_code"))
        ))
        unique[key] = record
    return list(unique.values())


def build_biosphere_dataset(records: list[dict], error: str | None = None) -> dict:
    normalized = [normalize_biosphere_record(record) for record in records]
    features = [feature for record in normalized if (feature := biosphere_feature(record)) is not None]
    return {
        "dataset_type": "UNESCO Man and the Biosphere (MAB) reserves",
        "schema_version": 1,
        "generated_at_utc": utc_now(),
        "source": {
            "name": "UNESCO DataHub — Man and the Biosphere Programme",
            "dataset_id": UNESCO_DATASET_ID,
            "api": f"{UNESCO_API_BASE}/catalog/datasets/{UNESCO_DATASET_ID}/records",
            "url": UNESCO_DATASET_URL,
            "license": "CC BY-SA 4.0",
            "attribution": "UNESCO",
        },
        "summary": {
            "records": len(normalized),
            "mapped_point_features": len(features),
            "records_without_coordinates": len(normalized) - len(features),
            "status": "updated" if records and not error else ("stale-fallback" if records else "unavailable"),
            "error": error,
            "geometry_note": "The source dataset supplies point coordinates, not official reserve boundary polygons. Do not render these points as reserve boundaries.",
        },
        "records": [{key: value for key, value in record.items() if not key.startswith("_")} for record in normalized],
        "geojson": {"type": "FeatureCollection", "features": features},
    }


def build_dataset(country: dict, records: list[dict], total: int, raw_count: int,
                  page_errors: list[dict], maximum: int, grid_size: float,
                  biosphere_records: list[dict] | None = None,
                  biosphere_error: str | None = None) -> dict:
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
    grid = distribution_grid(points, grid_size)
    reserves = [
        record for record in (biosphere_records or [])
        if str(record.get("country_code") or "").upper() == country["code"]
    ]
    reserve_features = [feature for record in reserves if (feature := biosphere_feature(record)) is not None]
    complete = not page_errors and len(records) >= min(total, maximum)
    generated = utc_now()
    return {
        "dataset_type": "GBIF country biodiversity sample + UNESCO MAB records",
        "schema_version": 2,
        "generated_at_utc": generated,
        "repository": REPOSITORY_URL,
        "source": {
            "name": "Global Biodiversity Information Facility (GBIF)",
            "api": "https://api.gbif.org/v1/occurrence/search",
            "documentation": "https://techdocs.gbif.org/en/openapi/v1/occurrence",
            "attribution_note": "GBIF occurrence records have varying licences and attribution requirements. Check each original record before reuse.",
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
            "biosphere_reserves_in_country": len(reserves),
            "biosphere_reserve_points_with_coordinates": len(reserve_features),
            "is_sample": total > len(records) or bool(page_errors) or len(points) < total,
            "complete_for_requested_sample": complete,
            "failed_pages": page_errors,
            "interpretation": "A capped sample of georeferenced occurrence records, not a census of all biodiversity or a confirmed species range.",
        },
        "observations_geojson": {"type": "FeatureCollection", "features": points},
        "distribution_geojson": grid,
        "biosphere_reserves": [{key: value for key, value in record.items() if not key.startswith("_")} for record in reserves],
        "biosphere_geojson": {"type": "FeatureCollection", "features": reserve_features},
        "biosphere_source_status": {
            "dataset_id": UNESCO_DATASET_ID,
            "url": UNESCO_DATASET_URL,
            "license": "CC BY-SA 4.0",
            "attribution": "UNESCO",
            "error": biosphere_error,
            "geometry_note": "Only source-provided reserve point coordinates are included here; official reserve boundary polygons are not provided by this endpoint.",
        },
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

    output_dir.mkdir(parents=True, exist_ok=True)
    biosphere_records: list[dict] = []
    biosphere_error: str | None = None
    biosphere_path = output_dir / "biosphere.json"
    try:
        biosphere_records = fetch_biosphere_records()
        write_json(biosphere_path, build_biosphere_dataset(biosphere_records))
        print(f"UNESCO MAB DataHub: {len(biosphere_records)} biosphere reserve records.", flush=True)
    except Exception as exc:
        biosphere_error = str(exc)[:500]
        previous_biosphere = read_json(biosphere_path) if biosphere_path.exists() else None
        if previous_biosphere and isinstance(previous_biosphere.get("records"), list):
            biosphere_records = [
                normalize_biosphere_record(row) for row in previous_biosphere["records"]
                if isinstance(row, dict)
            ]
        else:
            write_json(biosphere_path, build_biosphere_dataset([], biosphere_error))
        print(f"WARNING: UNESCO MAB refresh failed; retaining previous data when available: {biosphere_error}", file=sys.stderr, flush=True)

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
            dataset = build_dataset(
                country, records, total, raw_count, page_errors, maximum, grid_size,
                biosphere_records=biosphere_records, biosphere_error=biosphere_error,
            )
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
                    "biosphere_reserves_in_country": summary["biosphere_reserves_in_country"],
                    "biosphere_reserve_points_with_coordinates": summary["biosphere_reserve_points_with_coordinates"],
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
        "biosphere": {
            "file": "biosphere.json",
            "source": UNESCO_DATASET_URL,
            "license": "CC BY-SA 4.0",
            "attribution": "UNESCO",
            "records": len(biosphere_records),
            "error": biosphere_error,
        },
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
