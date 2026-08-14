"""Shared helpers for the product/trade/portfolio valuation API tests."""

from __future__ import annotations

import time


def wait_for_valuation(client, valuation_id: str, max_polls: int = 20) -> dict:
    for _ in range(max_polls):
        resp = client.get(f"/api/valuations/{valuation_id}")
        assert resp.status_code == 200
        body = resp.json()
        if body["status"] != "running":
            return body
        time.sleep(0.1)
    raise AssertionError(f"Valuation {valuation_id} did not settle within {max_polls} polls")


def create_european_product(client, strike: str = "100.0") -> str:
    payload = {
        "name": "Call",
        "description": "",
        "rows": [
            {"date_kind": "label", "label": "STRIKE", "event": strike},
            {
                "date_kind": "date",
                "date": "2023-09-15",
                "event": "call pays MAX(spot() - STRIKE, 0.0)",
            },
        ],
    }
    resp = client.post("/api/products", json=payload)
    assert resp.status_code == 201
    return resp.json()["id"]


def create_bs_model(client) -> str:
    resp = client.post(
        "/api/models",
        json={
            "name": "BS",
            "kind": "BSModelData_",
            "bs": {"spot": 100.0, "vol": 0.2, "rate": 0.0, "div": 0.0},
        },
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def create_trade(client, product_id: str, model_id: str, name: str = "t") -> str:
    resp = client.post(
        "/api/trades",
        json={"name": name, "product_id": product_id, "model_id": model_id, "notional": 1.0},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def create_portfolio_with_trades(client, trade_ids: list[str]) -> str:
    resp = client.post("/api/portfolios", json={"name": "PF"})
    assert resp.status_code == 201
    portfolio_id = resp.json()["id"]
    for trade_id in trade_ids:
        add = client.post(f"/api/portfolios/{portfolio_id}/trades/{trade_id}")
        assert add.status_code == 200
    return portfolio_id
