"""Printful print-on-demand supplier integration.

Provides product sync, order creation, and inventory management through
the Printful API.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from fastapi import APIRouter
from pydantic import BaseModel, Field, SecretStr

from app.addons.suppliers.base import SupplierAddon
from app.addons.suppliers.printful.catalog import (
    PrintfulNormalizeStats,
    build_printful_catalog_row,
    load_printful_category_titles,
    merge_printful_variant_payload,
    normalize_printful_catalog_products,
    printful_variant_is_ignored,
    printful_variant_stub_id,
    resolve_printful_catalog_product_type,
    sync_variants_from_list_stub,
    sync_variants_from_product_detail,
    unwrap_printful_sync_variant_payload,
)
from app.addons.suppliers.printful.client import (
    PrintfulAPIError,
    PrintfulClient,
    build_order_items,
    map_recipient,
)
from schemas.supplier import SupplierAssignment, SupplierCatalogProduct
from app.addons.log import info, warning
from app.addons.config_serialization import dump_addon_config


class PrintfulConfig(BaseModel):
    """Configuration for the Printful supplier addon."""

    api_key: SecretStr = Field(default=..., description="Printful API key")
    is_active: bool = Field(default=False, description="Whether the addon is active")
    auto_confirm: bool = Field(
        default=True,
        description="Confirm Printful orders immediately after payment",
    )

    @classmethod
    def config_model(cls):
        return cls


class PrintfulAddon(SupplierAddon):
    """Printful print-on-demand supplier."""

    addon_id: str = "printful"
    addon_name: str = "Printful"
    addon_description: str = "Print-on-demand supplier for custom apparel and accessories."
    addon_category: str = "supplier"
    version: str = "1.0.0"

    _config: Dict[str, Any] | None = None
    _client: PrintfulClient | None = None
    _catalog_category_titles: dict[int, str] | None = None
    _catalog_product_type_cache: dict[int, str] | None = None

    @classmethod
    def config_schema(cls):
        return PrintfulConfig

    async def initialize(self, config: dict) -> None:
        schema = self.config_schema()
        validated = schema(**config)
        self._config = dump_addon_config(validated)
        self._client = PrintfulClient(validated.api_key.get_secret_value())
        self.is_enabled = validated.is_active
        info("Printful", "Initialized (auto_confirm={})", validated.auto_confirm)

    async def validate_config(self, config: dict) -> None:
        from app.core.exceptions import ValidationError

        validated = self.config_schema()(**config)
        api_key = validated.api_key.get_secret_value()
        if not api_key:
            return
        client = PrintfulClient(api_key)
        try:
            await client.list_sync_products(limit=1)
        except PrintfulAPIError as exc:
            if exc.status_code == 401:
                raise ValidationError(message="Invalid API key — check your credentials") from exc
            if exc.status_code == 403:
                raise ValidationError(
                    message="API key is valid but missing required permissions: catalog:read"
                ) from exc
            raise ValidationError(message=f"Printful API error: {exc}") from exc

    async def shutdown(self) -> None:
        self._client = None
        self._config = None
        self.is_enabled = False

    def admin_form_hints(self) -> dict[str, str | bool]:
        return {
            "requires_variant_id": False,
            "product_id_help": "Required. Printful sync variant ID from your catalog.",
            "variant_id_help": "",
        }

    def external_key_from_assignment(self, assignment: SupplierAssignment) -> str | None:
        if assignment.addon_id != self.addon_id or not assignment.supplier_product_id:
            return None
        return f"printful:variant:{assignment.supplier_product_id}"

    def _require_client(self) -> PrintfulClient:
        if self._client is None:
            raise PrintfulAPIError("Printful addon is not initialized")
        return self._client

    async def _variant_detail(
        self,
        client: PrintfulClient,
        variant_stub: dict[str, Any],
        *,
        product_id: Any,
        product_name: str,
        product_thumbnail: str | None,
    ) -> dict[str, Any] | None:
        variant_id = printful_variant_stub_id(variant_stub)
        if variant_id is None:
            warning(
                "Printful",
                "catalog sync: variant stub missing id for product {}",
                product_id,
            )
            return None
        if printful_variant_is_ignored(variant_stub.get("is_ignored")):
            warning(
                "Printful",
                "catalog sync: variant {} stub marked ignored; fetching detail for normalize",
                variant_id,
            )
        try:
            data = await client.get_sync_variant(str(variant_id))
            detail = data.get("result", data)
            if isinstance(detail, dict):
                detail = unwrap_printful_sync_variant_payload(detail)
            else:
                detail = variant_stub
        except PrintfulAPIError as exc:
            warning(
                "Printful",
                "catalog sync: get_sync_variant({}) failed: {}",
                variant_id,
                exc,
            )
            detail = variant_stub
        else:
            detail = merge_printful_variant_payload(variant_stub, detail)
        row = build_printful_catalog_row(
            detail,
            product_id=product_id,
            product_name=product_name,
            product_thumbnail=product_thumbnail,
            fallback_variant_id=variant_id,
            category_titles=self._catalog_category_titles,
        )
        if not row.get("product_type") and self._catalog_product_type_cache is not None:
            row["product_type"] = await resolve_printful_catalog_product_type(
                client,
                detail,
                catalog_cache=self._catalog_product_type_cache,
            ) or None
        if not row.get("id"):
            warning(
                "Printful",
                "catalog sync: enriched row has empty variant id keys={}",
                sorted(row.keys()),
            )
            return None
        return row

    async def _expand_sync_product(
        self,
        client: PrintfulClient,
        sync_product: dict[str, Any],
    ) -> list[dict[str, Any]]:
        product_id = sync_product.get("id")
        if product_id is None:
            return []

        product_name = str(sync_product.get("name") or "Unknown")
        product_thumbnail = sync_product.get("thumbnail_url")
        if isinstance(product_thumbnail, str):
            product_thumbnail = product_thumbnail.strip() or None
        else:
            product_thumbnail = None

        variants = sync_variants_from_list_stub(sync_product)
        list_by_id: dict[Any, dict[str, Any]] = {}
        for stub in variants:
            variant_id = printful_variant_stub_id(stub)
            if variant_id is not None:
                list_by_id[variant_id] = stub

        product_detail_stubs: dict[Any, dict[str, Any]] = {}
        try:
            data = await client.get_sync_product(str(product_id))
            detail = data.get("result", data)
            for stub in sync_variants_from_product_detail(
                detail if isinstance(detail, dict) else {}
            ):
                variant_id = printful_variant_stub_id(stub)
                if variant_id is not None:
                    product_detail_stubs[variant_id] = stub
        except PrintfulAPIError as exc:
            warning(
                "Printful",
                "catalog sync: get_sync_product({}) failed: {}",
                product_id,
                exc,
            )
            if not list_by_id:
                return []

        if list_by_id:
            variant_order = [
                printful_variant_stub_id(stub)
                for stub in variants
                if printful_variant_stub_id(stub) is not None
            ]
        else:
            variant_order = list(product_detail_stubs.keys())

        variants = [
            merge_printful_variant_payload(
                product_detail_stubs.get(variant_id, {}),
                list_by_id.get(variant_id, {}),
            )
            for variant_id in variant_order
            if variant_id is not None
        ]

        stub_count = len(variants)
        info(
            "Printful",
            "catalog sync: product {} expanded to {} variant stubs",
            product_id,
            stub_count,
        )

        if not variants:
            return []

        variant_stubs = variants
        rows = await asyncio.gather(
            *[
                self._variant_detail(
                    client,
                    variant,
                    product_id=product_id,
                    product_name=product_name,
                    product_thumbnail=product_thumbnail,
                )
                for variant in variant_stubs
            ]
        )
        detail_failures = sum(1 for row in rows if row is None)
        if detail_failures:
            warning(
                "Printful",
                "catalog sync: {} variant detail fetch(es) failed or dropped for product {}",
                detail_failures,
                product_id,
            )
        enriched = [row for row in rows if row]
        empty_id_drops = 0
        kept: list[dict[str, Any]] = []
        for row in enriched:
            if not row.get("id"):
                empty_id_drops += 1
                warning(
                    "Printful",
                    "catalog sync: dropping row with empty variant id keys={}",
                    sorted(row.keys()),
                )
                continue
            kept.append(row)
        info(
            "Printful",
            "catalog sync: enriched {} variant rows ({} detail fetch failures, {} empty id drops)",
            len(kept),
            detail_failures,
            empty_id_drops,
        )
        return kept

    async def list_products(self, **kwargs: Any) -> List[Dict[str, Any]]:
        client = self._require_client()
        products: List[Dict[str, Any]] = []
        offset = 0
        limit = 100
        list_product_count = 0
        while True:
            data = await client.list_sync_products(offset=offset, limit=limit)
            result = data.get("result", [])
            if not isinstance(result, list):
                break
            list_product_count += len(result)
            for sync_product in result:
                if not isinstance(sync_product, dict):
                    continue
                products.extend(await self._expand_sync_product(client, sync_product))
            paging = data.get("paging") or {}
            total = paging.get("total", len(result))
            offset += limit
            if offset >= total or not result:
                break
        info(
            "Printful",
            "catalog sync: list returned {} products, {} variant rows total",
            list_product_count,
            len(products),
        )
        return products

    async def fetch_catalog_for_import(self, **kwargs: Any) -> List[SupplierCatalogProduct]:
        client = self._require_client()
        self._catalog_category_titles = await load_printful_category_titles(client)
        self._catalog_product_type_cache = {}
        try:
            raw = await self.list_products(**kwargs)
            stats = PrintfulNormalizeStats()
            products = normalize_printful_catalog_products(raw, stats=stats)
            importable = sum(
                1 for product in products for variant in product.variants if not variant.skip_reason
            )
            info(
                "Printful",
                "catalog sync: fetch_catalog raw={} normalized={} products importable_variants={} skipped={}",
                len(raw),
                len(products),
                importable,
                stats.skipped,
            )
            return products
        finally:
            self._catalog_category_titles = None
            self._catalog_product_type_cache = None

    async def get_product(self, product_id: str) -> Dict[str, Any]:
        client = self._require_client()
        data = await client.get_sync_product(product_id)
        return data.get("result", data)

    async def create_order(
        self,
        items: List[Dict[str, Any]],
        shipping_address: Dict[str, Any],
        *,
        external_id: str | None = None,
        supplier_ref: str | None = None,
    ) -> Dict[str, Any]:
        del supplier_ref
        client = self._require_client()
        try:
            order_items = build_order_items(items)
            if not order_items:
                return {"success": False, "error": "No valid Printful line items"}

            payload: Dict[str, Any] = {
                "recipient": map_recipient(shipping_address),
                "items": order_items,
            }
            if external_id:
                payload["external_id"] = external_id

            confirm = bool(self._config.get("auto_confirm", True)) if self._config else True
            data = await client.create_order(payload, confirm=confirm)
            result = data.get("result", {})
            order_id = result.get("id", "")
            return {
                "success": True,
                "order_id": str(order_id),
                "status": result.get("status", "created"),
                "printful_order_id": str(order_id),
            }
        except PrintfulAPIError as exc:
            warning("Printful", "create_order error: {}", exc)
            return {"success": False, "error": str(exc)}

    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        client = self._require_client()
        try:
            data = await client.get_order(order_id)
            result = data.get("result", {})
            return {
                "order_id": order_id,
                "status": result.get("status", "unknown"),
                "fulfillment_status": (result.get("fulfillment") or {}).get("status", ""),
            }
        except PrintfulAPIError as exc:
            warning("Printful", "get_order_status({}) error: {}", order_id, exc)
            return {"order_id": order_id, "status": "error", "detail": str(exc)}

    async def sync_inventory(self) -> None:
        client = self._require_client()
        offset = 0
        limit = 100
        total = 0
        while True:
            data = await client.list_sync_variants(offset=offset, limit=limit)
            result = data.get("result", [])
            if isinstance(result, list):
                total += len(result)
            paging = data.get("paging") or {}
            batch_total = paging.get("total", len(result) if isinstance(result, list) else 0)
            offset += limit
            if offset >= batch_total or not result:
                break
        info("Printful", "Synced {} sync variants", total)

    def get_routers(self) -> List[APIRouter]:
        from app.addons.suppliers.printful.routes import api_router

        return [api_router]

    def get_admin_routes(self) -> List[APIRouter]:
        from app.addons.suppliers.printful.routes import admin_router

        return [admin_router]

    def get_admin_templates(self) -> str:
        from pathlib import Path

        return str(Path(__file__).resolve().parent / "templates")

    def get_admin_static(self) -> str:
        from pathlib import Path

        return str(Path(__file__).resolve().parent / "static")
