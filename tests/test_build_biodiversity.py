import json
import unittest
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts import build_biodiversity as pipeline


class BiodiversityPipelineTests(unittest.TestCase):
    def test_country_slug_removes_accents_and_punctuation(self):
        self.assertEqual(pipeline.slugify_country("Côte d’Ivoire", "CI"), "cote-divoire")
        self.assertEqual(pipeline.slugify_country("United States of America", "US"), "united-states-of-america")

    def test_occurrence_feature_preserves_source_payload_and_description(self):
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
        self.assertEqual(feature["properties"]["recordedBy"], "Observer")
        self.assertIn("Urban areas", feature["properties"]["description"])
        self.assertEqual(feature["properties"]["media"], record["media"])

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
        self.assertIn("A reserve introduction.", feature["properties"]["description"])
        self.assertEqual(feature["properties"]["country_code"], "ID")


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

    def test_invalid_coordinates_are_rejected(self):
        self.assertIsNone(pipeline.valid_coordinates({"decimalLatitude": 91, "decimalLongitude": 0}))
        self.assertIsNone(pipeline.valid_coordinates({"decimalLatitude": "north", "decimalLongitude": 0}))


if __name__ == "__main__":
    unittest.main()
