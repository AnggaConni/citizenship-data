import unittest

from scripts import build_biodiversity as pipeline


class BiodiversityPipelineTests(unittest.TestCase):
    def test_country_slug_removes_accents_and_punctuation(self):
        self.assertEqual(pipeline.slugify_country("Côte d’Ivoire", "CI"), "cote-divoire")
        self.assertEqual(pipeline.slugify_country("United States of America", "US"), "united-states-of-america")

    def test_occurrence_feature_uses_geojson_longitude_latitude_order(self):
        record = {
            "key": 12345,
            "speciesKey": 987,
            "scientificName": "Felis catus",
            "decimalLatitude": -6.2,
            "decimalLongitude": 106.8,
            "kingdom": "Animalia",
        }
        feature = pipeline.occurrence_feature(record, {"code": "ID", "name": "Indonesia"})
        self.assertEqual(feature["geometry"]["type"], "Point")
        self.assertEqual(feature["geometry"]["coordinates"], [106.8, -6.2])
        self.assertEqual(feature["properties"]["taxon_key"], 987)

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

    def test_invalid_coordinates_are_rejected(self):
        self.assertIsNone(pipeline.valid_coordinates({"decimalLatitude": 91, "decimalLongitude": 0}))
        self.assertIsNone(pipeline.valid_coordinates({"decimalLatitude": "north", "decimalLongitude": 0}))


if __name__ == "__main__":
    unittest.main()
