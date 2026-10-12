#!/usr/bin/env python3
"""Build country-level GBIF occurrence samples and density-grid GeoJSON.

The output is a capped exploratory sample. Grid cells summarize returned
occurrence records; they are not species-range boundaries or habitat polygons.
Uses only the Python standard library.
"""
from __future__ import annotations

import argparse
import calendar
import json
import math
import os
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
IUCN_API_BASE = "https://api.iucnredlist.org/api/v4"
IUCN_DATASET_URL = "https://www.iucnredlist.org/"
IUCN_API_DOCS_URL = "https://api.iucnredlist.org/help"
IUCN_PUBLICATION_APPROVED_ENV = "IUCN_PUBLICATION_APPROVED"
MAX_IUCN_TARGETS_PER_RUN = 25
IUCN_CATEGORY_LABELS = {
    "EX": "Extinct", "EW": "Extinct in the Wild", "CR": "Critically Endangered",
    "EN": "Endangered", "VU": "Vulnerable", "NT": "Near Threatened",
    "LC": "Least Concern", "DD": "Data Deficient", "NE": "Not Evaluated",
}
REPOSITORY_URL = "https://github.com/AnggaConni/citizenship-data"
PAGE_SIZE = 300
GBIF_SEARCH_OFFSET_LIMIT = 10_000  # GBIF restricts high-offset occurrence search queries.
MAX_RECORDS_PER_COUNTRY = 300  # Maximum new unique records appended per run.
DEFAULT_RECORDS_PER_COUNTRY = 300
MAX_BATCH_PAGE_REQUESTS = 24
MAX_PARTITION_ADVANCES_PER_RUN = 24
MIN_HARVEST_YEAR = 1800
USER_AGENT = "OpenDataExplorers-BiodiversityPipeline/1.0"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "biodiversity"
MAX_PUBLISHED_JSON_BYTES = 45 * 1024 * 1024
MAX_GBIF_NARRATIVE_CHARS = 600
MAX_MAB_NARRATIVE_CHARS = 1800
MAX_MAB_DESCRIPTION_CHARS = 3200

# Publish useful, compact source fields rather than duplicating the entire
# GBIF response, nested media objects, and other verbose payload fields.
GBIF_MAP_FIELDS = (
    "key", "datasetKey", "basisOfRecord", "taxonKey", "speciesKey",
    "scientificName", "acceptedScientificName", "species", "genus", "family", "order",
    "class", "kingdom", "country", "countryCode", "stateProvince", "county", "municipality",
    "locality", "decimalLatitude", "decimalLongitude",
)

# MAB static files are a spatial index only. Long descriptions and image metadata
# are fetched from UNESCO DataHub on demand when a user opens a reserve.
MAB_API_FIELDS = (
    "mab_id", "title_en", "iso2", "country_title_en", "coordinates", "uuid", "url",
)
MAB_GEOJSON_FIELDS = (
    "mab_id", "api_record_id", "name", "country_code", "country",
    "url", "source_url", "biosphere_id",
)
MAB_MAP_FIELDS = MAB_API_FIELDS + ("api_record_id",)



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



