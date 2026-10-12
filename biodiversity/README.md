# Country biodiversity and biosphere data

This pipeline builds country-level JSON files from two separate public sources:

- **GBIF Occurrence API** for individual biodiversity observations and their source metadata.
- **UNESCO DataHub — Man and the Biosphere Programme (dataset mab001)** for reserve names, country, published introduction/ecological characteristics, metadata and source-provided point coordinates.

## Files generated

- indonesia.json and other country files: the requested GBIF occurrence sample, full source payload fields for each returned observation (where exposed by the API), a standardized description field when descriptive terms are present, point GeoJSON, density-grid GeoJSON, and matching UNESCO reserve records/features.
- biosphere.json: the global UNESCO MAB dataset, with reserve records and GeoJSON point features.
- index.json: country file metadata, sample counts, and biosphere source status.

## Run it

Open **Actions → Build biodiversity country datasets → Run workflow**.

- country_code = ID updates Indonesia only; ALL updates all countries returned by GBIF enumeration.
- max_records_per_country defaults to 300 and can be increased to at most 9,900. GBIF reports millions of matching records for some countries, but the search endpoint is capped/paginated; this pipeline deliberately creates a reproducible sample rather than a complete GBIF extract.
- grid_size_degrees controls the rectangular grid used for the biodiversity density layer. A 0.5-degree cell is an exploratory count cell, not a species habitat boundary or a uniform-area cell.
- The workflow also runs each Monday at 02:17 UTC.

## About descriptions and completeness

GBIF does not provide a narrative description for every observation. The pipeline preserves source fields returned in the occurrence payload and derives a normalized description from available terms such as description, taxonRemarks, occurrenceRemarks, habitat, eventRemarks, fieldNotes, and identificationRemarks. If none are provided by a source record, the description can be null. This is not an encyclopedic description of every species.

## UNESCO MAB source and licensing

The UNESCO DataHub mab001 dataset is provided under **CC BY-SA 4.0** and is attributed to UNESCO. Preserve this attribution and review the licence requirements before redistributing adapted datasets. The endpoint currently provides reserve coordinates as points, plus descriptive fields such as introduction_en and ecological_characteristics_en; it is not an official reserve-boundary polygon API. The point layer must not be styled as an entire reserve area.

GBIF source record licences vary; individual record licence and source URL fields are retained. Check the original record and dataset-level requirements before reuse.

The frontend is intentionally not included yet. Its future map can show individual occurrence points, density grid cells, and a separate UNESCO biosphere-reserve point layer.
