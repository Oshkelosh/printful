"""Printful API client."""

from __future__ import annotations

from typing import Any

import httpx

PRINTFUL_BASE = "https://api.printful.com"


class PrintfulAPIError(Exception):
    """Raised when the Printful API returns an error response."""

    def __init__(self, message: str, status_code: int | None = None, body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class PrintfulClient:
    """Thin async wrapper around Printful REST endpoints."""

    def __init__(self, api_key: str, *, timeout: float = 30.0):
        self._api_key = api_key
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{PRINTFUL_BASE}{path}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.request(
                method,
                url,
                headers=self._headers(),
                params=params,
                json=json,
            )
        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text}
        if resp.status_code >= 400:
            message = data.get("error", {}).get("message", resp.text) if isinstance(data, dict) else resp.text
            raise PrintfulAPIError(str(message), status_code=resp.status_code, body=data)
        if isinstance(data, dict) and data.get("code") not in (None, 200):
            err = data.get("error") or {}
            message = err.get("message", "Printful API error") if isinstance(err, dict) else str(err)
            raise PrintfulAPIError(message, status_code=resp.status_code, body=data)
        return data if isinstance(data, dict) else {"result": data}

    async def list_sync_products(self, *, offset: int = 0, limit: int = 100) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/sync/products",
            params={"offset": offset, "limit": limit},
        )

    async def get_sync_product(self, product_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/sync/products/{product_id}")

    async def get_sync_variant(self, variant_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/sync/variant/{variant_id}")

    async def list_categories(self) -> dict[str, Any]:
        return await self._request("GET", "/categories")

    async def get_catalog_product(self, product_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/products/{product_id}")

    async def create_order(self, payload: dict[str, Any], *, confirm: bool) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/orders",
            params={"confirm": "1" if confirm else "0"},
            json=payload,
        )

    async def confirm_order(self, order_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/orders/{order_id}/confirm")

    async def get_order(self, order_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/orders/{order_id}")

    async def list_sync_variants(self, *, offset: int = 0, limit: int = 100) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/sync/variant",
            params={"offset": offset, "limit": limit},
        )


def map_recipient(shipping_address: dict[str, Any]) -> dict[str, str]:
    """Map Oshkelosh shipping_address keys to Printful recipient fields."""
    first = shipping_address.get("first_name", "")
    last = shipping_address.get("last_name", "")
    name = shipping_address.get("name") or f"{first} {last}".strip() or "Customer"
    recipient: dict[str, str] = {
        "name": name,
        "address1": shipping_address.get("line1") or shipping_address.get("address1") or "",
        "city": shipping_address.get("city", ""),
        "state_code": shipping_address.get("state") or shipping_address.get("state_code") or "",
        "country_code": shipping_address.get("country") or shipping_address.get("country_code") or "US",
        "zip": shipping_address.get("zip") or shipping_address.get("postal_code") or "",
    }
    line2 = shipping_address.get("line2") or shipping_address.get("address2")
    if line2:
        recipient["address2"] = str(line2)
    email = shipping_address.get("email")
    if email:
        recipient["email"] = str(email)
    phone = shipping_address.get("phone")
    if phone:
        recipient["phone"] = str(phone)
    return recipient


def build_order_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert fulfillment items to Printful order line items."""
    order_items: list[dict[str, Any]] = []
    for item in items:
        variant_id = item.get("supplier_product_id")
        if not variant_id:
            continue
        try:
            sync_variant_id = int(variant_id)
        except (TypeError, ValueError) as exc:
            raise PrintfulAPIError(f"Invalid sync_variant_id: {variant_id}") from exc
        quantity = item.get("quantity", 1)
        try:
            qty = int(quantity)
        except (TypeError, ValueError):
            qty = 1
        order_items.append({"sync_variant_id": sync_variant_id, "quantity": max(qty, 1)})
    return order_items
