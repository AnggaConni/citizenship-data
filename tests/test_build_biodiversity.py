import json
import unittest
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts import build_biodiversity as pipeline


class BiodiversityPipelineTests(unittest.TestCase):
    def test_daily_default_and_manual_bulk_limit(self):
        self.assertEqual(pipeline.DEFAULT_RECORDS_PER_COUNTRY, 300)
        self.assertEqual(pipeline.MAX_RECORDS_PER_COUNTRY, 9000)
        self.assertEqual(pipeline.PAGE_SIZE, 300)
        self.assertGreaterEqual(
            pipeline.MAX_BATCH_PAGE_REQUESTS,
            (pipeline.MAX_RECORDS_PER_COUNTRY + pipeline.PAGE_SIZE - 1) // pipeline.PAGE_SIZE,
        )

    def test_country_slug_removes_accents_and_punctuation(self):
        self.assertEqual(pipeline.slugify_country("Côte d’Ivoire", "CI"), "cote-divoire")
        self.assertEqual(pipeline.slugify_country("United States of America", "US"), "united-states-of-america")

    def test_occurrence_feature_contains_only_map_fields(self):
        record = {
            "key": 12345,
            "speciesKey": 987,
            "scientificName": "Felis catus",
            "decimalLatitude": -6.2,
            "decimalLongitude": 106.8,
            "kingdom": "Animalia",
            "habitat": "Urban areas",
            "recordedBy": "Observer",
            "media": [{"identifier": "https://example.org/cat.jpg"}],
        }
        feature = pipeline.occurrence_feature(record, {"code": "ID", "name": "Indonesia"})
        self.assertEqual(feature["geometry"]["type"], "Point")
        self.assertEqual(feature["geometry"]["coordinates"], [106.8, -6.2])
        self.assertEqual(feature["properties"]["taxon_key"], 987)
        self.assertNotIn("recordedBy", feature["properties"])
        self.assertNotIn("description", feature["properties"])
        self.assertNotIn("habitat", feature["properties"])
        self.assertNotIn("media", feature["properties"])
        self.assertNotIn("image_url", feature["properties"])
        self.assertEqual(feature["properties"]["scientific_name"], "Felis catus")
        self.assertEqual(feature["properties"]["gbif_id"], 12345)

    def test_occurrence_static_feature_excludes_image_and_long_details(self):
        record = {
            "key": 98765,
            "speciesKey": 123,
            "scientificName": "Felis catus",
            "decimalLatitude": -6.2,
            "decimalLongitude": 106.8,
            "occurrenceRemarks": "R" * 10000,
            "media": [
                {
                    "identifier": "https://example.org/cat.png",
                    "type": "StillImage",
                    "large_metadata_blob": "binary-placeholder" * 500,
                }
            ],
            "unneeded_upstream_payload": "X" * 50000,
        }
        feature = pipeline.occurrence_feature(record, {"code": "ID", "name": "Indonesia"})
        props = feature["properties"]
        self.assertNotIn("image_url", props)
        self.assertNotIn("media", props)
        self.assertNotIn("occurrenceRemarks", props)
        self.assertNotIn("unneeded_upstream_payload", props)
        self.assertLess(len(json.dumps(feature)), 1500)

    def test_build_dataset_appends_new_records_and_compacts_old_payload(self):
        previous = {
            "schema_version": 3,
            "country": {"code": "ID", "name": "Indonesia"},
            "observations_geojson": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature", "id": "1",
                        "geometry": {"type": "Point", "coordinates": [106.8, -6.2]},
                        "properties": {
                            "key": 1, "gbif_id": 1, "taxon_key": 10,
                            "scientific_name": "Felis catus", "kingdom": "Animalia",
                            "description": "Old verbose description", "media": [{"identifier": "https://example.org/a.jpg"}],
                        },
                    },
                    {
                        "type": "Feature", "id": "2",
                        "geometry": {"type": "Point", "coordinates": [107.0, -6.3]},
                        "properties": {"key": 2, "gbif_id": 2, "scientific_name": "Canis lupus"},
                    },
                ],
            },
        }
        records = [
            {"key": 2, "scientificName": "Canis lupus", "decimalLatitude": -6.3, "decimalLongitude": 107.0},
            {"key": 3, "speciesKey": 30, "species": "Felis catus", "decimalLatitude": -6.4, "decimalLongitude": 107.1},
        ]
        dataset = pipeline.build_dataset(
            {"code": "ID", "name": "Indonesia"}, records, 3812893, len(records), [],
            300, 0.5, previous_dataset=previous,
            harvest_meta={"mode": "incremental-append", "batch_goal_met": False},
        )
        features = dataset["observations_geojson"]["features"]
        self.assertEqual(len(features), 3)
        self.assertEqual(dataset["summary"]["previous_points_retained"], 2)
        self.assertEqual(dataset["summary"]["new_occurrence_records_added"], 1)
        self.assertEqual(dataset["summary"]["mapped_occurrence_points"], 3)
        self.assertNotIn("description", features[0]["properties"])
        self.assertNotIn("media", features[0]["properties"])
        self.assertEqual({str(f["properties"]["gbif_id"]) for f in features}, {"1", "2", "3"})

    @patch("scripts.build_biodiversity.request_json")
    def test_incremental_fetch_deduplicates_and_resumes_cursor(self, request_mock):
        def row(key, lat=-6.2, lon=106.8):
            return {
                "key": key, "speciesKey": key + 10, "species": "Test taxon",
                "decimalLatitude": lat, "decimalLongitude": lon,
            }
        request_mock.side_effect = [
            {"count": 1000, "results": [row(1), row(2)]},
            {"count": 1000, "results": [row(3)]},
        ]
        cursor = {"mode": "country", "offset": 300, "year": 2026, "month": 10, "day": None}
        records, raw_count, errors, next_cursor, meta = pipeline.fetch_incremental_records(
            "ID", 2, cursor, {"1"}
        )
        self.assertEqual([r["key"] for r in records], [2, 3])
        self.assertEqual(raw_count, 3)
        self.assertEqual(errors, [])
        self.assertEqual(next_cursor["offset"], 303)
        self.assertEqual(meta["pages_queried"], 2)
        self.assertEqual(request_mock.call_args_list[0].args[1]["offset"], 300)
        self.assertEqual(request_mock.call_args_list[1].args[1]["offset"], 302)
        self.assertEqual(request_mock.call_args_list[1].args[1]["limit"], 1)

    @patch("scripts.build_biodiversity.request_json")
    def test_incremental_fetch_splits_overfull_month_into_days(self, request_mock):
        record = {
            "key": 42, "speciesKey": 99, "species": "Test taxon",
            "decimalLatitude": -6.2, "decimalLongitude": 106.8,
        }
        request_mock.side_effect = [
            {"count": 12000, "results": [record]},
            {"count": 1, "results": [record]},
        ]
        cursor = {"mode": "month", "offset": 0, "year": 2024, "month": 5, "day": None}
        records, raw_count, errors, next_cursor, meta = pipeline.fetch_incremental_records(
            "ID", 1, cursor, set()
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(raw_count, 1)
        self.assertEqual(errors, [])
        self.assertEqual(request_mock.call_args_list[1].args[1]["eventDate"], "2024-05-01")
        self.assertEqual(next_cursor["day"], 2)
        self.assertEqual(meta["pages_queried"], 2)

    def test_distribution_grid_aggregates_points(self):
        features = [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [106.8, -6.2]},
             "properties": {"taxon_key": 1, "scientific_name": "Taxon one", "kingdom": "Animalia"}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [106.9, -6.1]},
             "properties": {"taxon_key": 2, "scientific_name": "Taxon two", "kingdom": "Plantae"}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [110.1, -7.5]},
             "properties": {"taxon_key": 1, "scientific_name": "Taxon one", "kingdom": "Animalia"}},
        ]
        grid = pipeline.distribution_grid(features, 0.5)
        self.assertEqual(grid["type"], "FeatureCollection")
        self.assertEqual(len(grid["features"]), 2)
        busiest = max(grid["features"], key=lambda item: item["properties"]["observation_count"])
        self.assertEqual(busiest["properties"]["observation_count"], 2)
        self.assertEqual(busiest["properties"]["unique_taxa_count"], 2)

    def test_mab_map_index_excludes_long_details_and_images(self):
        record = {
            "mab_id": "TEST-COMPACT",
            "title_en": "A Compact Reserve",
            "iso2": "ID",
            "country_title_en": "Indonesia",
            "coordinates": {"lat": -6.2, "lon": 106.8},
            "main_image_url": "https://example.org/reserve.jpg",
            "introduction_en": "A" * 10000,
            "ecological_characteristics_en": "B" * 10000,
            "unneeded_attachment": "Y" * 1000000,
        }
        normalized = pipeline.normalize_biosphere_record(record)
        feature = pipeline.biosphere_feature(record)
        self.assertNotIn("unneeded_attachment", normalized)
        self.assertNotIn("introduction_en", normalized)
        self.assertNotIn("ecological_characteristics_en", normalized)
        self.assertNotIn("description", normalized)
        self.assertNotIn("main_image_url", feature["properties"])
        self.assertNotIn("description", feature["properties"])
        self.assertLess(len(json.dumps(feature)), 1500)

    def test_biosphere_geojson_reverses_lat_lon_and_keeps_description(self):
        record = {
            "mab_id": "TEST-1",
            "title_en": "Example Biosphere",
            "iso2": "ID",
            "country_title_en": "Indonesia",
            "coordinates": [-6.2, 106.8],
            "introduction_en": "A reserve introduction.",
            "ecological_characteristics_en": "Forest and wetlands.",
        }
        feature = pipeline.biosphere_feature(record)
        self.assertEqual(feature["geometry"]["type"], "Point")
        self.assertEqual(feature["geometry"]["coordinates"], [106.8, -6.2])
        normalized = pipeline.normalize_biosphere_record(record)
        self.assertNotIn("description", normalized)
        self.assertEqual(feature["properties"]["country_code"], "ID")
        self.assertNotIn("description", feature["properties"])


    def test_iucn_target_normalization_and_allowlist_deduplication(self):
        self.assertEqual(
            pipeline.normalize_iucn_target({"genus_name": "Pongo", "species_name": "pygmaeus"})["scientific_name"],
            "Pongo pygmaeus",
        )
        self.assertIsNone(pipeline.normalize_iucn_target({"genus_name": "", "species_name": "pygmaeus"}))
        with TemporaryDirectory() as temporary_dir:
            target_path = Path(temporary_dir) / "targets.json"
            target_path.write_text(json.dumps({"species": [
                {"genus_name": "Pongo", "species_name": "pygmaeus"},
                {"genus_name": "pongo", "species_name": "PYGMAEUS"},
                {"genus_name": "Varanus", "species_name": "komodoensis"},
            ]}), encoding="utf-8")
            targets = pipeline.load_iucn_targets(target_path)
            self.assertEqual(len(targets), 2)

    def test_iucn_response_prefers_latest_global_assessment(self):
        target = {
            "genus_name": "Pongo",
            "species_name": "pygmaeus",
            "scientific_name": "Pongo pygmaeus",
        }
        payload = {
            "taxon": {"sis_id": 111, "scientific_name": "Pongo pygmaeus"},
            "assessments": [
                {
                    "latest": True,
                    "assessment_date": "2022-01-01",
                    "year_published": "2022",
                    "red_list_category_code": "EN",
                    "criteria": "A2",
                    "assessment_id": 2,
                    "url": "https://www.iucnredlist.org/species/111/2",
                    "scopes": [{"code": "4", "description": {"en": "Mediterranean"}}],
                },
                {
                    "latest": True,
                    "assessment_date": "2016-01-01",
                    "year_published": "2016",
                    "red_list_category_code": "CR",
                    "criteria": "A2",
                    "assessment_id": 1,
                    "url": "https://www.iucnredlist.org/species/111/1",
                    "scopes": [{"code": "1", "description": {"en": "Global"}}],
                },
            ],
        }
        result = pipeline.normalize_iucn_response(target, payload)
        self.assertEqual(result["status"], "assessed")
        self.assertEqual(result["red_list_category_code"], "CR")
        self.assertEqual(result["red_list_category"], "Critically Endangered")
        self.assertEqual(result["scope_code"], "1")
        self.assertEqual(result["assessment_url"], "https://www.iucnredlist.org/species/111/1")

    def test_iucn_response_handles_species_without_assessment(self):
        result = pipeline.normalize_iucn_response(
            {"scientific_name": "Unknown species"},
            {"taxon": {"scientific_name": "Unknown species"}, "assessments": []},
        )
        self.assertEqual(result["status"], "no_assessment_found")

    @patch("scripts.build_biodiversity.request_json")
    def test_fetch_biosphere_records_reads_flattened_v21_results(self, request_mock):
        request_mock.return_value = {
            "total_count": 2,
            "results": [
                {
                    "mab_id": "TEST-MAB-A",
                    "title_en": "Reserve A",
                    "iso2": "ID",
                    "country_title_en": "Indonesia",
                    "coordinates": {"lat": -6.2, "lon": 106.8},
                },
                {
                    "mab_id": "TEST-MAB-B",
                    "title_en": "Reserve B",
                    "iso2": "ID",
                    "country_title_en": "Indonesia",
                    "coordinates": {"lat": -7.1, "lon": 110.4},
                },
            ],
        }
        records = pipeline.fetch_biosphere_records()
        self.assertEqual(len(records), 2)
        self.assertEqual({row["biosphere_id"] for row in records}, {"TEST-MAB-A", "TEST-MAB-B"})
        self.assertEqual(records[0]["country_code"], "ID")
        args, kwargs = request_mock.call_args
        self.assertIn("select", args[1])
        self.assertEqual(args[1]["select"], ",".join(pipeline.MAB_API_FIELDS))

    def test_mab_map_index_keeps_api_record_id(self):
        wrapped = {
            "recordid": "abcd-1234",
            "mab_id": "MAB-11",
            "title_en": "Reserve Eleven",
            "iso2": "ID",
            "country_title_en": "Indonesia",
            "coordinates": {"lat": -6.2, "lon": 106.8},
            "introduction_en": "This lengthy narrative is intentionally not stored in the map index.",
        }
        fields = pipeline.extract_unesco_fields(wrapped)
        feature = pipeline.biosphere_feature(fields)
        self.assertEqual(feature["properties"]["api_record_id"], "abcd-1234")
        self.assertNotIn("introduction_en", feature["properties"])
        output = pipeline.build_biosphere_dataset([fields])
        self.assertNotIn("records", output)
        self.assertEqual(len(output["geojson"]["features"]), 1)

    def test_unesco_v21_flattened_results_are_supported(self):
        record = {
            "mab_id": "TEST-MAB-1",
            "title_en": "Example Biosphere Reserve",
            "iso2": "ID",
            "country_title_en": "Indonesia",
            "coordinates": {"lat": -6.2, "lon": 106.8},
            "introduction_en": "An example reserve.",
        }
        fields = pipeline.extract_unesco_fields(record)
        self.assertEqual(fields["mab_id"], "TEST-MAB-1")
        feature = pipeline.biosphere_feature(fields)
        self.assertEqual(feature["geometry"]["coordinates"], [106.8, -6.2])
        self.assertEqual(feature["properties"]["country_code"], "ID")

    def test_unesco_nested_record_response_is_supported(self):
        wrapped = {"record": {"fields": {
            "mab_id": "TEST-MAB-2",
            "title_en": "Nested Example",
            "iso2": "ID",
            "geo_point_2d": {"lat": -7.1, "lon": 110.4},
        }}}
        fields = pipeline.extract_unesco_fields(wrapped)
        feature = pipeline.biosphere_feature(fields)
        self.assertEqual(feature["geometry"]["coordinates"], [110.4, -7.1])

    def test_oversize_json_is_rejected_before_overwriting_target(self):
        with TemporaryDirectory() as temporary_dir:
            output = Path(temporary_dir) / "large.json"
            output.write_text("previous-version", encoding="utf-8")
            old_limit = pipeline.MAX_PUBLISHED_JSON_BYTES
            try:
                pipeline.MAX_PUBLISHED_JSON_BYTES = 32
                with self.assertRaises(ValueError):
                    pipeline.write_json(output, {"payload": "x" * 1000})
                self.assertEqual(output.read_text(encoding="utf-8"), "previous-version")
            finally:
                pipeline.MAX_PUBLISHED_JSON_BYTES = old_limit

    def test_invalid_coordinates_are_rejected(self):
        self.assertIsNone(pipeline.valid_coordinates({"decimalLatitude": 91, "decimalLongitude": 0}))
        self.assertIsNone(pipeline.valid_coordinates({"decimalLatitude": "north", "decimalLongitude": 0}))


if __name__ == "__main__":
    unittest.main()
