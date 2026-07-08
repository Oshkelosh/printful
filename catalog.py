"""Printful catalog normalization for local product import."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from app.addons.log import info, warning
from app.addons.suppliers.catalog_utils import variant_title_from_attributes
from schemas.supplier import (
    POD_INVENTORY_PLACEHOLDER,
    SupplierCatalogItem,
    SupplierCatalogProduct,
    SupplierCatalogVariant,
)


@dataclass
class PrintfulNormalizeStats:
    input_rows: int = 0
    importable: int = 0
    skipped: int = 0
    dropped_empty_id: int = 0


def printful_price_to_cents(retail_price: Any) -> int:
    """Convert Printful retail_price (decimal string) to cents."""
    if retail_price is None or retail_price == "":
        return 0
    try:
        return int(Decimal(str(retail_price)) * 100)
    except (InvalidOperation, ValueError):
        return 0


def printful_variant_is_synced(value: Any) -> bool:
    """Interpret Printful synced flag (bool, int, or string)."""
    if value is True or value == 1:
        return True
    if value is False or value == 0 or value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def printful_variant_is_ignored(value: Any) -> bool:
    """Interpret Printful is_ignored flag (bool, int, or string)."""
    if value is True or value == 1:
        return True
    if value is False or value == 0 or value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def _file_url(file_entry: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = file_entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _printful_preview_file_url(variant: dict[str, Any]) -> str | None:
    """Return image URL from the first preview-type file entry.

    Printful often sets ``visible: false`` on preview mockups while still
    providing a usable ``preview_url``; library visibility must not block import.
    Prefer ``type: preview`` entries, but accept any file with ``preview_url``
    when Printful omits the type field on sync variant detail payloads.
    """
    files = variant.get("files")
    if not isinstance(files, list):
        return None
    untyped_preview: str | None = None
    for file_entry in files:
        if not isinstance(file_entry, dict):
            continue
        url = _file_url(file_entry, "preview_url", "url", "thumbnail_url")
        if not url:
            continue
        file_type = str(file_entry.get("type") or "").lower()
        if file_type == "preview":
            return url
        if not file_type and untyped_preview is None:
            untyped_preview = url
    return untyped_preview


def _printful_product_image_url(variant: dict[str, Any]) -> str | None:
    """Return catalog product image URL from a sync variant payload."""
    product = variant.get("product")
    if isinstance(product, dict):
        image = product.get("image")
        if isinstance(image, str) and image.strip():
            return image.strip()
    return None


def _printful_product_image_alt_text(variant: dict[str, Any], *, product_name: str = "") -> str:
    """Return alt text for variant.product.image from sync variant.product.name."""
    product = variant.get("product")
    if isinstance(product, dict):
        name = product.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return printful_variant_display_name(variant, product_name=product_name)


def printful_variant_image_urls(variant: dict[str, Any], *, fallback: str | None = None) -> list[str]:
    """Collect up to two image URLs: preview mockup, then catalog product image."""
    return [url for url, _alt in printful_variant_image_entries(variant, fallback=fallback)]


def printful_variant_image_alt_texts(
    variant: dict[str, Any],
    *,
    product_name: str,
    fallback: str | None = None,
) -> list[str]:
    """Alt text aligned with :func:`printful_variant_image_urls`.

    Preview mockups use the sync variant name; catalog product images use
    ``sync_variants[].product.name`` from GET /sync/products/{id}.
    """
    return [alt for _url, alt in printful_variant_image_entries(variant, product_name=product_name, fallback=fallback)]


def printful_variant_image_entries(
    variant: dict[str, Any],
    *,
    product_name: str = "",
    fallback: str | None = None,
) -> list[tuple[str, str]]:
    """Collect image URL and alt-text pairs: preview mockup, then catalog product image."""
    variant_name = printful_variant_display_name(variant, product_name=product_name)
    catalog_product_name = _printful_product_image_alt_text(variant, product_name=product_name)
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()

    def _add(url: str | None, alt: str) -> None:
        if not url or url in seen:
            return
        seen.add(url)
        entries.append((url, alt))

    _add(_printful_preview_file_url(variant), variant_name)
    _add(_printful_product_image_url(variant), catalog_product_name)
    if not entries and isinstance(fallback, str) and fallback.strip():
        _add(fallback.strip(), variant_name)
    return entries


def printful_variant_image_url(variant: dict[str, Any], *, fallback: str | None = None) -> str | None:
    """Pick the primary storefront image URL from a sync variant detail payload."""
    preview = _printful_preview_file_url(variant)
    if preview:
        return preview
    product_image = _printful_product_image_url(variant)
    if product_image:
        return product_image
    if isinstance(fallback, str) and fallback.strip():
        return fallback.strip()
    return None


def printful_variant_display_name(variant: dict[str, Any], *, product_name: str) -> str:
    """Build a display name from sync variant fields."""
    base = str(variant.get("name") or product_name or "Printful product").strip()
    parts: list[str] = []
    for key in ("size", "color"):
        value = variant.get(key)
        if isinstance(value, str) and value.strip():
            part = value.strip()
            if part.lower() not in base.lower():
                parts.append(part)
    if parts:
        return f"{base} / {' / '.join(parts)}"
    return base


def printful_variant_description(variant: dict[str, Any]) -> str | None:
    """Return catalog garment description from variant detail when available."""
    product = variant.get("product")
    if isinstance(product, dict):
        name = product.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def humanize_printful_type(value: str) -> str:
    """Turn Printful catalog type codes like T-SHIRT into readable labels."""
    cleaned = value.strip()
    if not cleaned:
        return cleaned
    if " " in cleaned or cleaned != cleaned.upper():
        return cleaned
    return cleaned.replace("-", " ").replace("_", " ").title()


async def load_printful_category_titles(client: Any) -> dict[int, str]:
    """Load Printful catalog category id -> title mapping."""
    titles: dict[int, str] = {}
    try:
        data = await client.list_categories()
    except Exception:
        return titles
    result = data.get("result", [])
    if not isinstance(result, list):
        return titles
    for entry in result:
        if not isinstance(entry, dict):
            continue
        category_id = entry.get("id")
        title = entry.get("title")
        if category_id is None or not isinstance(title, str) or not title.strip():
            continue
        try:
            titles[int(category_id)] = title.strip()
        except (TypeError, ValueError):
            continue
    return titles


async def resolve_printful_catalog_product_type(
    client: Any,
    variant: dict[str, Any],
    *,
    catalog_cache: dict[int, str],
) -> str | None:
    """Fetch catalog product type_name when sync variant payload lacks it."""
    product = variant.get("product")
    if not isinstance(product, dict):
        return None
    catalog_product_id = product.get("product_id")
    if catalog_product_id is None:
        return None
    try:
        catalog_id = int(catalog_product_id)
    except (TypeError, ValueError):
        return None
    if catalog_id in catalog_cache:
        return catalog_cache[catalog_id]
    try:
        data = await client.get_catalog_product(str(catalog_id))
    except Exception:
        catalog_cache[catalog_id] = ""
        return None
    result = data.get("result", data)
    catalog_product = result.get("product", result) if isinstance(result, dict) else {}
    if not isinstance(catalog_product, dict):
        catalog_cache[catalog_id] = ""
        return None
    for key in ("type_name", "type"):
        value = catalog_product.get(key)
        if isinstance(value, str) and value.strip():
            resolved = humanize_printful_type(value) if key == "type" else value.strip()
            catalog_cache[catalog_id] = resolved
            return resolved
    catalog_cache[catalog_id] = ""
    return None


def printful_variant_product_type(
    variant: dict[str, Any],
    *,
    category_titles: dict[int, str] | None = None,
) -> str | None:
    """Return catalog product type from variant detail when available."""
    product = variant.get("product")
    if isinstance(product, dict):
        type_name = product.get("type_name")
        if isinstance(type_name, str) and type_name.strip():
            return type_name.strip()
        type_code = product.get("type")
        if isinstance(type_code, str) and type_code.strip():
            return humanize_printful_type(type_code)

    main_category_id = variant.get("main_category_id")
    if main_category_id is not None and category_titles:
        try:
            title = category_titles.get(int(main_category_id))
        except (TypeError, ValueError):
            title = None
        if title:
            return title

    for key in ("type_name", "type"):
        value = variant.get(key)
        if isinstance(value, str) and value.strip():
            return humanize_printful_type(value) if key == "type" else value.strip()
    return None


def unwrap_printful_sync_variant_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Flatten GET /sync/variant/{id} SyncVariantInfo to a sync variant dict."""
    nested = payload.get("sync_variant")
    if isinstance(nested, dict):
        return nested
    return payload


