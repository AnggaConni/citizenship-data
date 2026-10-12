# Country biodiversity data (pipeline under development)

The Python pipeline queries the public GBIF Occurrence API country by country. It generates one JSON file per country plus index.json.

Each country JSON contains:

- observations_geojson: individual georeferenced occurrence points.
- distribution_geojson: rectangular grid cells aggregated from those points, with occurrence and unique-taxon counts. This is a density layer, not a confirmed species-range or habitat boundary.
- summary and query: sampling limits, record counts, generated timestamp, errors, and data-source context.

## Run it

In GitHub, open Actions → Build biodiversity country datasets → Run workflow.

- country_code = ALL updates the countries returned by GBIF's country enumeration. Enter a two-letter GBIF country code (for example, ID) to run one country for testing.
- The default is 300 records per country. Increase the cap for denser samples, up to 9,900 records per country. GBIF's public occurrence search is paginated at up to 300 results per page, and the script stays below the high-offset boundary.
- The workflow also runs every Monday at 02:17 UTC.

The pipeline uses only Python's standard library. It retries transient API errors, continues if an individual country fails, preserves any previous good file for a country that fails, and records partial/errors in index.json.

## Interpretation and licensing

This is a reproducible, capped sample, not a complete extraction of GBIF. Coverage differs by country and is influenced by what datasets publish to GBIF, geographic coordinates, and the selected sample cap. Grid sizes are measured in degrees and therefore are not equal-area cells. GBIF occurrence records and attached media may have different licences; check each original record's metadata and conditions before reuse.

The future frontend is not included yet. The output schema is intended to support an interactive map with individual points and a country-level observation-density overlay.
