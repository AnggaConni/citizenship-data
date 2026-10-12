# Open Data Explorers

**Open Data Explorers** is an independent, no-fee project for exploring curated citizenship knowledge and biodiversity information. It brings together three user-facing experiences—Curated Data, the live Biodiversity Explorer, and the Biodiversity Atlas—backed by a Python pipeline that publishes country-level sample datasets.

- **Live site:** https://anggaconni.github.io/citizenship-data/
- **Biodiversity Atlas:** https://anggaconni.github.io/citizenship-data/biodiversity-atlas.html
- **Source code:** https://github.com/AnggaConni/citizenship-data
- **Software terms:** [LICENSE](./LICENSE)
- **Biodiversity pipeline documentation:** [biodiversity/README.md](./biodiversity/README.md)

## Important: please read the disclaimer

This project is freely accessible and is not operated as a paid service. However, **free access to the website does not mean every included dataset is public domain or free of third-party restrictions**.

1. **Software licence.** The repository has a custom licence focused on personal, educational, research, non-profit, and social-impact use. It permits copying and modifying the software for the uses described in [LICENSE](./LICENSE), subject to its conditions. Commercial use or inclusion in a paid product requires prior written permission from the author. This is not an unrestricted commercial-use licence.
2. **Third-party data.** GBIF occurrence records, UNESCO DataHub records, map tiles, photographs, and publication metadata retain the applicable source terms, record-level licences, attribution requirements, and usage limits. The repository's software licence does not replace or override those terms.
3. **IUCN Red List.** IUCN enrichment is optional and disabled by default. Having an API key does not itself authorize redistribution. Public caching or display of IUCN assessment metadata will remain gated until permission for that specific use is confirmed with IUCN. Do not treat the IUCN API key as permission to republish its data.
4. **Independent project.** This project is not an official UNESCO, GBIF, IUCN, OpenAlex, Crossref, or OpenStreetMap product. References to these organisations identify data sources only; they do not imply affiliation, sponsorship, review, approval, or endorsement.

## What is included?

### 1. Citizenship Data Explorer

A manually curated knowledge base for structured citizenship and country-related information. Records are selected and maintained by a human curator and served through project-owner-managed storage. The interface provides map, detail, curation, and export features; the fact that a record appears in the explorer does not mean an external authority has verified it.

Open the [Citizenship Data Explorer](./curated-data.html).

### 2. Biodiversity Explorer

A browser-based explorer for georeferenced species occurrence records. Users select a country—or explicitly choose Worldwide—and the browser requests pages of public GBIF data asynchronously. Results are processed as they arrive so the map, search, and species details can remain usable during the scan.

The explorer deduplicates occurrences by species for its main map and provides source links where available. It is designed for discovery, not as an exhaustive download of GBIF or an authoritative species-range map.

Open the [Biodiversity Explorer](./biodiversity.html).

### 3. Biodiversity Atlas

When a user selects an occurrence, the detail panel also performs on-demand lookups for common names, taxonomic classification, source descriptions and available profile information through the GBIF Species API and iNaturalist. A conservation category is shown only when a source returns one; GBIF's IUCN category reference can lag the latest IUCN assessment, so the interface links to the primary IUCN Red List for verification. The frontend never exposes the IUCN API secret and does not query the authenticated IUCN API directly.

The [Biodiversity Atlas](./biodiversity-atlas.html) is the published-data interface for the pipeline outputs. It reads the country index and generated JSON files directly, so visitors can select a country, inspect sample summaries, view occurrence points and density-grid cells, search records, and inspect source-linked details without triggering another API scan. **The first published dataset is an Indonesia pilot sample**; it is capped and must not be interpreted as a complete inventory.

### 4. Biodiversity Distribution Pipeline

A Python pipeline, run through GitHub Actions, that produces country-level JSON and GeoJSON from:

- **GBIF Occurrence API:** capped samples of georeferenced occurrence records, including source fields and record links when supplied.
- **UNESCO DataHub — Man and the Biosphere dataset (mab001):** reserve metadata and source-provided point coordinates.
- **IUCN Red List API v4 (optional):** targeted assessment metadata for a small, explicitly curated list of selected species. It remains disabled by default and must not be enabled for public-output caching before the applicable permission is confirmed.