def merge_printful_variant_files(
    stub_files: list[Any] | None,
    detail_files: list[Any] | None,
) -> list[dict[str, Any]]:
    """Union file entries by id; detail wins on conflict; keep stub-only preview mockups."""
    stub_list = [entry for entry in (stub_files or []) if isinstance(entry, dict)]
    detail_list = [entry for entry in (detail_files or []) if isinstance(entry, dict)]

    by_id: dict[Any, dict[str, Any]] = {}
    for entry in stub_list:
        file_id = entry.get("id")
        if file_id is not None:
            by_id[file_id] = entry
    for entry in detail_list:
        file_id = entry.get("id")
        if file_id is not None:
            by_id[file_id] = entry

    result: list[dict[str, Any]] = []
    seen_ids: set[Any] = set()
    for entry in detail_list:
        file_id = entry.get("id")
        if file_id is not None:
            if file_id in seen_ids:
                continue
            result.append(by_id[file_id])
            seen_ids.add(file_id)
        else:
            result.append(entry)

    for entry in stub_list:
        if str(entry.get("type") or "").lower() != "preview":
            continue
        file_id = entry.get("id")
        if file_id is not None and file_id in seen_ids:
            merged = by_id[file_id]
            if str(merged.get("type") or "").lower() == "preview":
                continue
            result.append(entry)
            seen_ids.add(file_id)
        elif file_id is not None and file_id not in seen_ids:
            result.append(entry)
            seen_ids.add(file_id)
        elif file_id is None:
            result.append(entry)

    return result


