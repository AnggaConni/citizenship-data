import unittest

from scripts.build_fishstat_production import build_records, classify_source, norm_code, parse_number


class FishStatProductionTests(unittest.TestCase):
    def test_source_categories(self):
        self.assertEqual(classify_source("Capture production"), "Capture production")
        self.assertEqual(classify_source("Aquaculture production (marine)"), "Aquaculture production")
        self.assertEqual(classify_source("Aquaculture production (freshwater)"), "Aquaculture production")
        self.assertIsNone(classify_source("Imported fish products"))

    def test_normalizers(self):
        self.assertEqual(norm_code("360.0"), "360")
        self.assertEqual(norm_code("ID"), "ID")
        self.assertEqual(parse_number("1,234.5"), 1234.5)
        self.assertIsNone(parse_number(".."))

    def test_aggregation_is_country_year_source_and_unit_specific(self):
        countries = [
            {"un_code": "360", "iso2_code": "ID", "name_en": "Indonesia"},
            {"un_code": "608", "iso2_code": "PH", "name_en": "Philippines"},
        ]
        sources = [
            {"code": "1", "name_en": "Capture production"},
            {"code": "2", "name_en": "Aquaculture production (marine)"},
            {"code": "3", "name_en": "Aquaculture production (freshwater)"},
        ]
        production = [
            {"country_un_code": "360", "production_source_det_code": "1", "measure": "Q_tlw", "period": "2020", "value": "100", "status": "A", "species_alpha_3_code": "AAA", "area_code": "01"},
            {"country_un_code": "360", "production_source_det_code": "1", "measure": "Q_tlw", "period": "2020", "value": "50", "status": "E", "species_alpha_3_code": "BBB", "area_code": "02"},
            {"country_un_code": "360", "production_source_det_code": "2", "measure": "Q_tlw", "period": "2020", "value": "25.5", "status": "", "species_alpha_3_code": "CCC", "area_code": "00"},
            {"country_un_code": "360", "production_source_det_code": "3", "measure": "Q_tlw", "period": "2020", "value": "24.5", "status": "A", "species_alpha_3_code": "DDD", "area_code": "00"},
            {"country_un_code": "360", "production_source_det_code": "1", "measure": "Q_no_1", "period": "2020", "value": "999999", "status": "", "species_alpha_3_code": "EEE", "area_code": "00"},
            {"country_un_code": "608", "production_source_det_code": "1", "measure": "Q_tlw", "period": "1999", "value": "12", "status": "", "species_alpha_3_code": "FFF", "area_code": "00"},
            {"country_un_code": "999", "production_source_det_code": "1", "measure": "Q_tlw", "period": "2020", "value": "9000", "status": "", "species_alpha_3_code": "GGG", "area_code": "00"},
        ]
        records = build_records(production, countries, sources, start_year=2000)
        self.assertEqual(len(records), 2)
        capture = next(row for row in records if row["source"] == "Capture production")
        aquaculture = next(row for row in records if row["source"] == "Aquaculture production")
        self.assertEqual(capture["countryCode"], "ID")
        self.assertEqual(capture["year"], 2020)
        self.assertEqual(capture["unit"], "tonnes live weight")
        self.assertEqual(capture["value"], 150)
        self.assertEqual(capture["sourceFlags"], ["A", "E"])
        self.assertEqual(aquaculture["value"], 50)
        self.assertEqual(aquaculture["componentCount"], 2)


if __name__ == "__main__":
    unittest.main()