def request_iucn_json(
    endpoint: str,
    params: dict | None,
    api_key: str,
    retries: int = 2,
) -> dict | list:
    """Make one authenticated IUCN API v4 request without exposing the API key."""
    if not api_key or not api_key.strip():
        raise RuntimeError("IUCN API key is missing.")
    url = f"{IUCN_API_BASE.rstrip('/')}/{endpoint.lstrip('/')}"
    if params:
        url += "?" + urlencode(params)
    last_error: Exception | None = None

    for attempt in range(retries + 1):
        request = Request(url, headers={
            "Accept": "application/json",
            # IUCN documents the key as the raw Authorization header value (no Bearer prefix).
            "Authorization": api_key.strip(),
            "User-Agent": f"{USER_AGENT} (+{REPOSITORY_URL})",
        })
        try:
            with urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, (dict, list)):
                    raise RuntimeError("IUCN API returned an unexpected JSON type.")
                return payload
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise RuntimeError(
                    f"IUCN API authorization failed (HTTP {exc.code}); check the IUCN_API_KEY "
                    "secret and confirm that the account is authorized for this intended use."
                ) from None
            if exc.code == 404:
                raise LookupError("No matching IUCN taxon or resource was found.") from None
            last_error = exc
            if exc.code not in (408, 425, 429, 500, 502, 503, 504) or attempt >= retries:
                break
        except (URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            last_error = exc
            if attempt >= retries:
                break
        time.sleep(min(8.0, 1.0 * (2 ** attempt)))

    if isinstance(last_error, HTTPError):
        raise RuntimeError(
            f"IUCN API request failed for {endpoint} (HTTP {last_error.code})."
        ) from None
    raise RuntimeError(
        f"IUCN API request failed for {endpoint} ({type(last_error).__name__ if last_error else 'unknown error'})."
    ) from None


def normalize_iucn_target(item: object) -> dict | None:
    """Validate one explicitly curated species target without guessing from occurrence data."""
    if not isinstance(item, dict):
        return None
    genus = str(item.get("genus_name") or item.get("genus") or "").strip()
    species = str(item.get("species_name") or item.get("species") or "").strip()
    infra = str(item.get("infra_name") or "").strip()
    subpopulation = str(item.get("subpopulation_name") or "").strip()
    if not genus or not species or len(genus) > 100 or len(species) > 100:
        return None
    if any("\n" in value or "\r" in value for value in (genus, species, infra, subpopulation)):
        return None
    scientific_name = str(item.get("scientific_name") or " ".join(
        part for part in (genus, species, infra) if part
    )).strip()
    result = {
        "genus_name": genus,
        "species_name": species,
        "scientific_name": scientific_name,
    }
    if infra:
        result["infra_name"] = infra
    if subpopulation:
        result["subpopulation_name"] = subpopulation
    return result


def load_iucn_targets(path: Path) -> list[dict]:
    """Load a small user-curated allowlist; never harvest every GBIF taxon automatically."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(
            f"IUCN target file not found: {path}. Add selected species to biodiversity/iucn_targets.json."
        ) from None
    except json.JSONDecodeError as exc:
        raise ValueError(f"IUCN target file contains invalid JSON at line {exc.lineno}.") from None
    rows = raw.get("species") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        raise ValueError("IUCN target file must contain a top-level 'species' array.")
    targets: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        target = normalize_iucn_target(row)
        if not target:
            continue
        key = (
            target["genus_name"].casefold(),
            target["species_name"].casefold(),
            target.get("infra_name", "").casefold(),
        )
        if key not in seen:
            seen.add(key)
            targets.append(target)
    if len(targets) > MAX_IUCN_TARGETS_PER_RUN:
        raise ValueError(
            f"IUCN target list contains {len(targets)} valid species; the per-run limit is "
            f"{MAX_IUCN_TARGETS_PER_RUN}. Use a smaller curated set."
        )
    return targets


def _assessment_scope_codes(assessment: dict) -> set[str]:
    scopes = assessment.get("scopes")
    if not isinstance(scopes, list):
        return set()
    codes = set()
    for scope in scopes:
        if not isinstance(scope, dict):
            continue
        code = scope.get("code")
        if code is not None:
            codes.add(str(code))
        description = scope.get("description")
        if isinstance(description, dict) and str(description.get("en") or "").casefold() == "global":
            codes.add("1")
    return codes


def normalize_iucn_response(target: dict, payload: dict) -> dict:
    """Reduce an API response to selected assessment fields for research display."""
    taxon = payload.get("taxon") if isinstance(payload.get("taxon"), dict) else {}
    assessments = payload.get("assessments")
    assessments = [row for row in assessments if isinstance(row, dict)] if isinstance(assessments, list) else []
    if not taxon and not assessments:
        return {
            "requested_name": target["scientific_name"],
            "scientific_name": target["scientific_name"],
            "status": "not_found",
            "source": "IUCN Red List of Threatened Species",
            "source_url": IUCN_DATASET_URL,
        }
    if not assessments:
        return {
            "requested_name": target["scientific_name"],
            "scientific_name": taxon.get("scientific_name") or target["scientific_name"],
            "sis_id": taxon.get("sis_id"),
            "status": "no_assessment_found",
            "source": "IUCN Red List of Threatened Species",
            "source_url": IUCN_DATASET_URL,
        }

    global_assessments = [row for row in assessments if "1" in _assessment_scope_codes(row)]
    latest_global = [row for row in global_assessments if row.get("latest") is True]
    latest_any = [row for row in assessments if row.get("latest") is True]
    candidates = latest_global or latest_any or global_assessments or assessments
    chosen = sorted(
        candidates,
        key=lambda row: (
            str(row.get("assessment_date") or ""),
            str(row.get("year_published") or ""),
            int(row.get("assessment_id") or 0) if str(row.get("assessment_id") or "").isdigit() else 0,
        ),
        reverse=True,
    )[0]
    category = str(chosen.get("red_list_category_code") or "").strip()
    scopes = chosen.get("scopes") if isinstance(chosen.get("scopes"), list) else []
    scope_name = None
    scope_code = None
    global_scope = next((
        scope for scope in scopes
        if isinstance(scope, dict) and (
            str(scope.get("code") or "") == "1"
            or (
                isinstance(scope.get("description"), dict)
                and str(scope["description"].get("en") or "").casefold() == "global"
            )
        )
    ), None)
    chosen_scope = global_scope or next(
        (scope for scope in scopes if isinstance(scope, dict)), None
    )
    if chosen_scope:
        scope_code = str(chosen_scope.get("code")) if chosen_scope.get("code") is not None else None
        desc = chosen_scope.get("description")
        scope_name = desc.get("en") if isinstance(desc, dict) else None
        if scope_name is None and scope_code == "1":
            scope_name = "Global"

    record = {
        "requested_name": target["scientific_name"],
        "scientific_name": taxon.get("scientific_name")
            or chosen.get("taxon_scientific_name")
            or target["scientific_name"],
        "sis_id": taxon.get("sis_id") or chosen.get("sis_taxon_id"),
        "status": "assessed",
        "red_list_category_code": category or None,
        "red_list_category": IUCN_CATEGORY_LABELS.get(category.upper(), category or None),
        "assessment_date": chosen.get("assessment_date"),
        "year_published": chosen.get("year_published"),
        "assessment_criteria": chosen.get("criteria"),
        "assessment_url": chosen.get("url"),
        "assessment_id": chosen.get("assessment_id"),
        "latest": chosen.get("latest"),
        "possibly_extinct": chosen.get("possibly_extinct"),
        "possibly_extinct_in_the_wild": chosen.get("possibly_extinct_in_the_wild"),
        "scope_code": scope_code,
        "scope": scope_name or ("Global" if scope_code == "1" else None),
        "source": "IUCN Red List of Threatened Species",
        "source_url": chosen.get("url") or IUCN_DATASET_URL,
    }
    return record


def fetch_iucn_dataset(targets: list[dict], api_key: str) -> dict:
    """Fetch a strictly bounded set of explicitly requested species assessments."""
    # Validate authorization before doing any species lookups.
    api_version = request_iucn_json("information/api_version", None, api_key)
    red_list_version = request_iucn_json("information/red_list_version", None, api_key)
    result_records: list[dict] = []
    errors = 0
    for index, target in enumerate(targets):
        params = {
            "genus_name": target["genus_name"],
            "species_name": target["species_name"],
        }
        if target.get("infra_name"):
            params["infra_name"] = target["infra_name"]
        if target.get("subpopulation_name"):
            params["subpopulation_name"] = target["subpopulation_name"]
        try:
            response = request_iucn_json("taxa/scientific_name", params, api_key)
            normalized = normalize_iucn_response(target, response if isinstance(response, dict) else {})
        except LookupError:
            normalized = {
                "requested_name": target["scientific_name"],
                "scientific_name": target["scientific_name"],
                "status": "not_found",
                "source": "IUCN Red List of Threatened Species",
                "source_url": IUCN_DATASET_URL,
            }
        except RuntimeError as exc:
            # Authentication errors were validated above; preserve other failures as per-target status.
            errors += 1
            normalized = {
                "requested_name": target["scientific_name"],
                "scientific_name": target["scientific_name"],
                "status": "request_error",
                "error": str(exc)[:240],
                "source": "IUCN Red List of Threatened Species",
                "source_url": IUCN_DATASET_URL,
            }
        normalized["requested_genus_name"] = target["genus_name"]
        normalized["requested_species_name"] = target["species_name"]
        result_records.append(normalized)
        print(
            f"  IUCN [{index + 1}/{len(targets)}] {target['scientific_name']}: "
            f"{normalized['status']}",
            flush=True,
        )
        if index + 1 < len(targets):
            time.sleep(0.35)

    return {
        "dataset_type": "Selected IUCN Red List species assessment metadata",
        "schema_version": 1,
        "generated_at_utc": utc_now(),
        "source": {
            "name": "IUCN Red List of Threatened Species",
            "api": IUCN_API_BASE,
            "api_version": api_version.get("api_version") if isinstance(api_version, dict) else None,
            "red_list_version": red_list_version.get("red_list_version") if isinstance(red_list_version, dict) else None,
            "url": IUCN_DATASET_URL,
            "documentation": IUCN_API_DOCS_URL,
            "attribution": "IUCN Red List of Threatened Species",
            "note": "Only explicitly selected targets are queried. Verify IUCN terms before publishing or caching these fields.",
        },
        "summary": {
            "requested_species": len(targets),
            "assessed_species": sum(row.get("status") == "assessed" for row in result_records),
            "not_found_species": sum(row.get("status") == "not_found" for row in result_records),
            "species_without_assessment": sum(row.get("status") == "no_assessment_found" for row in result_records),
            "request_errors": errors,
            "status": "partial" if errors else "updated",
        },
        "assessments": result_records,
    }


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


def feature_identity(feature: dict) -> str:
    """Stable identity for an existing compact GeoJSON point."""
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    value = props.get("gbif_id") or props.get("key") or feature.get("id")
    return str(value) if value not in (None, "") else ""


def compact_existing_occurrence(feature: dict, country: dict) -> dict | None:
    """Migrate older, verbose occurrence features into the current map-only schema."""
    geometry = feature.get("geometry") if isinstance(feature.get("geometry"), dict) else {}
    coordinates = geometry.get("coordinates")
    if geometry.get("type") != "Point" or not isinstance(coordinates, (list, tuple)) or len(coordinates) < 2:
        return None
    try:
        lon, lat = float(coordinates[0]), float(coordinates[1])
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90):
        return None
    old_props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    props = compact_scalar_fields(old_props, GBIF_MAP_FIELDS, set(), 500)
    record_id = old_props.get("gbif_id") or old_props.get("key") or feature.get("id")
    taxon_key = old_props.get("taxon_key") or old_props.get("speciesKey") or old_props.get("taxonKey")
    scientific = (
        old_props.get("scientific_name") or old_props.get("species")
        or old_props.get("scientificName") or old_props.get("acceptedScientificName")
    )
    props.update({
        "key": props.get("key") or record_id,
        "gbif_id": record_id,
        "taxon_key": taxon_key,
        "scientific_name": scientific,
        "country_code": old_props.get("country_code") or country["code"],
        "country": old_props.get("country") or country["name"],
        "source_url": old_props.get("source_url") or (
            f"https://www.gbif.org/occurrence/{record_id}" if record_id else None
        ),
    })
    props = {key: value for key, value in props.items() if value is not None and value != ""}
    return {
        "type": "Feature",
        "id": str(record_id or feature.get("id") or ""),
        "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
        "properties": props,
    }


def initial_harvest_cursor(previous_dataset: dict | None) -> dict:
    """Resume after a previous country-wide sample; then use date partitions."""
    now = datetime.now(timezone.utc)
    old_points = (
        previous_dataset.get("observations_geojson", {}).get("features", [])
        if isinstance(previous_dataset, dict) else []
    )
    count = len(old_points) if isinstance(old_points, list) else 0
    if count < GBIF_SEARCH_OFFSET_LIMIT:
        return {
            "mode": "country", "offset": count,
            "year": now.year, "month": now.month, "day": None,
        }
    return {"mode": "month", "offset": 0, "year": now.year, "month": now.month, "day": None}


def advance_harvest_partition(cursor: dict) -> None:
    """Move backwards through month/day partitions and wrap after MIN_HARVEST_YEAR."""
    year, month, day = int(cursor["year"]), int(cursor["month"]), cursor.get("day")
    cursor["offset"] = 0
    if day is not None and int(day) < calendar.monthrange(year, month)[1]:
        cursor["day"] = int(day) + 1
        return
    if month > 1:
        year, month = year, month - 1
    else:
        year, month = year - 1, 12
    if year < MIN_HARVEST_YEAR:
        now = datetime.now(timezone.utc)
        year, month = now.year, now.month
    cursor.update({"mode": "month", "year": year, "month": month, "day": None})


def next_country_code(countries: list[dict], code: str) -> str:
    """Return the next country in the stable GBIF name-sorted rotation."""
    codes = [row["code"] for row in countries]
    if not codes:
        return "ID"
    try:
        index = codes.index(code)
    except ValueError:
        return codes[0]
    return codes[(index + 1) % len(codes)]


def fetch_country_total(country_code: str) -> int:
    """Retrieve a fresh count for the full country georeferenced occurrence query."""
    response = request_json("occurrence/search", {
        "country": country_code,
        "hasCoordinate": "true",
        "hasGeospatialIssue": "false",
        "limit": 1,
        "offset": 0,
    })
    if not isinstance(response, dict):
        raise RuntimeError("GBIF country-count response was not an object.")
    return max(0, int(response.get("count") or 0))


def fetch_incremental_records(
    country_code: str,
    maximum: int,
    cursor: dict,
    existing_ids: set[str],
) -> tuple[list[dict], int, list[dict], dict, dict]:
    """Fetch up to a batch of new unique mapped records without replacing existing records.

    Start where the prior country-wide query left off. After the deep-offset limit,
    proceed through year/month partitions and split heavily populated months by date.
    """
    if not 1 <= maximum <= MAX_RECORDS_PER_COUNTRY:
        raise ValueError(f"batch size must be between 1 and {MAX_RECORDS_PER_COUNTRY}.")
    cursor = {
        "mode": str(cursor.get("mode") or "country"),
        "offset": max(0, int(cursor.get("offset") or 0)),
        "year": int(cursor.get("year") or datetime.now(timezone.utc).year),
        "month": int(cursor.get("month") or datetime.now(timezone.utc).month),
        "day": int(cursor["day"]) if cursor.get("day") not in (None, "", 0) else None,
    }
    seen = set(existing_ids)
    new_records: list[dict] = []
    raw_rows = 0
    page_errors: list[dict] = []
    pages = 0
    advances = 0
    partition_labels: list[str] = []

    while len(new_records) < maximum and pages < MAX_BATCH_PAGE_REQUESTS:
        if cursor["mode"] == "country" and cursor["offset"] >= GBIF_SEARCH_OFFSET_LIMIT:
            cursor.update({
                "mode": "month", "offset": 0,
                "year": datetime.now(timezone.utc).year,
                "month": datetime.now(timezone.utc).month, "day": None,
            })
            continue
        if advances >= MAX_PARTITION_ADVANCES_PER_RUN:
            break
        if cursor["mode"] != "country" and cursor["offset"] >= GBIF_SEARCH_OFFSET_LIMIT:
            page_errors.append({
                "message": "A date partition exceeded GBIF's safe search offset; remaining rows in that partition were skipped."
            })
            advance_harvest_partition(cursor)
            advances += 1
            continue

        limit = min(PAGE_SIZE, maximum - len(new_records), GBIF_SEARCH_OFFSET_LIMIT - cursor["offset"])
        if limit <= 0:
            cursor["offset"] = GBIF_SEARCH_OFFSET_LIMIT
            continue
        params = {
            "country": country_code,
            "hasCoordinate": "true",
            "hasGeospatialIssue": "false",
            "limit": limit,
            "offset": cursor["offset"],
        }
        if cursor["mode"] != "country":
            if cursor["day"] is None:
                params["year"] = cursor["year"]
                params["month"] = cursor["month"]
                label = f"{cursor['year']:04d}-{cursor['month']:02d}"
            else:
                params["eventDate"] = f"{cursor['year']:04d}-{cursor['month']:02d}-{cursor['day']:02d}"
                label = params["eventDate"]
            if label not in partition_labels:
                partition_labels.append(label)

        try:
            response = request_json("occurrence/search", params)
        except RuntimeError as exc:
            page_errors.append({
                "offset": cursor["offset"],
                "partition": partition_labels[-1] if partition_labels else "country",
                "message": str(exc)[:400],
            })
            break
        pages += 1
        if not isinstance(response, dict):
            page_errors.append({"message": "GBIF occurrence response was not a JSON object."})
            break
        try:
            partition_total = max(0, int(response.get("count") or 0))
        except (TypeError, ValueError):
            partition_total = 0

        # Deep month queries are split into daily event-date partitions before paging.
        if cursor["mode"] != "country" and cursor["day"] is None and partition_total >= GBIF_SEARCH_OFFSET_LIMIT:
            cursor["day"] = 1
            cursor["offset"] = 0
            advances = 0
            continue

        if cursor["offset"] >= partition_total:
            advance_harvest_partition(cursor)
            advances += 1
            continue

        rows = response.get("results", [])
        if not isinstance(rows, list) or not rows:
            advance_harvest_partition(cursor)
            advances += 1
            continue

        raw_rows += len(rows)
        for row in rows:
            if not isinstance(row, dict) or valid_coordinates(row) is None:
                continue
            identifier = stable_record_id(row)
            if not identifier or identifier in seen:
                continue
            new_records.append(row)
            seen.add(identifier)
            if len(new_records) >= maximum:
                break

        cursor["offset"] += len(rows)
        if cursor["offset"] >= partition_total:
            advance_harvest_partition(cursor)
            advances += 1
        elif len(rows) < limit:
            page_errors.append({
                "offset": cursor["offset"],
                "partition": partition_labels[-1] if partition_labels else "country",
                "message": "GBIF returned a short page before the partition count was reached.",
            })
            advance_harvest_partition(cursor)
            advances += 1

    metadata = {
        "mode": "incremental-append",
        "batch_requested": maximum,
        "new_records_returned": len(new_records),
        "raw_rows_received": raw_rows,
        "pages_queried": pages,
        "batch_goal_met": len(new_records) >= maximum,
        "partitions_touched": partition_labels,
        "cursor_after": dict(cursor),
    }
    return new_records, raw_rows, page_errors, cursor, metadata


def bounded_text(value: object, limit: int) -> str | None:
    """Return compact text while marking long values as truncated."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if len(text) <= limit:
        return text
    suffix = " … [truncated]"
    return text[:max(0, limit - len(suffix))].rstrip() + suffix


def compact_scalar_fields(record: dict, fields: tuple[str, ...],
                          narrative_fields: set[str], narrative_limit: int) -> dict:
    """Keep allowlisted scalar fields; omit nested media metadata and arbitrary payloads."""
    compact: dict = {}
    for field in fields:
        if field not in record:
            continue
        value = record[field]
        if value is None or value == "":
            continue
        if isinstance(value, str):
            limit = narrative_limit if field in narrative_fields else 500
            value = bounded_text(value, limit)
            if value is not None:
                compact[field] = value
        elif isinstance(value, (int, float, bool)):
            compact[field] = value
    return compact


def occurrence_feature(record: dict, country: dict) -> dict | None:
    """Create a lightweight mapping feature; full record metadata is requested by the browser."""
    coordinates = valid_coordinates(record)
    if coordinates is None:
        return None
    lat, lon = coordinates
    props = compact_scalar_fields(record, GBIF_MAP_FIELDS, set(), 500)
    props.update({
        "gbif_id": record.get("key"),
        "taxon_key": record.get("speciesKey") or record.get("taxonKey"),
        "scientific_name": record.get("species") or record.get("scientificName")
                           or record.get("acceptedScientificName"),
        "country_code": country["code"],
        "country": country["name"],
        "source_url": f"https://www.gbif.org/occurrence/{record.get('key')}" if record.get("key") else None,
    })
    props = {key: value for key, value in props.items() if value is not None and value != ""}
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


def extract_unesco_fields(item: object) -> dict | None:
    """Extract source fields plus the API record identifier from supported response shapes."""
    if not isinstance(item, dict):
        return None
    fields = item.get("fields")
    if isinstance(fields, dict):
        result = dict(fields)
    else:
        record = item.get("record")
        if isinstance(record, dict) and isinstance(record.get("fields"), dict):
            result = dict(record["fields"])
        elif isinstance(record, dict) and any(key in record for key in (
            "mab_id", "title_en", "iso2", "country_title_en", "coordinates", "geo_point_2d"
        )):
            result = dict(record)
        elif any(key in item for key in (
            "mab_id", "title_en", "iso2", "country_title_en", "coordinates", "geo_point_2d"
        )):
            result = dict(item)
        else:
            return None
    record_id = item.get("recordid") or item.get("record_id") or item.get("recordId")
    if record_id:
        result["api_record_id"] = str(record_id)
    return result


def normalize_biosphere_record(record: dict) -> dict:
    """Normalize a compact UNESCO MAB map-index entry; detailed fields stay upstream."""
    item = compact_scalar_fields(record, MAB_MAP_FIELDS, set(), 500)
    coordinates = record.get("coordinates")
    if coordinates is None:
        coordinates = record.get("geo_point_2d") or record.get("geopoint") or record.get("geo_point")
    lat = lon = None
    if isinstance(coordinates, (list, tuple)) and len(coordinates) >= 2:
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

    if lat is not None and lon is not None:
        item["coordinates"] = {"lat": round(lat, 6), "lon": round(lon, 6)}
    item["biosphere_id"] = item.get("mab_id") or item.get("uuid")
    item["name"] = item.get("title_en") or item.get("title") or item.get("name")
    item["country_code"] = str(item.get("iso2") or item.get("country_code") or "").upper() or None
    item["country"] = item.get("country_title_en") or item.get("country")
    item["_latitude"] = lat
    item["_longitude"] = lon
    item["source_url"] = item.get("url") or UNESCO_DATASET_URL
    return {key: value for key, value in item.items() if value is not None and value != ""}


def biosphere_feature(record: dict) -> dict | None:
    normalized = normalize_biosphere_record(record)
    lat, lon = normalized.get("_latitude"), normalized.get("_longitude")
    if lat is None or lon is None:
        return None
    # Map features carry only identifiers and compact labels; the detail API is called on demand.
    props = {
        key: normalized[key]
        for key in MAB_GEOJSON_FIELDS
        if key in normalized and normalized[key] is not None and normalized[key] != ""
    }
    return {
        "type": "Feature",
        "id": str(normalized.get("biosphere_id") or normalized.get("uuid") or normalized.get("name") or ""),
        "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
        "properties": props,
    }


def fetch_biosphere_records() -> list[dict]:
    """Fetch all published records from UNESCO's public MAB DataHub dataset.

    Supports the flattened results used by Explore API v2.1 as well as older/nested
    response shapes. An empty response is treated as a failure so an upstream schema
    change cannot silently overwrite the published reserve dataset with zero records.
    """
    endpoint = f"catalog/datasets/{UNESCO_DATASET_ID}/records"
    page_size = 100
    select_fields = ",".join(MAB_API_FIELDS)
    first = request_json(endpoint, {"limit": page_size, "offset": 0, "select": select_fields}, base_url=UNESCO_API_BASE)
    if not isinstance(first, dict):
        raise RuntimeError("UNESCO DataHub response was not a JSON object.")

    def total_count(response: dict, fallback: int = 0) -> int:
        pagination = response.get("pagination") if isinstance(response.get("pagination"), dict) else {}
        raw = response.get("total_count", response.get("nhits", pagination.get("total_count", fallback)))
        try:
            return max(0, int(raw or 0))
        except (TypeError, ValueError):
            return max(0, fallback)

    total = total_count(first)
    results = first.get("results") if isinstance(first.get("results"), list) else []
    records: list[dict] = []
    for item in results:
        fields = extract_unesco_fields(item)
        if fields is not None:
            records.append(normalize_biosphere_record(fields))

    offset = len(results)
    while offset < total:
        response = request_json(
            endpoint, {"limit": page_size, "offset": offset, "select": select_fields},
            base_url=UNESCO_API_BASE
        )
        if not isinstance(response, dict):
            raise RuntimeError(f"UNESCO DataHub returned an unexpected response at offset {offset}.")
        page = response.get("results", [])
        if not isinstance(page, list) or not page:
            raise RuntimeError(
                f"UNESCO DataHub returned an empty page at offset {offset} of {total}."
            )
        for item in page:
            fields = extract_unesco_fields(item)
            if fields is not None:
                records.append(normalize_biosphere_record(fields))
        offset += len(page)
        time.sleep(0.1)

    unique: dict[str, dict] = {}
    for record in records:
        key = str(record.get("biosphere_id") or record.get("uuid") or (
            str(record.get("name")) + "|" + str(record.get("country_code"))
        ))
        unique[key] = record

    if total > 0 and not unique:
        raise RuntimeError(
            f"UNESCO DataHub reported {total} MAB records, but none matched a supported "
            "record shape. The API response may have changed; retaining previously published data."
        )
    if total == 0 and not unique:
        raise RuntimeError(
            "UNESCO DataHub returned zero MAB records. Refusing to replace the published dataset "
            "with an empty file; verify the upstream API response."
        )
    return list(unique.values())


def build_biosphere_dataset(records: list[dict], error: str | None = None) -> dict:
    normalized = [normalize_biosphere_record(record) for record in records]
    features = [feature for record in normalized if (feature := biosphere_feature(record)) is not None]
    return {
        "dataset_type": "UNESCO Man and the Biosphere (MAB) reserves",
        "schema_version": 2,
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
        "geojson": {"type": "FeatureCollection", "features": features},
    }


def build_dataset(country: dict, records: list[dict], total: int, raw_count: int,
                  page_errors: list[dict], maximum: int, grid_size: float,
                  biosphere_records: list[dict] | None = None,
                  biosphere_error: str | None = None,
                  previous_dataset: dict | None = None,
                  harvest_meta: dict | None = None) -> dict:
    """Append new mapped points to a prior country dataset and rebuild cumulative summaries."""
    old_features = (
        previous_dataset.get("observations_geojson", {}).get("features", [])
        if isinstance(previous_dataset, dict) else []
    )
    old_points: list[dict] = []
    seen: set[str] = set()
    for feature in old_features if isinstance(old_features, list) else []:
        if not isinstance(feature, dict):
            continue
        compact = compact_existing_occurrence(feature, country)
        if compact is None:
            continue
        identifier = feature_identity(compact)
        if identifier and identifier not in seen:
            seen.add(identifier)
            old_points.append(compact)

    added_points: list[dict] = []
    for record in records:
        feature = occurrence_feature(record, country)
        if feature is None:
            continue
        identifier = feature_identity(feature)
        if identifier and identifier in seen:
            continue
        if identifier:
            seen.add(identifier)
        added_points.append(feature)

    points = old_points + added_points
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
    complete = not page_errors and raw_count > 0
    generated = utc_now()
    harvest = dict(harvest_meta or {})
    harvest.update({
        "mode": "incremental-append",
        "batch_new_records_added": len(added_points),
        "cumulative_mapped_points": len(points),
        "previous_points_retained": len(old_points),
        "batch_goal_met": len(added_points) >= maximum,
        "raw_rows_received": raw_count,
        "page_errors": page_errors,
    })
    return {
        "dataset_type": "GBIF country biodiversity spatial index + UNESCO MAB points",
        "schema_version": 4,
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
            "batch_size_per_run": maximum,
            "harvest_mode": "incremental-append",
            "grid_size_degrees": grid_size,
            "page_size": PAGE_SIZE,
            "cursor": harvest.get("cursor_after"),
            "partitions_touched": harvest.get("partitions_touched", []),
        },
        "summary": {
            "total_matching_records_reported_by_gbif": total,
            "raw_rows_received": raw_count,
            "unique_occurrence_records": len(points),
            "mapped_occurrence_points": len(points),
            "new_occurrence_records_added": len(added_points),
            "previous_points_retained": len(old_points),
            "unique_taxa_in_sample": len(taxa),
            "distribution_grid_cells": len(grid["features"]),
            "biosphere_reserves_in_country": len(reserves),
            "biosphere_reserve_points_with_coordinates": len(reserve_features),
            "is_sample": total > len(points) or bool(page_errors) or len(points) < total,
            "complete_for_requested_sample": complete,
            "batch_goal_met": len(added_points) >= maximum,
            "failed_pages": page_errors,
            "harvest": harvest,
            "interpretation": "Cumulative, deduplicated GBIF occurrence points appended in rotating daily batches. Stored points remain a partial sample, not a census or confirmed species range.",
        },
        "observations_geojson": {"type": "FeatureCollection", "features": points},
        "distribution_geojson": grid,
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
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
    size_bytes = len(payload.encode("utf-8"))
    if size_bytes > MAX_PUBLISHED_JSON_BYTES:
        size_mb = size_bytes / (1024 * 1024)
        limit_mb = MAX_PUBLISHED_JSON_BYTES / (1024 * 1024)
        raise ValueError(
            f"Refusing to publish {path.name}: {size_mb:.2f} MB exceeds the "
            f"{limit_mb:.0f} MiB safety limit. Slim the dataset or reduce the sample size."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def run(country_filter: str, maximum: int, grid_size: float, output_dir: Path,
        include_iucn: bool = False, iucn_targets_path: Path | None = None) -> int:
    if not 1 <= maximum <= MAX_RECORDS_PER_COUNTRY:
        raise ValueError(f"batch size must be between 1 and {MAX_RECORDS_PER_COUNTRY}.")
    if not (0 < grid_size <= 10):
        raise ValueError("grid_size must be greater than 0 and no more than 10 degrees.")

    countries = get_countries()
    filename_by_code = country_filenames(countries)
    selected = country_filter.strip().upper()
    index_path = output_dir / "index.json"
    state_path = output_dir / "harvest-state.json"
    old_index = read_json(index_path) or {}
    harvest_state = read_json(state_path) or {
        "schema_version": 1,
        "next_country_code": "ID",
        "countries": {},
    }
    country_states = harvest_state.get("countries")
    if not isinstance(country_states, dict):
        country_states = {}
        harvest_state["countries"] = country_states
    entries_by_code = {
        entry.get("code"): entry for entry in old_index.get("countries", [])
        if isinstance(entry, dict) and entry.get("code")
    }

    if selected == "NEXT":
        next_code = str(harvest_state.get("next_country_code") or "ID").upper()
        by_code = {row["code"]: row for row in countries}
        chosen = by_code.get(next_code) or by_code.get("ID") or (countries[0] if countries else None)
        if not chosen:
            raise RuntimeError("No country was available for the next incremental run.")
        countries_to_process = [chosen]
    elif selected == "ALL":
        countries_to_process = countries
    else:
        choices = [row for row in countries if row["code"] == selected]
        if not choices:
            raise ValueError(f"Country code {selected!r} was not found in GBIF's country enumeration.")
        countries_to_process = choices

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
        if previous_biosphere and isinstance(previous_biosphere.get("geojson"), dict):
            for feature in previous_biosphere["geojson"].get("features", []):
                props = feature.get("properties", {}) if isinstance(feature, dict) else {}
                coords = feature.get("geometry", {}).get("coordinates", []) if isinstance(feature, dict) else []
                if len(coords) >= 2:
                    biosphere_records.append({
                        **props,
                        "mab_id": props.get("mab_id") or props.get("biosphere_id"),
                        "title_en": props.get("name") or props.get("title_en"),
                        "iso2": props.get("country_code") or props.get("iso2"),
                        "country_title_en": props.get("country") or props.get("country_title_en"),
                        "coordinates": {"lat": coords[1], "lon": coords[0]},
                    })
        if not biosphere_records:
            print(
                f"WARNING: UNESCO MAB refresh failed and no prior points were available: {biosphere_error}",
                file=sys.stderr, flush=True,
            )
        else:
            print(
                f"WARNING: UNESCO MAB refresh failed; retaining {len(biosphere_records)} previous points: {biosphere_error}",
                file=sys.stderr, flush=True,
            )

    iucn_path = output_dir / "iucn-assessments.json"
    # Direct IUCN collection is hard-disabled while permission is pending.
    # Old environment variables, secrets or stored files must never unlock it.
    if include_iucn:
        raise ValueError(
            "IUCN direct API lookup/scraping is stopped: permission is not approved. "
            "Assessment data remain hidden and unpublished. Do not bypass this gate."
        )
    if iucn_path.exists():
        iucn_path.unlink()
    iucn_summary = {
        "file": "iucn-assessments.json",
        "source": IUCN_DATASET_URL,
        "status": "not-approved-yet",
        "public_display_approved": False,
        "dataset_available": False,
        "direct_api_enabled": False,
        "scraping_enabled": False,
        "data_hidden": True,
        "note": "NOT APPROVED YET: direct IUCN API lookup/scraping, enrichment, caching and publication are stopped pending explicit permission.",
    }


    failures = 0
    for number, country in enumerate(countries_to_process, start=1):
        code = country["code"]
        filename = filename_by_code[code]
        file_path = output_dir / filename
        previous = read_json(file_path) if file_path.exists() else None
        old_features = (
            previous.get("observations_geojson", {}).get("features", [])
            if isinstance(previous, dict) else []
        )
        existing_ids = {
            feature_identity(feature) for feature in old_features
            if isinstance(feature, dict) and feature_identity(feature)
        }
        stored_state = country_states.get(code) if isinstance(country_states.get(code), dict) else {}
        stored_cursor = stored_state.get("cursor") if isinstance(stored_state.get("cursor"), dict) else None
        cursor = dict(stored_cursor) if stored_cursor else initial_harvest_cursor(previous)
        cursor_start = dict(cursor)
        print(
            f"[{number}/{len(countries_to_process)}] {country['name']} ({code}) "
            f"— append up to {maximum} new unique records; cursor={cursor_start}",
            flush=True,
        )
        try:
            total = fetch_country_total(code)
            records, raw_count, page_errors, cursor, harvest_meta = fetch_incremental_records(
                code, maximum, cursor, existing_ids
            )
            harvest_meta["cursor_start"] = cursor_start
            harvest_meta["cursor_after"] = dict(cursor)
            dataset = build_dataset(
                country, records, total, raw_count, page_errors, maximum, grid_size,
                biosphere_records=biosphere_records, biosphere_error=biosphere_error,
                previous_dataset=previous, harvest_meta=harvest_meta,
            )
            write_json(file_path, dataset)
            summary = dataset["summary"]
            status = "partial" if page_errors else "updated"
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
                    "new_occurrence_records_added": summary["new_occurrence_records_added"],
                    "previous_points_retained": summary["previous_points_retained"],
                    "unique_taxa_in_sample": summary["unique_taxa_in_sample"],
                    "distribution_grid_cells": summary["distribution_grid_cells"],
                    "biosphere_reserves_in_country": summary["biosphere_reserves_in_country"],
                    "biosphere_reserve_points_with_coordinates": summary["biosphere_reserve_points_with_coordinates"],
                    "is_sample": summary["is_sample"],
                    "complete_for_requested_sample": summary["complete_for_requested_sample"],
                    "batch_goal_met": summary["batch_goal_met"],
                    "last_batch_pages_queried": harvest_meta["pages_queried"],
                    "file_size_bytes": file_path.stat().st_size,
                },
            }
            country_states[code] = {
                "cursor": cursor,
                "last_successful_generated_at_utc": dataset["generated_at_utc"],
                "last_batch_new_records": summary["new_occurrence_records_added"],
                "last_batch_raw_rows": raw_count,
                "last_batch_pages_queried": harvest_meta["pages_queried"],
                "cumulative_points": summary["mapped_occurrence_points"],
            }
            harvest_state["next_country_code"] = next_country_code(countries, code)
            print(
                f"  {status}: appended {summary['new_occurrence_records_added']} new unique points; "
                f"{summary['mapped_occurrence_points']} cumulative points, "
                f"{summary['unique_taxa_in_sample']} taxa, {summary['distribution_grid_cells']} grid cells "
                f"(GBIF full query count: {total:,}; pages queried: {harvest_meta['pages_queried']}).",
                flush=True,
            )
        except Exception as exc:
            failures += 1
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
                    "new_occurrence_records_added": 0,
                    "unique_taxa_in_sample": previous_summary.get("unique_taxa_in_sample", 0),
                    "distribution_grid_cells": previous_summary.get("distribution_grid_cells", 0),
                    "file_size_bytes": file_path.stat().st_size if previous else 0,
                },
            }
            print(f"  ERROR: {exc}", file=sys.stderr, flush=True)
            # Leave the rotation pointer unchanged to retry this country next time.
            harvest_state["next_country_code"] = code

    ordered_entries = sorted(entries_by_code.values(), key=lambda row: str(row.get("name", "")).casefold())
    write_json(index_path, {
        "dataset_type": "GBIF country dataset index",
        "schema_version": 2,
        "generated_at_utc": utc_now(),
        "source": "https://api.gbif.org/v1/enumeration/country",
        "countries_attempted_this_run": len(countries_to_process),
        "country_count_in_index": len(ordered_entries),
        "available_country_count": sum(bool(row.get("available")) for row in ordered_entries),
        "error_or_partial_count": sum(row.get("status") in ("error", "partial") for row in ordered_entries),
        "default_new_records_per_run": maximum,
        "harvest_mode": "incremental-append",
        "country_rotation_next": harvest_state.get("next_country_code", "ID"),
        "grid_size_degrees": grid_size,
        "biosphere": {
            "file": "biosphere.json",
            "source": UNESCO_DATASET_URL,
            "license": "CC BY-SA 4.0",
            "attribution": "UNESCO",
            "records": len(biosphere_records),
            "error": biosphere_error,
        },
        "iucn": iucn_summary,
        "countries": ordered_entries,
        "note": "Country JSON files retain prior unique GBIF points and append new records in rotating daily batches. GBIF IDs are deduplicated. Date partitions help avoid deep-search offsets; samples remain incomplete and grid cells are not habitat/range boundaries.",
    })
    write_json(state_path, harvest_state)
    print(
        f"Updated {index_path}. Next daily country: {harvest_state.get('next_country_code')}. "
        f"Countries with errors/partial pages: {failures}.",
        flush=True,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--country", default="NEXT", help="NEXT selects the next country in the persisted rotation; or provide one GBIF ISO-2 country code. ALL explicitly processes every country.")
    parser.add_argument("--max-records", type=int, default=DEFAULT_RECORDS_PER_COUNTRY,
                        help=f"Maximum new unique records to append in this run, 1–{MAX_RECORDS_PER_COUNTRY}; default {DEFAULT_RECORDS_PER_COUNTRY}.")
    parser.add_argument("--grid-size", type=float, default=0.5, help="Grid-cell size in degrees; default 0.5.")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR, help="Output directory (default: repo/biodiversity).")
    parser.add_argument("--include-iucn", action="store_true", help="Disabled: direct IUCN API requests/scraping are stopped pending permission. This flag always fails closed.")
    parser.add_argument("--iucn-targets", type=Path, help="Optional path to a manually curated IUCN target JSON file.")
    args = parser.parse_args()
    try:
        return run(args.country, args.max_records, args.grid_size, args.output_dir,
                   include_iucn=args.include_iucn, iucn_targets_path=args.iucn_targets)
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
