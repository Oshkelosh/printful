"""Unit tests for the Printful supplier addon."""

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
