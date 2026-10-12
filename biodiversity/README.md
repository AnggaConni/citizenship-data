# Country biodiversity and biosphere data

This pipeline builds country-level JSON files primarily from two public sources, with optional, targeted IUCN enrichment for selected taxa:

- **GBIF Occurrence API** for individual biodiversity observations and their source metadata.
- **UNESCO DataHub — Man and the Biosphere Programme (dataset mab001)** for reserve names, country, published introduction/ecological characteristics, metadata and source-provided point coordinates.
- **IUCN Red List API v4 (optional)** for selected species assessment metadata. It remains disabled by default and is subject to separate usage and publication terms.

## Files generated

- indonesia.json and other country files: the requested GBIF occurrence sample, full source payload fields for each returned observation (where exposed by the API), a standardized description field when descriptive terms are present, point GeoJSON, density-grid GeoJSON, and matching UNESCO reserve records/features.
- biosphere.json: the global UNESCO MAB dataset, with reserve records and GeoJSON point features.
- index.json: country file metadata, sample counts, and biosphere source status.

## Optional IUCN enrichment — permission gate

The repository secret IUCN_API_KEY is used only by the GitHub Actions runner and is never written into generated files. Add selected species to iucn_targets.json using their genus and species names. The pipeline does not automatically query every GBIF taxon: a single run is capped at 25 explicitly listed species.

**Do not enable IUCN enrichment just because an API key is available.** IUCN's API is non-commercial, discourages scraping or bulk extraction, and has terms governing redistribution and derivative works. This workflow writes selected assessment fields to a public JSON file, so first obtain confirmation from IUCN that this public caching/display use is permitted. Once you have confirmation, add the repository variable IUCN_PUBLICATION_APPROVED with value true and run the workflow with include_iucn_data = true. Keep this input false until then. If the publication approval variable is absent, the script refuses to write IUCN results.

When enabled, the optional output is iucn-assessments.json; it contains only selected assessment fields (category, date, publication year, criteria, URL, scope and extinction flags), not the complete API response. It also records the returned Red List version. The API key must be stored as the Actions secret IUCN_API_KEY, never as a repository variable or in a source file.


## Run it

Open **Actions → Build biodiversity country datasets → Run workflow**.

- country_code = ID updates Indonesia only; ALL updates all countries returned by GBIF enumeration.
- max_records_per_country defaults to 300 and can be increased to at most 9,900. GBIF reports millions of matching records for some countries, but the search endpoint is capped/paginated; this pipeline deliberately creates a reproducible sample rather than a complete GBIF extract.
- grid_size_degrees controls the rectangular grid used for the biodiversity density layer. A 0.5-degree cell is an exploratory count cell, not a species habitat boundary or a uniform-area cell.
- The workflow also runs each Monday at 02:17 UTC.

## About descriptions and completeness

GBIF does not provide a narrative description for every observation. The pipeline preserves source fields returned in the occurrence payload and derives a normalized description from available terms such as description, taxonRemarks, occurrenceRemarks, habitat, eventRemarks, fieldNotes, and identificationRemarks. If none are provided by a source record, the description can be null. This is not an encyclopedic description of every species.

## UNESCO MAB source and licensing

The UNESCO DataHub mab001 dataset is provided under **CC BY-SA 4.0** and is attributed to UNESCO. Preserve this attribution and review the licence requirements before redistributing adapted datasets. The endpoint currently provides reserve coordinates as points, plus descriptive fields such as introduction_en and ecological_characteristics_en; it is not an official reserve-boundary polygon API. The point layer must not be styled as an entire reserve area. The importer supports the flattened `results[]` fields returned by UNESCO DataHub Explore API v2.1, as well as older/nested field wrappers. It treats a zero-record API response as a refresh error rather than silently replacing the reserve file with an empty dataset.

GBIF source record licences vary; individual record licence and source URL fields are retained. Check the original record and dataset-level requirements before reuse.

The published-data frontend is available as the [Biodiversity Atlas](../biodiversity-atlas.html). It reads `index.json` and the selected country JSON directly, visualizes occurrence points and density-grid cells, supports record search and details, and shows UNESCO biosphere-reserve points when the source data contains mappable coordinates. The first published country dataset is an Indonesia pilot sample (currently capped at 300 occurrence records per run), not a complete biodiversity inventory. The live browser-based scanner in `biodiversity.html` is a separate experience and makes its own API requests. The Atlas also computes heuristic spatial clusters in the browser from the sample points; the cluster radius can be adjusted (25–150 km). Clicking a cluster zooms to the grouped source points, while isolated observations remain as individual markers. The polygon envelopes use a local convex hull and are illustrative summaries only—not authoritative species ranges, habitat boundaries or reserve boundaries. Clicking a UNESCO MAB point zooms to sampled occurrence records within 50 km of its source coordinate; this is a proximity view, not evidence that those records fall inside a reserve.
