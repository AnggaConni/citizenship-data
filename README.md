# Open Data Explorers

**Open Data Explorers** is an independent, no-fee project for exploring curated citizenship knowledge and biodiversity information. It brings together three user-facing experiences—Curated Data, the live Biodiversity Explorer, and the Biodiversity Atlas—backed by a Python pipeline that publishes country-level occurrence records.

- **Live site:** https://anggaconni.github.io/citizenship-data/
- **Biodiversity Atlas:** https://anggaconni.github.io/citizenship-data/biodiversity-atlas.html
- **Source code:** https://github.com/AnggaConni/citizenship-data
- **Software terms:** [LICENSE](./LICENSE)
- **Biodiversity pipeline documentation:** [biodiversity/README.md](./biodiversity/README.md)

## Important: please read the disclaimer

This project is freely accessible and is not operated as a paid service. However, **free access to the website does not mean every included dataset is public domain or free of third-party restrictions**.

1. **Software licence.** The repository has a custom licence focused on personal, educational, research, non-profit, and social-impact use. It permits copying and modifying the software for the uses described in [LICENSE](./LICENSE), subject to its conditions. Commercial use or inclusion in a paid product requires prior written permission from the author. This is not an unrestricted commercial-use licence.
2. **Third-party data.** GBIF occurrence records, UNESCO DataHub records, map tiles, photographs, and publication metadata retain the applicable source terms, record-level licences, attribution requirements, and usage limits. The repository's software licence does not replace or override those terms.
3. **IUCN Red List — 🔴 NOT APPROVED YET.** Direct IUCN API requests, scraping, enrichment, caching, and publication are **stopped** while permission is pending. IUCN assessment data are hidden and are not served by this project. The workflow no longer offers an enable switch, and the pipeline refuses direct IUCN lookup even if an API key or old approval variable exists. The Atlas does not request or display IUCN-derived conservation categories while permission is pending. Direct assessment data remain hidden and unpublished. This does not imply IUCN approval.
4. **Independent project.** This project is not an official UNESCO, GBIF, IUCN, OpenAlex, Crossref, or OpenStreetMap product. References to these organisations identify data sources only; they do not imply affiliation, sponsorship, review, approval, or endorsement.

## What is included?

### 1. Citizenship Data Explorer

A manually curated knowledge base for structured citizenship and country-related information. Records are selected and maintained by a human curator and served through project-owner-managed storage. The interface provides map, detail, curation, and export features; the fact that a record appears in the explorer does not mean an external authority has verified it.

Open the [Citizenship Data Explorer](./curated-data.html).

### 2. Biodiversity Explorer

A browser-based explorer for georeferenced species occurrence records. Users select a country—or explicitly choose Worldwide—and the browser requests pages of public GBIF data asynchronously. Results are processed as they arrive so the map, search, and species details can remain usable during the scan.

The explorer deduplicates occurrences by species for its main map and provides source links where available. The records shown are sourced from GBIF's indexed occurrence records; application limits affect what this interface retrieves or displays, not the provenance of each record. It is designed for discovery, not as an exhaustive download of GBIF or an authoritative species-range map.

Open the [Biodiversity Explorer](./biodiversity.html).

### 3. Biodiversity Atlas

When a user selects an occurrence, the detail panel performs on-demand lookups for common names, taxonomic classification, source descriptions and available profile information through the GBIF Species API and iNaturalist. The Atlas does not request or display IUCN-derived conservation categories. Direct IUCN API requests and scraping are stopped; IUCN assessment data remain hidden and unpublished while permission is pending.

The [Biodiversity Atlas](./biodiversity-atlas.html) is the published-data interface for the pipeline outputs. It reads the country index and generated JSON files directly, so visitors can select a country, inspect published record summaries, view occurrence points and density-grid cells, search records, and inspect source-linked details without triggering another API scan. **The first published country dataset is Indonesia.** The application retrieves and retains a limited, incrementally updated set of GBIF records; this describes application coverage, not the authenticity or provenance of each record. It is not a complete GBIF download or a complete species inventory.

### 4. Biodiversity Distribution Pipeline

A Python pipeline, run through GitHub Actions, that produces country-level JSON and GeoJSON from:

- **GBIF Occurrence API:** access to georeferenced occurrence records, including source fields and record links when supplied. The pipeline retrieves records in batches; this application view is not a complete GBIF download.
- **UNESCO DataHub — Man and the Biosphere dataset (mab001):** reserve metadata and source-provided point coordinates.
- **IUCN Red List:** potential future source only. **🔴 NOT APPROVED YET — direct requests/scraping stopped; assessment data hidden and not published.** Do not enable direct collection or distribute cached assessment data while permission remains pending.

