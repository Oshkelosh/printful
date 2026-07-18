"""Unit tests for the Printful supplier addon."""

from unittest.mock import AsyncMock

import pytest

from app.addons.suppliers.printful.addon import PrintfulAddon, PrintfulConfig


class TestPrintfulAddon:
    def test_printful_addon_has_required_attrs(self):
        assert hasattr(PrintfulAddon, "addon_id")
        assert hasattr(PrintfulAddon, "addon_name")
        assert hasattr(PrintfulAddon, "addon_description")
        assert hasattr(PrintfulAddon, "addon_category")
        assert hasattr(PrintfulAddon, "config_schema")
        assert PrintfulAddon.addon_id == "printful"
        assert PrintfulAddon.addon_category == "supplier"

    def test_printful_config_schema(self):
        config = PrintfulConfig(api_key="test-key", is_active=True, auto_confirm=False)
        assert config.api_key.get_secret_value() == "test-key"
        assert config.is_active is True
        assert config.auto_confirm is False

    def test_printful_config_requires_api_key(self):
        with pytest.raises(Exception):
            PrintfulConfig()

    def test_supports_shipping_quotes(self):
        assert PrintfulAddon().supports_shipping_quotes() is True

    @pytest.mark.asyncio
    async def test_quote_shipping_returns_cents(self):
        addon = PrintfulAddon()
        addon._client = AsyncMock()
        addon._rate_variant_ids = {}
        addon._client.get_sync_variant = AsyncMock(
            return_value={"result": {"sync_variant": {"id": 99, "variant_id": 4011}}}
        )
        addon._client.get_shipping_rates = AsyncMock(
            return_value={
                "result": [
                    {"id": "STANDARD", "rate": "12.34"},
                ]
            }
        )
        cents = await addon.quote_shipping(
            [{"supplier_product_id": "99", "quantity": 1}],
            {"line1": "1 Main", "city": "Austin", "postal_code": "78701", "country": "US"},
        )
        assert cents == 1234
        addon._client.get_shipping_rates.assert_awaited_once()
        assert addon._client.get_shipping_rates.await_args.args[1] == [
            {"variant_id": 4011, "quantity": 1}
        ]
        assert addon._rate_variant_ids["99"] == 4011

    @pytest.mark.asyncio
    async def test_quote_shipping_uses_cached_catalog_variant_id(self):
        addon = PrintfulAddon()
        addon._client = AsyncMock()
        addon._rate_variant_ids = {"99": 4011}
        addon._client.get_sync_variant = AsyncMock()
        addon._client.get_shipping_rates = AsyncMock(
            return_value={"result": [{"id": "STANDARD", "rate": "5.00"}]}
        )
        cents = await addon.quote_shipping(
            [{"supplier_product_id": "99", "quantity": 2}],
            {"country": "US"},
        )
        assert cents == 500
        addon._client.get_sync_variant.assert_not_awaited()
        assert addon._client.get_shipping_rates.await_args.args[1] == [
            {"variant_id": 4011, "quantity": 2}
        ]

    @pytest.mark.asyncio
    async def test_quote_shipping_returns_none_when_variant_unresolvable(self):
        from app.addons.suppliers.printful.client import PrintfulAPIError

        addon = PrintfulAddon()
        addon._client = AsyncMock()
        addon._rate_variant_ids = {}
        addon._client.get_sync_variant = AsyncMock(
            side_effect=PrintfulAPIError("not found", status_code=404)
        )
        addon._client.get_shipping_rates = AsyncMock()
        cents = await addon.quote_shipping(
            [{"supplier_product_id": "99", "quantity": 1}],
            {"country": "US"},
        )
        assert cents is None
        addon._client.get_shipping_rates.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_quote_shipping_returns_none_on_api_error(self):
        from app.addons.suppliers.printful.client import PrintfulAPIError

        addon = PrintfulAddon()
        addon._client = AsyncMock()
        addon._rate_variant_ids = {}
        addon._client.get_sync_variant = AsyncMock(
            return_value={"result": {"sync_variant": {"id": 99, "variant_id": 4011}}}
        )
        addon._client.get_shipping_rates = AsyncMock(
            side_effect=PrintfulAPIError("bad request", status_code=400)
        )
        cents = await addon.quote_shipping(
            [{"supplier_product_id": "99", "quantity": 1}],
            {"country": "US"},
        )
        assert cents is None
