# Printful (`printful`)

Print-on-demand supplier for custom apparel and accessories.

## Overview

| | |
|---|---|
| Addon ID | `printful` |
| Category | supplier |
| Version | 1.0.0 |
| Category guide | [../README.md](../README.md) |
| Fulfillment key | `printful` |

Multiple suppliers can be enabled at the same time. Fulfillment runs when an order becomes **paid**.

## Enable and configure

1. Install this package under `app/addons/suppliers/printful/`
2. Open **Admin → Suppliers → Printful** at `/admin/suppliers/printful`
3. Enter API credentials and enable the addon

## Configuration schema

| Field | Type | Description |
|-------|------|-------------|
| `api_key` | secret | Printful API key |
| `is_active` | bool | Whether the addon is active |
| `auto_confirm` | bool | Auto-confirm orders after creation |

## Routes

### Public API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/suppliers/printful/products` | List catalog products |

GET `/api/v1/suppliers/printful/products/{product_id}` — single product detail.

### Admin

| Method | Path | Description |
|--------|------|-------------|
| GET | `/admin/suppliers/printful` | Config form |
| POST | `/admin/suppliers/printful/save` | Save config |
| POST | `/admin/suppliers/printful/sync` | Trigger catalog sync |

## Core integration

- **Variant supplier fields:** paid-order fulfillment reads Printful IDs from each **ProductVariant** row
- **Fulfillment:** calls Printful order API; optional auto-confirm after create
- **Grouping:** line items grouped by fulfillment key `printful`

## Variant supplier fields

| Field | Description |
|-------|-------------|
| `supplier_addon_id` | `printful` |
| `supplier_product_id` | Printful sync **product** id (parent design) |
| `supplier_variant_id` | Printful sync **variant** id (sellable SKU) |

Catalog sync populates these automatically. For manual assignment, set them on the variant in **Admin → Products**.

## Catalog sync

Supported. Admin sync at `/admin/suppliers/printful` or `POST /api/v1/admin/suppliers/printful/sync`.

**Import model:** one Oshkelosh **Product** per Printful sync product; one **ProductVariant** per sync variant.

| Key | Format |
|-----|--------|
| Product parent key | `printful:product:{sync_product_id}` → `products.supplier_external_product_key` |
| Variant dedup key | `printful:variant:{sync_variant_id}` → `product_variants.supplier_external_key` |

**How sync works:**

1. `GET /sync/products` — list sync products in your store
2. `GET /sync/products/{id}` — load full `sync_variants` (including `files`) for every product
3. `GET /sync/variant/{id}` — fetch per-variant metadata; `files` from step 2 are merged so `type: preview` mockups are not dropped

On first import, up to **two** images are downloaded per variant when available: the preview mockup (`files` entry with `type: preview`, preferring `preview_url`) first, then the catalog product image (`product.image`). Mockup files from product detail are preserved when the per-variant response omits them. Preview mockups are imported even when Printful marks them `visible: false`. If neither is present, the sync product list `thumbnail_url` is used as a last resort.

**Variant picker attributes:** Storefront pickers use only Printful `size` → **Size** and `color` → **Color**. The sync variant `name` field becomes the variant **title**, not a second picker. Printful’s `options` array (custom print options) is **not** imported as purchasable axes.

**Slugs and SEO:** Catalog sync stores Printful `type_name` as `products.options["Product type"]` (same value used for category assignment). On first import, the product slug and default `meta_title` include that type when present — e.g. design `Amaryllis Solandraeflora` on thin canvas → slug `amaryllis-solandraeflora-canvas-in-thin` instead of a numeric `-2` suffix when another listing shares the design name.

**After upgrading:** re-run catalog sync so existing products drop stale `Option` attributes from earlier imports.

**Prerequisites:**

- Products must exist in your Printful **sync catalog** (Manual/API store).
- Unsynced variants are skipped; an empty sync list imports nothing.

## Provider setup

- Obtain API key from Printful Dashboard → Stores → API.

## Package layout

```
printful/
├── README.md
├── addon.py
├── catalog.py
├── client.py
├── routes.py
└── templates/
```

## See also

- [Supplier addon development](../README.md)
- [Oshkelosh addon guide](../../README.md)