The generated density grid summarizes the returned sample. It is **not** a confirmed habitat boundary, a species-range polygon, a completeness measure, or evidence that a species is currently present throughout a grid cell. Likewise, UNESCO source points must not be presented as official reserve boundaries.

Explore the [pipeline folder](./biodiversity/) and its [usage and source notes](./biodiversity/README.md).

The country pipeline publishes lightweight spatial indexes for the initial map. Full GBIF occurrence metadata and UNESCO MAB descriptions are fetched from the source APIs only when a visitor opens a point or reserve; those descriptions are not copied into static mapping JSON. Source images, when available, are loaded by URL on demand rather than downloaded into the repository. The pipeline aborts if a generated JSON file exceeds its 45 MiB safety limit.

## Data-use and interpretation rules

- Follow each source's attribution, licence, API terms, rate limits, and any redistribution requirements.
- Check the original source record and its licence before reusing an occurrence, image, or research result.
- Do not interpret a missing record as proof that a species is absent.
- Do not treat a sample, representative map point, or density grid as a complete biodiversity inventory or formal conservation assessment.
- Verify critical information with the original data provider and relevant experts before using it for conservation decisions, policy, research conclusions, or publication.
- Respect third-party rights even when the website and source code are available without charge.

## Run the biodiversity pipeline

The scheduled workflow runs daily at 02:17 UTC (09:17 Jakarta time) and appends up to **300 new unique GBIF records for one country per run**. Countries are processed one at a time in a persisted round-robin rotation, beginning with Indonesia. Previously stored points are retained and GBIF IDs are deduplicated.

1. Open **Actions → Build biodiversity country datasets → Run workflow**.
2. Use **country_code = NEXT** to take the next country in the rotation, or enter one ISO-2 code such as **ID** to process a specific country.
3. Keep **max_records_per_country = 300** for up to 300 new unique records in the run. A run may add fewer when there are many duplicates, few remaining records, or a source/API issue.
4. Use **grid_size_degrees = 0.5** for the density grid. Keep **include_iucn_data = false** unless IUCN has confirmed that the proposed public caching/display use is permitted.
5. Review the action logs and the country’s cumulative counts after the workflow succeeds.

The workflow persists its rotation and page cursor in biodiversity/harvest-state.json. It progresses through country-wide result pages up to GBIF’s safe search-offset limit, then uses year/month and date partitions to continue without repeatedly fetching the same first page. This batch is **not necessarily records first created within the last 24 hours**; it is a new-to-this-repository batch of records reached by the saved cursor. Use **country_code = ALL** only when intentionally running every country in one manual run.

For IUCN enrichment, keep include_iucn_data false unless IUCN has confirmed that the intended caching/public-display use is permitted. Once authorized, use a short curated list in biodiversity/iucn_targets.json; the workflow requires the repository variable IUCN_PUBLICATION_APPROVED=true as an additional explicit gate. Store credentials only in GitHub Actions secrets, never in code or generated JSON.

See biodiversity/README.md for cursor, deduplication, and data-source details.

## Disclaimer

All tools and datasets are provided "as is", without warranty of any kind, subject to the applicable licences and terms. Source data can be incomplete, delayed, misclassified, or changed by its provider. Images and links may become unavailable. Maps and generated summaries are not professional advice or official determinations of species presence, distribution, conservation status, or protected-area boundaries.

The software is provided "as is", without warranty of any kind, subject to the full terms in [LICENSE](./LICENSE). Users are responsible for checking source licences, providing attribution, and obtaining any permissions needed for their own reuse or redistribution.

## Contributing and reuse

You are welcome to inspect, copy, and adapt the code for the permitted personal, educational, research, non-profit, and social-impact purposes described in [LICENSE](./LICENSE). If distributing modifications, follow the licence's source-availability and redistribution conditions. Contact the author for written permission before commercial use.

---

**Built independently for free access, open knowledge, and responsible data exploration.** Third-party data remains under its own terms.
