"""Tests for Printful list_products three-step catalog fetch."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.addons.suppliers.printful.addon import PrintfulAddon


@pytest.mark.asyncio
async def test_list_products_fetches_product_and_variant_details():
    addon = PrintfulAddon()
    addon._client = AsyncMock()
    addon._client.list_sync_products.return_value = {
        "result": [
            {
                "id": 378560852,
                "name": "Amaryllis Solandraeflora",
                "variants": 4,
                "synced": 4,
                "thumbnail_url": "https://example.com/product.png",
            }
        ],
        "paging": {"total": 1, "offset": 0, "limit": 100},
    }
    addon._client.get_sync_product.return_value = {
        "result": {
            "sync_product": {"id": 378560852, "name": "Amaryllis Solandraeflora"},
            "sync_variants": [
                {"id": 1001, "synced": True, "retail_price": "10.00", "sku": "A"},
                {"id": 1002, "synced": True, "retail_price": "11.00", "sku": "B"},
                {"id": 1003, "synced": True, "retail_price": "12.00", "sku": "C"},
                {"id": 1004, "synced": True, "retail_price": "13.00", "sku": "D"},
            ],
        }
    }

    async def _variant_detail(variant_id: str):
        vid = int(variant_id)
        return {
            "result": {
                "id": vid,
                "name": "Amaryllis Solandraeflora",
                "size": f"Size{vid}",
                "synced": True,
                "retail_price": f"{9 + vid - 1000}.00",
                "sku": chr(ord("A") + vid - 1001),
                "files": [
                    {
                        "visible": True,
                        "preview_url": f"https://example.com/mockup-{vid}.png",
                    }
                ],
                "product": {"name": f"Catalog garment {vid}"},
            }
        }

    addon._client.get_sync_variant.side_effect = _variant_detail

    rows = await addon.list_products()

    assert len(rows) == 4
    assert {row["id"] for row in rows} == {"1001", "1002", "1003", "1004"}
    assert rows[0]["thumbnail_url"] == "https://example.com/mockup-1001.png"
    assert rows[0]["description"] == "Catalog garment 1001"
    assert addon._client.get_sync_product.await_count == 1
    assert addon._client.get_sync_variant.await_count == 4


@pytest.mark.asyncio
async def test_fetch_catalog_for_import_returns_four_items():
    addon = PrintfulAddon()
    addon._client = AsyncMock()
    addon._client.list_sync_products.return_value = {
        "result": [{"id": 1, "name": "Tee", "variants": 2, "synced": 2}],
        "paging": {"total": 1},
    }
    addon._client.list_categories = AsyncMock(return_value={"result": []})
    addon._client.get_sync_product.return_value = {
        "result": {
            "sync_variants": [
                {"id": 10, "synced": True, "retail_price": "20.00"},
                {"id": 11, "synced": True, "retail_price": "21.00"},
            ]
        }
    }
    addon._client.get_sync_variant.side_effect = lambda vid: {
        "result": {
            "id": int(vid),
            "name": "Tee",
            "synced": True,
            "retail_price": "20.00" if vid == "10" else "21.00",
            "files": [{"visible": True, "preview_url": f"https://example.com/{vid}.png"}],
        }
    }

    items = await addon.fetch_catalog_for_import()

    variants = [variant for product in items for variant in product.variants]
    assert len(variants) == 2
    assert all(variant.skip_reason is None for variant in variants)
    assert variants[0].image_urls == ["https://example.com/10.png"]


@pytest.mark.asyncio
async def test_list_products_unwraps_sync_variant_info_response():
    """GET /sync/variant/{id} returns result.sync_variant, not a flat variant."""
    addon = PrintfulAddon()
    addon._client = AsyncMock()
    addon._client.list_sync_products.return_value = {
        "result": [{"id": 378560852, "name": "Amaryllis", "variants": 1, "synced": 1}],
        "paging": {"total": 1},
    }
    addon._client.get_sync_product.return_value = {
        "result": {
            "sync_variants": [{"id": 4752058849, "synced": True, "retail_price": "24.50"}],
        }
    }
    addon._client.get_sync_variant.return_value = {
        "result": {
            "sync_variant": {
                "id": 4752058849,
                "name": "Amaryllis / M",
                "synced": True,
                "retail_price": "24.50",
                "sku": "TEE-M",
                "files": [{"visible": True, "preview_url": "https://example.com/m.png"}],
                "product": {"name": "Bella Canvas 3001"},
            },
            "sync_product": {"id": 378560852, "name": "Amaryllis"},
        }
    }

    rows = await addon.list_products()

    assert len(rows) == 1
    assert rows[0]["id"] == "4752058849"
    assert rows[0]["thumbnail_url"] == "https://example.com/m.png"
    assert rows[0]["description"] == "Bella Canvas 3001"
