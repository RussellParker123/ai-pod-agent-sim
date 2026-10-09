import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from app.connectors.etsy_connector import EtsyAPIError, EtsyConnector
from app.sim import agents
from app.sim.agents import Design, compliance_agent, trend_agent


class StubEtsyConnector:
    def get_top_trending_search_terms(self, limit=10):
        return [
            {"term": "cozy autumn", "count": 8},
            {"term": "bookish humor", "count": 4},
        ][:limit]

    def get_historical_flagged_items(self):
        return [{"title": "Cozy autumn artwork", "tags": ["cozy", "autumn"]}]


class EtsyIntegrationTests(unittest.TestCase):
    def test_trend_agent_uses_store_terms(self):
        designs = trend_agent(
            ["mock niche"],
            k=10,
            etsy_connector=StubEtsyConnector(),
        )

        self.assertEqual([design.niche for design in designs], ["cozy autumn", "bookish humor"])
        self.assertGreater(designs[0].trend_score, designs[1].trend_score)

    def test_trend_connector_ranks_listing_tags_by_frequency(self):
        connector = EtsyConnector("123", "key", "secret", access_token="token")
        connector._get_listings = lambda state: [
            {"tags": ["coffee", "gift"]},
            {"tags": ["coffee"]},
        ]

        self.assertEqual(
            connector.get_top_trending_search_terms(),
            [{"term": "coffee", "count": 2}, {"term": "gift", "count": 1}],
        )

    def test_marketplace_search_deduplicates_and_ranks_across_niches(self):
        connector = EtsyConnector("123", "key", "secret", access_token="token")
        queries = []

        def get(path, query):
            queries.append((path, query))
            if query["keywords"] == "coffee":
                return {
                    "results": [
                        {
                            "listing_id": 1,
                            "title": "Retro coffee mug",
                            "tags": ["retro", "coffee"],
                            "views": 20,
                            "num_favorers": 4,
                        }
                    ]
                }
            return {
                "results": [
                    {
                        "listing_id": 1,
                        "title": "Retro coffee mug",
                        "tags": ["retro", "coffee"],
                        "views": 20,
                        "num_favorers": 4,
                    },
                    {
                        "listing_id": 2,
                        "title": "Minimal pet tote",
                        "tags": ["minimalist", "pet"],
                        "views": 40,
                        "num_favorers": 1,
                    },
                ]
            }

        connector._get = get

        results = connector.get_marketplace_listings(["coffee", "pets"], limit=2)

        self.assertEqual([item["listing_id"] for item in results], [2, 1])
        self.assertEqual(results[0]["demand"], 45)
        self.assertEqual(len(queries), 2)
        self.assertTrue(all(path == "listings/active" for path, _ in queries))
        self.assertTrue(all(query["sort_on"] == "score" for _, query in queries))

    def test_trend_agent_falls_back_when_etsy_fails(self):
        class BrokenConnector:
            def get_top_trending_search_terms(self, limit=10):
                raise EtsyAPIError("offline")

        with patch.object(agents.random, "choice", return_value="mock niche"):
            designs = trend_agent(["mock niche"], k=1, etsy_connector=BrokenConnector())

        self.assertEqual(designs[0].niche, "mock niche")

    def test_compliance_agent_flags_similarity_to_inactive_listing(self):
        design = Design("D001", "cozy autumn", 0.8)

        compliance_agent([design], etsy_connector=StubEtsyConnector())

        self.assertEqual(design.compliance_status, "flagged")
        self.assertIn("Cozy autumn artwork", design.compliance_notes)

    def test_inventory_converts_etsy_money_to_decimal_price(self):
        connector = EtsyConnector("123", "key", "secret", access_token="token")
        connector._get_listings = lambda state: [
            {
                "listing_id": 5,
                "title": "Mug",
                "tags": ["coffee"],
                "quantity": 3,
                "price": {"amount": 1250, "divisor": 100, "currency_code": "USD"},
            }
        ]

        self.assertEqual(
            connector.get_inventory(),
            [
                {
                    "listing_id": 5,
                    "title": "Mug",
                    "tags": ["coffee"],
                    "quantity": 3,
                    "price": 12.5,
                    "currency_code": "USD",
                }
            ],
        )

    def test_rate_limit_is_reported_as_connector_error(self):
        connector = EtsyConnector("123", "key", "secret", access_token="token")
        error = HTTPError("https://example.test", 429, "rate limited", {}, None)

        with patch("app.connectors.etsy_connector.urlopen", side_effect=error):
            with self.assertRaisesRegex(EtsyAPIError, "rate limit"):
                connector._get("shops/123/listings/active")


if __name__ == "__main__":
    unittest.main()
