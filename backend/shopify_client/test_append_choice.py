#!/usr/bin/env python3
"""
Unit tests for bite_shopify.append_choice capability echo.

Run from backend/:
    python -m unittest shopify_client.test_append_choice -v

Regression: metafieldDefinitionUpdate omits default capability fields to OFF.
append_choice must echo capabilities.smartCollectionCondition.enabled from the
live definition — never force true (subcategory_2 stays off).
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from shopify_client.bite_shopify import Shopify, ShopifyError


class AppendChoiceCapabilityEchoTests(unittest.TestCase):
    def _shop(self):
        s = Shopify.__new__(Shopify)
        s.domain = "example.myshopify.com"
        s.token = "test"
        s.api_version = "2025-07"
        s._cache = {}
        return s

    def test_echoes_smart_collection_condition_true(self):
        shop = self._shop()
        shop._cache[("mfdef", "custom", "subcategory", "PRODUCT")] = {
            "id": "gid://shopify/MetafieldDefinition/1",
            "choices": ["Existing"],
            "smart_collection_condition": True,
        }
        captured = {}

        def fake_gql(query, variables=None, retries=4):
            captured["variables"] = variables
            return {
                "metafieldDefinitionUpdate": {
                    "updatedDefinition": {"id": "gid://shopify/MetafieldDefinition/1"},
                    "userErrors": [],
                }
            }

        shop.gql = fake_gql
        result = shop.append_choice("custom", "subcategory", "New Label")
        self.assertTrue(result["added"])
        definition = captured["variables"]["def"]
        self.assertEqual(
            definition["capabilities"]["smartCollectionCondition"]["enabled"],
            True,
        )
        self.assertNotIn("useAsCollectionCondition", definition)
        choices = json.loads(definition["validations"][0]["value"])
        self.assertEqual(choices, ["Existing", "New Label"])

    def test_echoes_smart_collection_condition_false_for_subcategory_2(self):
        shop = self._shop()
        shop._cache[("mfdef", "custom", "subcategory_2", "PRODUCT")] = {
            "id": "gid://shopify/MetafieldDefinition/2",
            "choices": ["BLANK"],
            "smart_collection_condition": False,
        }
        captured = {}

        def fake_gql(query, variables=None, retries=4):
            captured["variables"] = variables
            return {
                "metafieldDefinitionUpdate": {
                    "updatedDefinition": {"id": "gid://shopify/MetafieldDefinition/2"},
                    "userErrors": [],
                }
            }

        shop.gql = fake_gql
        result = shop.append_choice("custom", "subcategory_2", "Overflow Label")
        self.assertTrue(result["added"])
        self.assertTrue(result.get("replaced_placeholder"))
        definition = captured["variables"]["def"]
        self.assertEqual(
            definition["capabilities"]["smartCollectionCondition"]["enabled"],
            False,
        )
        self.assertNotIn("useAsCollectionCondition", definition)
        choices = json.loads(definition["validations"][0]["value"])
        self.assertEqual(choices, ["Overflow Label"])

    def test_missing_api_version_fails_loudly(self):
        with patch("shopify_client.bite_shopify.STORE_DOMAIN", "example.myshopify.com"), patch(
            "shopify_client.bite_shopify.ACCESS_TOKEN", "tok"
        ), patch("shopify_client.bite_shopify.API_VERSION", None):
            with self.assertRaises(ShopifyError) as ctx:
                Shopify(domain="example.myshopify.com", token="tok", api_version=None)
            self.assertIn("API_VERSION", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
