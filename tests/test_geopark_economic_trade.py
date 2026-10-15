import unittest
from datetime import datetime, timezone

from scripts.build_geopark_economic_trade import (
    aggregate_products,
    build_country_record,
    reporter_lookup,
)


class GeoparkEconomicTradeTests(unittest.TestCase):
    def test_reporter_lookup_uses_active_iso3_and_discards_groups(self):
        payload = {
            "results": [
                {"reporterCodeIsoAlpha3": "IDN", "reporterCode": 360, "reporterDesc": "Indonesia"},
                {"reporterCodeIsoAlpha3": "IDN", "reporterCode": 999, "reporterDesc": "Indonesia Group", "isGroup": True},
                {"reporterCodeIsoAlpha3": "ZZZ", "reporterCode": 999, "reporterDesc": "Unknown"},
                {"reporterCodeIsoAlpha3": "MYS", "reporterCode": 458, "reporterDesc": "Malaysia", "entryExpiredDate": "2020-01-01"},
            ]
        }
        lookup = reporter_lookup(payload)
        self.assertEqual(lookup, {"IDN": {"reporterCode": 360, "countryName": "Indonesia"}})

    def test_aggregate_products_separates_years_and_skips_total_rows(self):
        rows = [
            {"period": "2024", "cmdCode": "01", "cmdDesc": "Live animals", "primaryValue": 100},
            {"period": "2024", "cmdCode": "01", "cmdDesc": "Live animals", "primaryValue": 25},
            {"period": "2024", "cmdCode": "02", "cmdDesc": "Meat", "primaryValue": 75},
            {"period": "2025", "cmdCode": "01", "cmdDesc": "Live animals", "primaryValue": 200},
            {"period": "2025", "cmdCode": "TOTAL", "cmdDesc": "All products", "primaryValue": 9999},
            {"period": "bad", "cmdCode": "03", "cmdDesc": "Fish", "primaryValue": 50},
        ]
        result = aggregate_products(rows)
        self.assertEqual(result[2024]["01"]["valueUsd"], 125)
        self.assertEqual(result[2025]["01"]["valueUsd"], 200)
        self.assertNotIn("TOTAL", result[2025])
        self.assertNotIn(2026, result)

    def test_country_uses_latest_year_and_computes_total_from_product_groups(self):
        reporter = {"reporterCode": 360, "countryName": "Indonesia"}
        rows = [
            {"period": "2024", "cmdCode": "01", "cmdDesc": "Live animals", "primaryValue": 100},
            {"period": "2024", "cmdCode": "02", "cmdDesc": "Meat", "primaryValue": 70},
            {"period": "2025", "cmdCode": "01", "cmdDesc": "Live animals", "primaryValue": 200},
            {"period": "2025", "cmdCode": "02", "cmdDesc": "Meat", "primaryValue": 80},
        ]
        result = build_country_record("IDN", reporter, rows, [2022, 2023, 2024, 2025])
        self.assertTrue(result["available"])
        self.assertEqual(result["latestYear"], 2025)
        self.assertEqual(result["totalImportUsd"], 280)
        self.assertEqual(result["productCount"], 2)
        self.assertEqual(result["products"][0]["name"], "Live animals")
        self.assertIn("not geopark-level", result["note"])

    def test_empty_country_is_explicitly_unavailable_not_zero_activity(self):
        result = build_country_record(
            "MYS",
            {"reporterCode": 458, "countryName": "Malaysia"},
            [],
            [2022, 2023, 2024, 2025],
        )
        self.assertFalse(result["available"])
        self.assertIsNone(result["totalImportUsd"])
        self.assertEqual(result["productCount"], 0)
        self.assertIn("No product-level", result["note"])


if __name__ == "__main__":
    unittest.main()
