"""Unit tests for Printful API client helpers."""

from unittest.mock import AsyncMock, patch

import pytest

from app.addons.suppliers.printful.client import (
    PrintfulClient,
    build_order_items,
    map_recipient,
    pick_shipping_rate_cents,
)


def test_printful_map_recipient():
    recipient = map_recipient(
        {
            "first_name": "Jane",
            "last_name": "Doe",
            "line1": "1 Main",
            "city": "Portland",
            "state": "OR",
            "zip": "97201",
            "country": "US",
            "email": "jane@example.com",
        }
    )
    assert recipient["name"] == "Jane Doe"
    assert recipient["address1"] == "1 Main"
    assert recipient["state_code"] == "OR"
    assert recipient["country_code"] == "US"

    items = build_order_items([{"supplier_product_id": "4752058849", "quantity": 2}])
    assert items == [{"sync_variant_id": 4752058849, "quantity": 2}]


def test_map_recipient_uses_full_name_and_normalizes_country():
    recipient = map_recipient(
        {
            "full_name": "Sam Shopper",
            "line1": "9 Oak Rd",
            "city": "Austin",
            "state": "TX",
            "postal_code": "78701",
            "country": "United States",
        }
    )
    assert recipient["name"] == "Sam Shopper"
    assert recipient["country_code"] == "US"
    assert recipient["zip"] == "78701"


def test_pick_shipping_rate_prefers_standard():
    rates = [
        {"id": "EXPRESS", "name": "Express", "rate": "25.00"},
        {"id": "STANDARD", "name": "Flat Rate", "rate": "13.60"},
    ]
    assert pick_shipping_rate_cents(rates) == 1360


def test_pick_shipping_rate_cheapest_when_no_standard():
    rates = [
        {"id": "EXPRESS", "name": "Express", "rate": "25.00"},
        {"id": "ECONOMY", "name": "Economy", "rate": "9.50"},
    ]
    assert pick_shipping_rate_cents(rates) == 950


@pytest.mark.asyncio
async def test_get_shipping_rates_posts_to_printful():
    client = PrintfulClient("test-token")
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json = lambda: {
        "code": 200,
        "result": [{"id": "STANDARD", "rate": "5.00"}],
    }
    mock_response.text = ""

    mock_http = AsyncMock()
    mock_http.request = AsyncMock(return_value=mock_response)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)

    with patch("app.addons.suppliers.printful.client.httpx.AsyncClient", return_value=mock_http):
        data = await client.get_shipping_rates(
            {"country_code": "US", "zip": "97201"},
            [{"sync_variant_id": 123, "quantity": 1}],
        )

    assert data["result"][0]["rate"] == "5.00"
    call_args = mock_http.request.await_args
    assert call_args.args[0] == "POST"
    assert call_args.args[1] == "https://api.printful.com/shipping/rates"


@pytest.mark.asyncio
async def test_get_sync_variant_requests_correct_path():
    client = PrintfulClient("test-token")
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json = lambda: {"code": 200, "result": {"id": 1781126748}}
    mock_response.text = ""

    mock_http = AsyncMock()
    mock_http.request = AsyncMock(return_value=mock_response)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)

    with patch("app.addons.suppliers.printful.client.httpx.AsyncClient", return_value=mock_http):
        data = await client.get_sync_variant("1781126748")

    assert data["result"]["id"] == 1781126748
    call_args = mock_http.request.await_args
    assert call_args.args[1] == "https://api.printful.com/sync/variant/1781126748"