def merge_printful_variant_payload(
    stub: dict[str, Any],
    detail: dict[str, Any],
) -> dict[str, Any]:
    """Merge product-detail/list stub with GET /sync/variant detail."""
    stub_flat = unwrap_printful_sync_variant_payload(stub) if stub else {}
    detail_flat = unwrap_printful_sync_variant_payload(detail) if detail else {}
    if not stub_flat:
        return dict(detail_flat)
    if not detail_flat:
        return dict(stub_flat)

    merged = {**stub_flat, **detail_flat}
    stub_product = stub_flat.get("product")
    detail_product = detail_flat.get("product")
    if isinstance(stub_product, dict) or isinstance(detail_product, dict):
        merged["product"] = {
            **(stub_product if isinstance(stub_product, dict) else {}),
            **(detail_product if isinstance(detail_product, dict) else {}),
        }
    merged["files"] = merge_printful_variant_files(
        stub_flat.get("files") if isinstance(stub_flat.get("files"), list) else None,
        detail_flat.get("files") if isinstance(detail_flat.get("files"), list) else None,
    )
    return merged


def printful_variant_stub_id(stub: dict[str, Any]) -> Any:
    """Read variant id from a flat or nested sync variant stub."""
    flat = unwrap_printful_sync_variant_payload(stub)
    return flat.get("id")


