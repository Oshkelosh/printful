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
    async def test_quote_shipping_returns_cents(self, monkeypatch):
        addon = PrintfulAddon()
        addon._client = AsyncMock()
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

    @pytest.mark.asyncio
    async def test_quote_shipping_returns_none_on_api_error(self, monkeypatch):
        from app.addons.suppliers.printful.client import PrintfulAPIError

        addon = PrintfulAddon()
        addon._client = AsyncMock()
        addon._client.get_shipping_rates = AsyncMock(
            side_effect=PrintfulAPIError("bad request", status_code=400)
        )
        cents = await addon.quote_shipping(
            [{"supplier_product_id": "99", "quantity": 1}],
            {"country": "US"},
        )
        assert cents is None