The generated density grid summarizes the occurrence records currently retained by the application. It is **not** a confirmed habitat boundary, a species-range polygon, a completeness measure, or evidence that a species is currently present throughout a grid cell. Likewise, UNESCO source points must not be presented as official reserve boundaries.

Explore the [pipeline folder](./biodiversity/) and its [usage and source notes](./biodiversity/README.md).

The country pipeline publishes lightweight spatial indexes for the initial map. Full GBIF occurrence metadata and UNESCO MAB descriptions are fetched from the source APIs only when a visitor opens a point or reserve; those descriptions are not copied into static mapping JSON. Source images, when available, are loaded by URL on demand rather than downloaded into the repository. The pipeline aborts if a generated JSON file exceeds its 45 MiB safety limit. The frontend does not request or display IUCN-derived conservation-status fields, does not call the authenticated IUCN API, and does not read IUCN-derived status fields from iNaturalist. Direct IUCN assessments are hidden and not published.

## Data-use and interpretation rules

- Follow each source's attribution, licence, API terms, rate limits, and any redistribution requirements.
- Check the original source record and its licence before reusing an occurrence, image, or research result.
- Do not interpret a missing record as proof that a species is absent.
- Do not treat the records currently retrieved by this application, a representative map point, or a density grid as a complete biodiversity inventory or formal conservation assessment.
- Verify critical information with the original data provider and relevant experts before using it for conservation decisions, policy, research conclusions, or publication.
- Respect third-party rights even when the website and source code are available without charge.

## Run the biodiversity pipeline

The scheduled workflow runs daily at 02:17 UTC (09:17 Jakarta time) and appends up to **300 new unique GBIF records for one country per run**. Countries are processed one at a time in a persisted round-robin rotation, beginning with Indonesia. Previously stored points are retained and GBIF IDs are deduplicated. Duplicate IDs are skipped while the saved search cursor advances through result pages and date partitions; if the run reaches its page or partition limit before collecting the requested number of new unique records, the next run resumes from the stored cursor. This is incremental coverage, not a guarantee that every GBIF record has been exhaustively enumerated.

1. Open **Actions → Build biodiversity country datasets → Run workflow**.
2. Use **country_code = NEXT** to take the next country in the rotation, or enter one ISO-2 code such as **ID** to process a specific country.
3. Keep **max_records_per_country = 300** for up to 300 new unique records in the run. Valid values are 1–300. If an empty, non-numeric, zero, or out-of-range value is supplied, the workflow uses the safe default or cap of 300 and prints a warning. A run may add fewer when there are many duplicates, few remaining records, or a source/API issue.
4. Use **grid_size_degrees = 0.5** for the density grid. Direct IUCN lookup is disabled in code and is not an available workflow option.
5. Review the action logs and the country’s cumulative counts after the workflow succeeds.

The workflow persists its rotation and page cursor in biodiversity/harvest-state.json. It progresses through country-wide result pages up to GBIF’s safe search-offset limit, then uses year/month and date partitions to continue without repeatedly fetching the same first page. This batch is **not necessarily records first created within the last 24 hours**; it is a new-to-this-repository batch of records reached by the saved cursor. Use **country_code = ALL** only when intentionally running every country in one manual run.

**IUCN status: 🔴 NOT APPROVED YET.** Direct IUCN scraping/API requests are stopped, and direct assessment output is hidden/not published. The workflow has no IUCN enable input, and the pipeline hard-fails if a legacy caller passes the old flag. Revisit integration only after explicit written permission and a separate implementation review.

See biodiversity/README.md for cursor, deduplication, and data-source details.

## Disclaimer

All tools and datasets are provided "as is", without warranty of any kind, subject to the applicable licences and terms. Source data can be incomplete, delayed, misclassified, or changed by its provider. Images and links may become unavailable. Maps and generated summaries are not professional advice or official determinations of species presence, distribution, conservation status, or protected-area boundaries.

The software is provided "as is", without warranty of any kind, subject to the full terms in [LICENSE](./LICENSE). Users are responsible for checking source licences, providing attribution, and obtaining any permissions needed for their own reuse or redistribution.

## Contributing and reuse

You are welcome to inspect, copy, and adapt the code for the permitted personal, educational, research, non-profit, and social-impact purposes described in [LICENSE](./LICENSE). If distributing modifications, follow the licence's source-availability and redistribution conditions. Contact the author for written permission before commercial use.

---

**Built independently for free access, open knowledge, and responsible data exploration.** Third-party data remains under its own terms.