def sync_variants_from_list_stub(sync_product: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract sync variant stubs from a list-sync-products row (lists only)."""
    if not isinstance(sync_product, dict):
        return []

    def _normalize_stubs(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        stubs: list[dict[str, Any]] = []
        for entry in value:
            if isinstance(entry, dict):
                stubs.append(unwrap_printful_sync_variant_payload(entry))
        return stubs

    for key in ("sync_variants", "variants"):
        stubs = _normalize_stubs(sync_product.get(key))
        if stubs:
            return stubs
    nested = sync_product.get("sync_product")
    if isinstance(nested, dict):
        for key in ("sync_variants", "variants"):
            stubs = _normalize_stubs(nested.get(key))
            if stubs:
                return stubs
    return []


def sync_variants_from_product_detail(detail: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract sync_variants list from GET /sync/products/{id} response."""
    if not isinstance(detail, dict):
        return []
    return sync_variants_from_list_stub(detail)


def build_printful_catalog_row(
    variant: dict[str, Any],
    *,
    product_id: Any,
    product_name: str,
    product_thumbnail: str | None,
    fallback_variant_id: Any = None,
    category_titles: dict[int, str] | None = None,
) -> dict[str, Any]:
    """Map a sync variant (stub or detail) to a flat row for normalize_printful_catalog."""
    variant_id = variant.get("id")
    if variant_id is None:
        variant_id = fallback_variant_id
    image_urls = printful_variant_image_urls(variant, fallback=product_thumbnail)
    image_alt_texts = printful_variant_image_alt_texts(
        variant,
        product_name=product_name,
        fallback=product_thumbnail,
    )
    return {
        "id": str(variant_id) if variant_id is not None else "",
        "sync_product_id": str(product_id) if product_id is not None else "",
        "sync_product_name": product_name,
        "size": variant.get("size"),
        "color": variant.get("color"),
        "name": printful_variant_display_name(variant, product_name=product_name),
        "description": printful_variant_description(variant),
        "sku": variant.get("sku"),
        "retail_price": variant.get("retail_price"),
        "currency": variant.get("currency"),
        "synced": variant.get("synced"),
        "is_ignored": variant.get("is_ignored"),
        "thumbnail_url": image_urls[0] if image_urls else None,
        "image_urls": image_urls,
        "image_alt_texts": image_alt_texts,
        "product_type": printful_variant_product_type(variant, category_titles=category_titles),
    }


def normalize_printful_catalog(
    raw_items: list[dict[str, Any]],
    *,
    stats: PrintfulNormalizeStats | None = None,
) -> list[SupplierCatalogItem]:
    """Map Printful list_products() rows to catalog import items."""
    normalize_stats = stats or PrintfulNormalizeStats()
    normalize_stats.input_rows = len(raw_items)
    items: list[SupplierCatalogItem] = []
    for row in raw_items:
        variant_id = str(row.get("id") or "").strip()
        if not variant_id:
            normalize_stats.dropped_empty_id += 1
            warning(
                "Printful",
                "catalog sync: dropping row with empty variant id keys={}",
                sorted(row.keys()),
            )
            continue
        external_key = f"printful:variant:{variant_id}"
        if printful_variant_is_ignored(row.get("is_ignored")):
            normalize_stats.skipped += 1
            warning("Printful", "catalog sync: normalize skipped variant {} (ignored)", variant_id)
            items.append(
                SupplierCatalogItem(
                    external_key=external_key,
                    name=row.get("name") or "Printful product",
                    description=row.get("description"),
                    price_cents=0,
                    sku=None,
                    image_url=None,
                    supplier_value="printful",
                    supplier_product_id=variant_id,
                    supplier_variant_id="",
                    inventory_quantity=0,
                    skip_reason="Printful variant is ignored",
                )
            )
            continue
        if not printful_variant_is_synced(row.get("synced")):
            normalize_stats.skipped += 1
            warning("Printful", "catalog sync: normalize skipped variant {} (not synced)", variant_id)
            items.append(
                SupplierCatalogItem(
                    external_key=external_key,
                    name=row.get("name") or "Printful product",
                    description=row.get("description"),
                    price_cents=0,
                    sku=None,
                    image_url=None,
                    supplier_value="printful",
                    supplier_product_id=variant_id,
                    supplier_variant_id="",
                    inventory_quantity=0,
                    skip_reason="Printful variant is not synced",
                )
            )
            continue
        name = str(row.get("name") or "Printful product")
        sku = row.get("sku")
        sku = str(sku).strip() if sku else f"printful-{variant_id}"
        description = row.get("description")
        description = str(description).strip() if description else None
        product_type = row.get("product_type")
        product_type = str(product_type).strip() if product_type else None
        raw_urls = row.get("image_urls")
        image_urls = [str(u).strip() for u in raw_urls if u] if isinstance(raw_urls, list) else []
        if not image_urls and row.get("thumbnail_url"):
            image_urls = [str(row.get("thumbnail_url")).strip()]
        raw_alts = row.get("image_alt_texts")
        image_alt_texts = (
            [str(a).strip() for a in raw_alts if a] if isinstance(raw_alts, list) else []
        )
        if not image_alt_texts and image_urls:
            image_alt_texts = [name] * len(image_urls)
        primary_image = image_urls[0] if image_urls else None
        items.append(
            SupplierCatalogItem(
                external_key=external_key,
                name=name,
                description=description,
                price_cents=printful_price_to_cents(row.get("retail_price")),
                sku=sku,
                image_url=primary_image,
                image_urls=image_urls,
                image_alt_texts=image_alt_texts,
                supplier_value="printful",
                supplier_product_id=variant_id,
                supplier_variant_id="",
                inventory_quantity=POD_INVENTORY_PLACEHOLDER,
                product_type=product_type,
            )
        )
        normalize_stats.importable += 1

    info(
        "Printful",
        "catalog sync: normalize {} rows -> {} importable, {} skipped, {} dropped",
        normalize_stats.input_rows,
        normalize_stats.importable,
        normalize_stats.skipped,
        normalize_stats.dropped_empty_id,
    )
    return items


def printful_variant_attributes_from_row(row: dict[str, Any]) -> dict[str, str]:
    """Picker attributes from Printful size/color only — not display name or options."""
    attrs: dict[str, str] = {}
    for key, label in (("size", "Size"), ("color", "Color")):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            attrs[label] = value.strip()
    return attrs


def _printful_variant_title(row: dict[str, Any], *, product_name: str) -> str:
    """Use Printful sync variant display name; fall back to attribute join when missing."""
    display_name = row.get("name")
    if isinstance(display_name, str) and display_name.strip():
        return display_name.strip()
    attributes = printful_variant_attributes_from_row(row)
    return variant_title_from_attributes(product_name, attributes, fallback=product_name)


def _printful_row_to_variant(
    row: dict[str, Any],
    *,
    variant_id: str,
    product_name: str,
) -> SupplierCatalogVariant:
    """Build a catalog variant from a normalized Printful row."""
    attributes = printful_variant_attributes_from_row(row)
    raw_urls = row.get("image_urls")
    image_urls = [str(u).strip() for u in raw_urls if u] if isinstance(raw_urls, list) else []
    if not image_urls and row.get("thumbnail_url"):
        image_urls = [str(row.get("thumbnail_url")).strip()]
    raw_alts = row.get("image_alt_texts")
    image_alt_texts = (
        [str(a).strip() for a in raw_alts if a] if isinstance(raw_alts, list) else []
    )
    variant_title = _printful_variant_title(row, product_name=product_name)
    if not image_alt_texts and image_urls:
        image_alt_texts = [variant_title] * len(image_urls)

    if printful_variant_is_ignored(row.get("is_ignored")):
        return SupplierCatalogVariant(
            external_key=f"printful:variant:{variant_id}",
            title=variant_title,
            attributes=attributes,
            price_cents=0,
            sku=None,
            inventory_quantity=0,
            supplier_product_id=variant_id,
            supplier_variant_id="",
            image_urls=image_urls,
            image_alt_texts=image_alt_texts,
            skip_reason="Printful variant is ignored",
        )
    if not printful_variant_is_synced(row.get("synced")):
        return SupplierCatalogVariant(
            external_key=f"printful:variant:{variant_id}",
            title=variant_title,
            attributes=attributes,
            price_cents=0,
            sku=None,
            inventory_quantity=0,
            supplier_product_id=variant_id,
            supplier_variant_id="",
            image_urls=image_urls,
            image_alt_texts=image_alt_texts,
            skip_reason="Printful variant is not synced",
        )

    sku = row.get("sku")
    sku = str(sku).strip() if sku else f"printful-{variant_id}"
    return SupplierCatalogVariant(
        external_key=f"printful:variant:{variant_id}",
        title=variant_title,
        attributes=attributes,
        price_cents=printful_price_to_cents(row.get("retail_price")),
        sku=sku,
        inventory_quantity=POD_INVENTORY_PLACEHOLDER,
        supplier_product_id=variant_id,
        supplier_variant_id="",
        image_urls=image_urls,
        image_alt_texts=image_alt_texts,
    )


def normalize_printful_catalog_products(
    raw_items: list[dict[str, Any]],
    *,
    stats: PrintfulNormalizeStats | None = None,
) -> list[SupplierCatalogProduct]:
    """Map Printful list_products() rows to grouped catalog products."""
    normalize_stats = stats or PrintfulNormalizeStats()
    normalize_stats.input_rows = len(raw_items)

    groups: dict[str, dict[str, Any]] = {}
    for row in raw_items:
        variant_id = str(row.get("id") or "").strip()
        if not variant_id:
            normalize_stats.dropped_empty_id += 1
            warning(
                "Printful",
                "catalog sync: dropping row with empty variant id keys={}",
                sorted(row.keys()),
            )
            continue

        sync_product_id = str(row.get("sync_product_id") or variant_id).strip()
        product_name = str(
            row.get("sync_product_name") or row.get("name") or "Printful product"
        )
        variant = _printful_row_to_variant(row, variant_id=variant_id, product_name=product_name)

        if variant.skip_reason:
            normalize_stats.skipped += 1
            warning(
                "Printful",
                "catalog sync: normalize skipped variant {} ({})",
                variant_id,
                variant.skip_reason,
            )
        else:
            normalize_stats.importable += 1

        if sync_product_id not in groups:
            description = row.get("description")
            description = str(description).strip() if description else None
            product_type = row.get("product_type")
            product_type = str(product_type).strip() if product_type else None
            groups[sync_product_id] = {
                "name": product_name,
                "description": description,
                "product_type": product_type,
                "variants": [],
            }
        groups[sync_product_id]["variants"].append(variant)

    products: list[SupplierCatalogProduct] = []
    for sync_product_id, group in groups.items():
        product_type = group.get("product_type")
        options: dict[str, str] = {}
        if product_type:
            options["Product type"] = product_type
        products.append(
            SupplierCatalogProduct(
                external_product_key=f"printful:product:{sync_product_id}",
                name=group["name"],
                description=group.get("description"),
                product_type=product_type,
                image_urls=[],
                image_alt_texts=[],
                variants=group["variants"],
                supplier_value="printful",
                options=options,
            )
        )

    info(
        "Printful",
        "catalog sync: normalize {} rows -> {} products, {} importable variants, {} skipped, {} dropped",
        normalize_stats.input_rows,
        len(products),
        normalize_stats.importable,
        normalize_stats.skipped,
        normalize_stats.dropped_empty_id,
    )
    return products
