"""Shared helpers for the Curve Lab draft/build/risk API tests."""

from __future__ import annotations

import time

import pytest

DISCOUNT_KEY = "clab/v1/local/discount/USD/OIS"


def wait_for_job(
    client,
    collection: str,
    job_id: str,
    terminal_states: set[str],
) -> dict[str, object]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        record = client.get(f"/api/curve-lab/{collection}/{job_id}").json()
        if record["state"] in terminal_states:
            return record
        time.sleep(0.01)
    pytest.fail(f"{collection}/{job_id} did not reach a terminal state")


def completed_import(client, response) -> dict[str, object]:
    assert response.status_code == 202, response.text
    admitted = response.json()
    assert admitted["state"] == "QUEUED"
    completed = wait_for_job(
        client,
        "import-jobs",
        admitted["id"],
        {"SUCCEEDED", "FAILED", "TIMED_OUT"},
    )
    assert completed["state"] == "SUCCEEDED", completed
    return completed


def completed_risk(client, response) -> dict[str, object]:
    assert response.status_code == 202, response.text
    admitted = response.json()
    assert admitted["state"] == "QUEUED"
    completed = wait_for_job(
        client,
        "risk-runs",
        admitted["id"],
        {"SUCCEEDED", "FAILED", "TIMED_OUT"},
    )
    assert completed["state"] == "SUCCEEDED", completed
    return completed


def completed_build(client, draft_id: str) -> dict[str, object]:
    response = client.post(f"/api/curve-lab/drafts/{draft_id}/build-runs")
    assert response.status_code == 202, response.text
    admitted = response.json()
    assert admitted["state"] == "QUEUED"
    completed = wait_for_job(
        client,
        "build-runs",
        admitted["id"],
        {"SUCCEEDED", "FAILED", "TIMED_OUT"},
    )
    assert completed["state"] == "SUCCEEDED", completed
    return completed


def single_ois_document(
    raw_quote: str = "0.04",
    *,
    start_date: str = "2026-01-16",
    maturity_date: str = "2026-04-16",
    terms: dict | None = None,
) -> dict[str, object]:
    return {
        "schema_version": 2,
        "mode": "SINGLE",
        "as_of_date": "2026-01-15",
        "market_snapshot_id": "market-2026-01-15",
        "declarations": [
            {
                "component_key": DISCOUNT_KEY,
                "role": "DISCOUNT",
                "currency": "USD",
                "parameterization": "PIECEWISE_CONSTANT_FWD",
            }
        ],
        "instruments": [
            {
                "instrument_type": "DEPOSIT",
                "trade_date": "2026-01-15",
                "start_date": start_date,
                "maturity_date": maturity_date,
                "currency_or_pair": "USD",
                "raw_quote": raw_quote,
                "source": "TEST",
                "observed_at": "2026-01-15T00:00:00Z",
                "included": True,
                "terms": {"index": "USD-SOFR"} if terms is None else terms,
            }
        ],
        "dependency_version_ids": [],
        "solver": {
            "solve_mode": "EXACT",
            "parameterization": "PIECEWISE_CONSTANT_FWD",
        },
    }
