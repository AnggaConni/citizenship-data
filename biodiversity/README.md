# Country Biodiversity Atlas data

The pipeline publishes a lightweight spatial index for the Biodiversity Atlas. It uses incremental, append-only harvesting of GBIF occurrence records, plus UNESCO Man and the Biosphere (MAB) reserve points.

## How daily harvesting works

- GitHub Actions runs every day at 02:17 UTC (09:17 Jakarta time).
- Each scheduled run processes **one country only**, selected from a persisted round-robin queue. The initial country is Indonesia (ID).
- Each run aims to append up to **300 new unique, georeferenced GBIF records** for the selected country. It does not replace the existing collection.
- Existing GBIF occurrence IDs are checked before appending. Duplicate IDs are skipped, while previously collected points are retained.
- The file biodiversity/harvest-state.json saves the next country in the rotation and the current query cursor for every country. It is committed alongside the JSON datasets, so the cursor survives between GitHub Actions runs.
- For a manually triggered run, set country_code to NEXT for the next queued country or an ISO-2 code such as ID to process one specific country. Avoid ALL for normal daily incremental harvesting because it attempts every country in a single run.
- max_records_per_country is the maximum new unique records to append in that run, from 1 to 300. A batch may append fewer than 300 if the source has fewer available records, the batch encounters many duplicates, or an API request fails.

**The 300 records are not necessarily observations first created in the last 24 hours.** The cursor progresses through the GBIF country query and, when the occurrence-search offset limit is reached, through year/month and date partitions. This lets the collector continue beyond the first search pages while avoiding repeated records. The daily job stores only records that are new to this repository.

## Files generated

- index.json — country dataset listing, cumulative counts, last batch totals, source status, and rotation metadata.
- harvest-state.json — persisted country rotation and query cursors.
- indonesia.json and other country files — cumulative, deduplicated point GeoJSON, a derived density grid, summaries, and matching UNESCO MAB point features. Older verbose point metadata is compacted to the current map-only schema the next time that country is processed.
- biosphere.json — global UNESCO MAB GeoJSON source points. This shared reference file may be refreshed, but it is not duplicated as a detailed reserve catalogue inside every country file.
- iucn-assessments.json — optional targeted output, disabled until applicable public caching/display permission has been confirmed from IUCN.

## Lightweight map index and on-demand details

GBIF occurrence JSON contains only fields needed for the initial map: record key, coordinates, scientific name, selected taxonomy/location labels, and source link. Full observation details, descriptions and media URLs are fetched directly from GBIF when a visitor opens a record. UNESCO reserve metadata and image URLs are likewise requested from UNESCO DataHub on demand when a user opens a MAB point.

Image assets are not downloaded or embedded in the static JSON. A 45 MiB size guard rejects an oversized generated file before it can overwrite the existing dataset.

## Data interpretation

The cumulative country dataset grows over time, but it is **not a complete biodiversity inventory**. The occurrence-search endpoint restricts deep offsets, so the harvester uses date partitions to broaden coverage; exact coverage and batch size depend on GBIF's returned records and API limits. Density grid cells count the stored sample only and do not indicate confirmed habitat or species-range boundaries. UNESCO MAB coordinates are points, not official reserve polygons.

Descriptions are not guaranteed for every species or occurrence. The Atlas asks public source APIs for taxonomic hierarchy, vernacular names, descriptions, profiles, and image URLs on demand. Automated IUCN and IUCN-derived conservation-status lookups are disabled pending permission; the frontend does not call the authenticated IUCN API or GBIF's IUCN category endpoint. If a source only provides a short distribution note—or no description—the interface should identify that limitation rather than invent a natural-history description. Users can open the public IUCN website manually; the Atlas does not fetch or cache assessment categories.

## Optional IUCN enrichment — permission gate

The repository secret IUCN_API_KEY is used only by the GitHub Actions runner and is never written into generated files. The pipeline does not automatically query every taxon; optional IUCN enrichment uses a small, manually curated target list.

**Do not enable IUCN enrichment just because an API key is available.** Before enabling public caching or display, obtain confirmation from IUCN that the intended use is permitted. Once authorized, set repository variable IUCN_PUBLICATION_APPROVED=true and run with include_iucn_data=true. Store the key only in GitHub Actions secrets, not in source code or generated JSON.

## Run it manually

Open **Actions → Build biodiversity country datasets → Run workflow**.

- country_code = NEXT — process the next country in the daily rotation (default).
- country_code = ID — process one specific country and append its next batch.
- country_code = ALL — explicitly process every country in one run; use sparingly.
- max_records_per_country = 300 — maximum new unique records to append in this run.
- grid_size_degrees = 0.5 — grid-cell size for the density overlay.
- include_iucn_data = false — keep disabled unless IUCN has confirmed the intended public caching/display use.

The published interface is the Biodiversity Atlas (../biodiversity-atlas.html). The live browser-based scanner in ../biodiversity.html is separate and issues its own API requests.
