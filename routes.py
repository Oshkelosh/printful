"""
Printful addon routes.

API Router (mounted at /api/v1/suppliers/printful/*):
    GET  /api/v1/suppliers/printful/products            - List Printful sync variants
    GET  /api/v1/suppliers/printful/products/{id}     - Single variant detail

Admin Router (mounted at /admin/suppliers/printful/*):
    GET  /admin/suppliers/printful              - Config/status page
    POST /admin/suppliers/printful/save         - Save configuration
    POST /admin/suppliers/printful/sync         - Catalog sync
"""

from __future__ import annotations

from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse

from app.addons.suppliers.shared_routes import build_supplier_routers


def _parse_printful_form(form: Any) -> tuple[dict[str, Any], bool]:
    return {
        "api_key": form.get("api_key", ""),
        "is_active": form.get("is_active") == "on",
        "auto_confirm": form.get("auto_confirm") == "on",
    }, form.get("is_active") == "on"


admin_router, api_router, jinja_env = build_supplier_routers(
    "printful",
    template_name="printful_config.html",
    page_title="Printful Settings",
    parse_config_form=_parse_printful_form,
)


@api_router.get("/products/{product_id}")
async def get_printful_product(product_id: str):
    from app.addons.registry import addon_registry

    addon = addon_registry.get("printful")
    if addon is None or not addon.is_enabled:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"error": "Printful addon is not enabled"},
        )

    try:
        product = await addon.get_product(product_id)
        return JSONResponse(content={"product": product})
    except Exception as exc:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": str(exc)},
        )
