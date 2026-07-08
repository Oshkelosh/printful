"""Unit tests for Printful catalog normalization."""

from app.addons.suppliers.printful.catalog import (
    PrintfulNormalizeStats,
    build_printful_catalog_row,
    normalize_printful_catalog,
    printful_price_to_cents,
    printful_variant_description,
    printful_variant_display_name,
    printful_variant_image_url,
    printful_variant_is_ignored,
    printful_variant_is_synced,
    sync_variants_from_list_stub,
    sync_variants_from_product_detail,
    unwrap_printful_sync_variant_payload,
)


def test_printful_price_string_to_cents():
    assert printful_price_to_cents("19.99") == 1999
    assert printful_price_to_cents("0") == 0
    assert printful_price_to_cents(None) == 0


def test_printful_skips_unsynced_variant():
    items = normalize_printful_catalog(
        [
            {
                "id": "123",
                "name": "Unsynced",
                "synced": False,
            }
        ]
    )
    assert len(items) == 1
    assert items[0].skip_reason == "Printful variant is not synced"


def test_printful_variant_image_url_prefers_preview_url():
    variant = {
        "files": [
            {
                "visible": True,
                "preview_url": "https://example.com/mockup.png",
                "thumbnail_url": "https://example.com/thumb.png",
            }
        ],
        "product": {"image": "https://example.com/blank.png"},
    }
    assert (
        printful_variant_image_url(variant, fallback="https://example.com/fallback.png")
        == "https://example.com/mockup.png"
    )


def test_printful_variant_display_name_appends_size_color():
    name = printful_variant_display_name(
        {"name": "Cool Tee", "size": "M", "color": "Black"},
        product_name="Parent",
    )
    assert name == "Cool Tee / M / Black"


def test_printful_variant_description_uses_catalog_product_name():
    assert printful_variant_description(
        {"product": {"name": "Bella Canvas 3001 (White / M)"}}
    ) == "Bella Canvas 3001 (White / M)"


def test_sync_variants_from_product_detail():
    detail = {
        "sync_product": {"id": 1, "name": "Tee"},
        "sync_variants": [{"id": 10}, {"id": 11}],
    }
    assert len(sync_variants_from_product_detail(detail)) == 2


def test_normalize_printful_catalog_passes_description():
    items = normalize_printful_catalog(
        [
            {
                "id": "4752058849",
                "name": "Cool Tee / M",
                "description": "Bella Canvas 3001",
                "retail_price": "24.50",
                "sku": "TEE-M",
                "synced": True,
                "thumbnail_url": "https://example.com/mockup.jpg",
            }
        ]
    )
    assert len(items) == 1
    assert items[0].description == "Bella Canvas 3001"
    assert items[0].image_url == "https://example.com/mockup.jpg"


def test_build_printful_catalog_row_merges_detail_fields():
    row = build_printful_catalog_row(
        {
            "id": 99,
            "name": "Tee",
            "size": "L",
            "synced": True,
            "retail_price": "19.00",
            "sku": "TEE-L",
            "files": [{"visible": True, "preview_url": "https://example.com/p.png"}],
            "product": {"name": "Catalog name"},
        },
        product_id=378560852,
        product_name="Amaryllis",
        product_thumbnail="https://example.com/store.png",
    )
    assert row["id"] == "99"
    assert row["sync_product_name"] == "Amaryllis"
    assert row["thumbnail_url"] == "https://example.com/p.png"
    assert row["description"] == "Catalog name"


def test_printful_variant_is_synced_accepts_int_and_string():
    assert printful_variant_is_synced(1) is True
    assert printful_variant_is_synced(True) is True
    assert printful_variant_is_synced("true") is True
    assert printful_variant_is_synced(0) is False
    assert printful_variant_is_synced(False) is False
    assert printful_variant_is_synced("false") is False
    assert printful_variant_is_synced(None) is False


def test_printful_variant_is_ignored_accepts_int_and_string():
    assert printful_variant_is_ignored(1) is True
    assert printful_variant_is_ignored("true") is True
    assert printful_variant_is_ignored(0) is False
    assert printful_variant_is_ignored(None) is False


def test_printful_synced_int_imports():
    items = normalize_printful_catalog(
        [{"id": "1", "name": "Synced", "synced": 1, "retail_price": "10.00"}]
    )
    assert len(items) == 1
    assert items[0].skip_reason is None
    assert items[0].price_cents == 1000


def test_printful_synced_zero_and_false_skip():
    for synced in (0, False, "false"):
        items = normalize_printful_catalog([{"id": "2", "name": "X", "synced": synced}])
        assert len(items) == 1
        assert items[0].skip_reason == "Printful variant is not synced"


def test_printful_is_ignored_int_emits_skip_reason():
    stats = PrintfulNormalizeStats()
    items = normalize_printful_catalog(
        [{"id": "3", "name": "Ignored", "synced": 1, "is_ignored": 1}],
        stats=stats,
    )
    assert len(items) == 1
    assert items[0].skip_reason == "Printful variant is ignored"
    assert stats.skipped == 1
    assert stats.importable == 0


def test_printful_is_ignored_true_emits_skip_reason():
    items = normalize_printful_catalog(
        [{"id": "4", "name": "Ignored", "synced": True, "is_ignored": True}]
    )
    assert len(items) == 1
    assert items[0].skip_reason == "Printful variant is ignored"


def test_printful_empty_id_not_imported():
    stats = PrintfulNormalizeStats()
    items = normalize_printful_catalog(
        [{"id": "", "name": "No id", "synced": True}],
        stats=stats,
    )
    assert items == []
    assert stats.dropped_empty_id == 1


def test_unwrap_printful_sync_variant_payload():
    wrapped = {
        "sync_variant": {"id": 10, "name": "Tee", "synced": True},
        "sync_product": {"id": 1, "name": "Parent"},
    }
    assert unwrap_printful_sync_variant_payload(wrapped)["id"] == 10
    flat = {"id": 11, "name": "Hat", "synced": True}
    assert unwrap_printful_sync_variant_payload(flat)["id"] == 11


def test_sync_variants_from_list_stub_ignores_numeric_variant_count():
    stubs = sync_variants_from_list_stub({"id": 1, "name": "Tee", "variants": 4})
    assert stubs == []


def test_sync_variants_from_list_stub_unwraps_nested_sync_variant():
    stubs = sync_variants_from_list_stub(
        {
            "sync_variants": [
                {"sync_variant": {"id": 99, "synced": True}},
                {"id": 100, "synced": True},
            ]
        }
    )
    assert len(stubs) == 2
    assert stubs[0]["id"] == 99
    assert stubs[1]["id"] == 100
