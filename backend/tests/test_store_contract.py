"""Behavioral contract suite for the two ``StoreProtocol`` implementations.

The in-memory :class:`Store` and the SQLite-backed :class:`DbStore` must honor
identical reference-integrity, compare-and-swap, idempotency, and
restart-reconciliation semantics. Most of these behaviors were previously
pinned only against ``DbStore`` (test_persistence.py,
test_curve_lab_lifecycle_api.py); parametrizing them over both implementations
catches drift between the two.

The portfolio section at the bottom pins the API-level 404 mapping for unknown
portfolio/trade ids (``NotFoundError`` -> 404 via the handler in app.main).
"""

from __future__ import annotations

import hashlib
from datetime import date

import pytest

from app.schemas import (
    BSModelParams,
    EventRow,
    ModelDefinition,
    Portfolio,
    ProductDefinition,
    Trade,
)
from app.services.db.store_db import DbStore
from app.services.store import ConflictError, NotFoundError, Store


@pytest.fixture(params=["memory", "db"])
def any_store(request, tmp_path):
    """Yield each ``StoreProtocol`` implementation with a fresh state per test."""
    if request.param == "memory":
        yield Store()
        return
    # Mirrors the DbStore construction in tests/conftest.py: one SQLite file
    # per test, schema created eagerly, engine disposed on teardown.
    store = DbStore(url=f"sqlite:///{tmp_path / 'contract.db'}")
    store.create_all()
    yield store
    store.close()


def _make_product(name: str = "P") -> ProductDefinition:
    return ProductDefinition(
        name=name,
        description="d",
        template="european_call",
        rows=[
            EventRow(date_kind="label", label="STRIKE", event="120.00"),
            EventRow(
                date_kind="date",
                date=date(2025, 9, 15),
                event="call pays MAX(spot() - STRIKE, 0.0)",
            ),
        ],
    )


def _make_bs_model(name: str = "M") -> ModelDefinition:
    return ModelDefinition(
        name=name,
        kind="BSModelData_",
        bs=BSModelParams(spot=100.0, vol=0.15, rate=0.01, div=0.0),
    )


def _add_product_model_trade(store) -> tuple[ProductDefinition, ModelDefinition, Trade]:
    product = store.add_product(_make_product())
    model = store.add_model(_make_bs_model())
    trade = store.add_trade(Trade(name="t", product_id=product.id, model_id=model.id))
    return product, model, trade


# -- delete guards and cascades (store.py:257-267 / store.py:342-350) --------


def test_delete_product_referenced_by_trade_raises_conflict(any_store) -> None:
    product, _model, trade = _add_product_model_trade(any_store)

    with pytest.raises(ConflictError, match=trade.id):
        any_store.delete_product(product.id)
    # The product survives the rejected delete.
    assert any_store.get_product(product.id).id == product.id


def test_delete_model_referenced_by_trade_raises_conflict(any_store) -> None:
    _product, model, trade = _add_product_model_trade(any_store)

    with pytest.raises(ConflictError, match=trade.id):
        any_store.delete_model(model.id)
    assert any_store.get_model(model.id).id == model.id


def test_delete_unreferenced_product_and_model_succeeds(any_store) -> None:
    product, model, trade = _add_product_model_trade(any_store)
    # Once the referencing trade is gone the guards no longer fire.
    any_store.delete_trade(trade.id)

    any_store.delete_product(product.id)
    any_store.delete_model(model.id)

    with pytest.raises(NotFoundError):
        any_store.get_product(product.id)
    with pytest.raises(NotFoundError):
        any_store.get_model(model.id)


def test_delete_trade_cascades_portfolio_membership(any_store) -> None:
    _product, _model, trade = _add_product_model_trade(any_store)
    portfolio = any_store.add_portfolio(Portfolio(name="PF", trade_ids=[trade.id]))
    assert [t.id for t in any_store.portfolio_trades(portfolio.id)] == [trade.id]

    any_store.delete_trade(trade.id)

    assert any_store.portfolio_trades(portfolio.id) == []
    assert any_store.get_portfolio(portfolio.id).trade_ids == []


# -- Curve Lab record builders ------------------------------------------------

_PAYLOAD = b'{"~type":"DiscountPWC_v1","name":"contract"}'
_PAYLOAD_HASH = hashlib.sha256(_PAYLOAD).hexdigest()
_FUTURE_DEADLINE = "2026-01-15T00:15:00+00:00"
_PAST_DEADLINE = "2026-01-15T00:00:30+00:00"
_RESTARTED_AT = "2026-01-15T00:01:00+00:00"


def _draft_record() -> dict:
    return {
        "id": "d" * 32,
        "schema_version": 2,
        "revision": 1,
        "fingerprint": "f" * 64,
        "state": "READY_TO_BUILD",
        "document": {"schema_version": 2, "mode": "SINGLE"},
        "created_at": "2026-01-15T00:00:00Z",
        "updated_at": "2026-01-15T00:00:00Z",
    }


def _build_run_record(
    draft: dict,
    run_id: str,
    *,
    state: str,
    deadline_at: str = _FUTURE_DEADLINE,
    finished_at: str | None = None,
) -> dict:
    succeeded = state == "SUCCEEDED"
    return {
        "id": run_id,
        "draft_id": draft["id"],
        "draft_revision": draft["revision"],
        "draft_fingerprint": draft["fingerprint"],
        "state": state,
        "request": draft["document"],
        "resolved_plan": {"schema_version": 1},
        "quote_axis": [],
        "parameter_axis": [],
        "dependency_manifest": [],
        "native_payload": _PAYLOAD if succeeded else None,
        "native_payload_hash": _PAYLOAD_HASH if succeeded else None,
        "diagnostics": {"fit_state": state},
        "error": None,
        "created_at": "2026-01-15T00:00:00+00:00",
        "deadline_at": deadline_at,
        "finished_at": finished_at,
    }


def _version_record(build_run_id: str | None, *, version_id: str, key: str) -> dict:
    return {
        "id": version_id,
        "idempotency_key": key,
        "source_kind": "BUILD",
        "build_run_id": build_run_id,
        "import_job_id": None,
        "native_payload": _PAYLOAD,
        "native_payload_length": len(_PAYLOAD),
        "native_payload_hash": _PAYLOAD_HASH,
        "archive_numeric_format": "JSON_MAX_DIGITS10_V1",
        "root_kind": "DISCOUNT_CURVE",
        "build_validation_state": "VERIFIED",
        "visibility_state": "VISIBLE",
        "name": "contract",
        "version_note": None,
        "tags": [],
        "verification": {},
        "created_at": "2026-01-15T00:02:00Z",
    }


def _import_job_record(
    job_id: str,
    *,
    state: str,
    deadline_at: str = _FUTURE_DEADLINE,
    error: dict | None = None,
    finished_at: str | None = None,
) -> dict:
    return {
        "id": job_id,
        "request_hash": hashlib.sha256(job_id.encode()).hexdigest(),
        "compressed_payload_length": 1,
        "expanded_payload_length": 1,
        "state": state,
        "phase": state,
        "error": error,
        "resulting_version_id": None,
        "created_at": "2026-01-15T00:00:00+00:00",
        "deadline_at": deadline_at,
        "finished_at": finished_at,
    }


def _risk_run_record(
    run_id: str,
    version_id: str,
    *,
    state: str,
    deadline_at: str = _FUTURE_DEADLINE,
    finished_at: str | None = None,
) -> dict:
    return {
        "id": run_id,
        "curve_version_id": version_id,
        "calibration_run_id": None,
        "import_job_id": None,
        "source_kind": "VERSION",
        "request": {},
        "fixing_snapshot_hash": "b" * 64,
        "target_fingerprint": "c" * 64,
        "quote_axis": None,
        "parameter_axis": [],
        "estimated_work": {},
        "state": state,
        "result": {"ok": True} if state == "SUCCEEDED" else None,
        "error": None,
        "created_at": "2026-01-15T00:00:00+00:00",
        "deadline_at": deadline_at,
        "finished_at": finished_at,
    }


def _add_draft_and_succeeded_run(store) -> tuple[dict, dict]:
    draft = store.add_curve_lab_draft(_draft_record())
    run = store.add_curve_lab_build_run(
        _build_run_record(
            draft,
            "b" * 32,
            state="SUCCEEDED",
            finished_at="2026-01-15T00:00:30+00:00",
        )
    )
    return draft, run


# -- publish_curve_lab_version CAS + idempotency ------------------------------


def test_publish_curve_lab_version_succeeds_and_replays_idempotently(any_store) -> None:
    draft, run = _add_draft_and_succeeded_run(any_store)
    record = _version_record(run["id"], version_id="v" * 32, key="contract-publish")

    version, created = any_store.publish_curve_lab_version(
        record, draft["id"], draft["revision"], draft["fingerprint"], run["id"]
    )
    assert created is True
    assert version["id"] == record["id"]
    assert version["build_run_id"] == run["id"]

    # Same idempotency key returns the stored version without inserting a row.
    replay = {**record, "id": "e" * 32, "name": "must not win"}
    again, created_again = any_store.publish_curve_lab_version(
        replay, draft["id"], draft["revision"], draft["fingerprint"], run["id"]
    )
    assert created_again is False
    assert again["id"] == record["id"]
    assert again["name"] == "contract"
    assert [item["id"] for item in any_store.list_curve_lab_versions(True)] == [record["id"]]


@pytest.mark.parametrize(
    ("revision", "fingerprint"),
    [(2, "f" * 64), (1, "0" * 64)],
)
def test_publish_curve_lab_version_rejects_draft_cas_mismatch(
    any_store, revision: int, fingerprint: str
) -> None:
    draft, run = _add_draft_and_succeeded_run(any_store)

    with pytest.raises(ConflictError):
        any_store.publish_curve_lab_version(
            _version_record(run["id"], version_id="v" * 32, key="contract-cas"),
            draft["id"],
            revision,
            fingerprint,
            run["id"],
        )
    assert any_store.list_curve_lab_versions(True) == []


def test_publish_curve_lab_version_rejects_stale_build_run(any_store) -> None:
    draft = any_store.add_curve_lab_draft(_draft_record())
    failed_run = any_store.add_curve_lab_build_run(
        _build_run_record(draft, "b" * 32, state="FAILED", finished_at=_RESTARTED_AT)
    )

    with pytest.raises(ConflictError):
        any_store.publish_curve_lab_version(
            _version_record(failed_run["id"], version_id="v" * 32, key="contract-stale"),
            draft["id"],
            draft["revision"],
            draft["fingerprint"],
            failed_run["id"],
        )
    assert any_store.list_curve_lab_versions(True) == []


def test_publish_curve_lab_version_unknown_draft_or_run_raises_not_found(any_store) -> None:
    draft, run = _add_draft_and_succeeded_run(any_store)

    with pytest.raises(NotFoundError):
        any_store.publish_curve_lab_version(
            _version_record(run["id"], version_id="v" * 32, key="contract-missing-draft"),
            "0" * 32,
            draft["revision"],
            draft["fingerprint"],
            run["id"],
        )
    with pytest.raises(NotFoundError):
        any_store.publish_curve_lab_version(
            _version_record("1" * 32, version_id="v" * 32, key="contract-missing-run"),
            draft["id"],
            draft["revision"],
            draft["fingerprint"],
            "1" * 32,
        )


# -- reconcile_curve_lab_inflight ---------------------------------------------


def _server_restarted_error(previous_state: str, resource_id: str) -> dict:
    return {
        "code": "SERVER_RESTARTED",
        "message": "Server restarted while Curve Lab work was running.",
        "field": "state",
        "value": previous_state,
        "resource_id": resource_id,
        "details": {},
    }


def _soft_deadline_error(resource_id: str) -> dict:
    return {
        "code": "SOFT_DEADLINE_EXCEEDED",
        "message": "Curve Lab work exceeded its persisted soft deadline.",
        "field": "deadline_at",
        "value": _PAST_DEADLINE,
        "resource_id": resource_id,
        "details": {},
    }


def test_reconcile_curve_lab_inflight_fails_or_times_out_inflight_rows(any_store) -> None:
    draft = any_store.add_curve_lab_draft(_draft_record())
    # Risk runs carry a NOT NULL FK to curve_versions, so a parent version row
    # must exist before any risk run can be staged (both stores accept this).
    version, _ = any_store.add_curve_lab_version(
        _version_record(None, version_id="v" * 32, key="contract-risk-parent")
    )
    inflight = (
        ("build-queued", "QUEUED", _FUTURE_DEADLINE),
        ("build-solving-expired", "SOLVING", _PAST_DEADLINE),
    )
    for run_id, state, deadline_at in inflight:
        any_store.add_curve_lab_build_run(
            _build_run_record(draft, run_id, state=state, deadline_at=deadline_at)
        )
    any_store.add_curve_lab_import_job(_import_job_record("import-queued", state="QUEUED"))
    any_store.add_curve_lab_import_job(
        _import_job_record("import-running-expired", state="RUNNING", deadline_at=_PAST_DEADLINE)
    )
    any_store.publish_curve_lab_risk_run(
        _risk_run_record("risk-queued", version["id"], state="QUEUED"), []
    )
    any_store.publish_curve_lab_risk_run(
        _risk_run_record(
            "risk-running-expired", version["id"], state="RUNNING", deadline_at=_PAST_DEADLINE
        ),
        [],
    )
    # Terminal rows must be left untouched by reconciliation.
    any_store.add_curve_lab_build_run(
        _build_run_record(
            draft,
            "build-succeeded",
            state="SUCCEEDED",
            finished_at="2026-01-15T00:00:45+00:00",
        )
    )
    original_import_error = {"code": "ORIGINAL", "message": "boom"}
    any_store.add_curve_lab_import_job(
        _import_job_record(
            "import-failed",
            state="FAILED",
            error=original_import_error,
            finished_at="2026-01-15T00:00:45+00:00",
        )
    )
    any_store.publish_curve_lab_risk_run(
        _risk_run_record(
            "risk-succeeded",
            version["id"],
            state="SUCCEEDED",
            finished_at="2026-01-15T00:00:45+00:00",
        ),
        [],
    )

    assert any_store.reconcile_curve_lab_inflight(_RESTARTED_AT) == 6

    restarted_failures = (
        (any_store.get_curve_lab_build_run, "build-queued", "QUEUED"),
        (any_store.get_curve_lab_import_job, "import-queued", "QUEUED"),
        (any_store.get_curve_lab_risk_run, "risk-queued", "QUEUED"),
    )
    for getter, record_id, previous in restarted_failures:
        record = getter(record_id)
        assert record["state"] == "FAILED"
        assert record["error"] == _server_restarted_error(previous, record_id)
        assert record["finished_at"] == _RESTARTED_AT
    timed_out = (
        any_store.get_curve_lab_build_run("build-solving-expired"),
        any_store.get_curve_lab_import_job("import-running-expired"),
        any_store.get_curve_lab_risk_run("risk-running-expired"),
    )
    for record in timed_out:
        assert record["state"] == "TIMED_OUT"
        assert record["error"] == _soft_deadline_error(record["id"])
        assert record["finished_at"] == _RESTARTED_AT
    # A timed-out build keeps its diagnostics with the fit state flipped.
    assert timed_out[0]["diagnostics"]["fit_state"] == "TIMED_OUT"
    # Non-expired failures keep their diagnostics as they were.
    assert any_store.get_curve_lab_build_run("build-queued")["diagnostics"]["fit_state"] == "QUEUED"

    succeeded_build = any_store.get_curve_lab_build_run("build-succeeded")
    assert succeeded_build["state"] == "SUCCEEDED"
    assert succeeded_build["error"] is None
    assert succeeded_build["finished_at"] == "2026-01-15T00:00:45+00:00"
    failed_import = any_store.get_curve_lab_import_job("import-failed")
    assert failed_import["state"] == "FAILED"
    assert failed_import["error"] == original_import_error
    assert failed_import["finished_at"] == "2026-01-15T00:00:45+00:00"
    succeeded_risk = any_store.get_curve_lab_risk_run("risk-succeeded")
    assert succeeded_risk["state"] == "SUCCEEDED"
    assert succeeded_risk["finished_at"] == "2026-01-15T00:00:45+00:00"

    # Reconciliation is idempotent: nothing remains in flight.
    assert any_store.reconcile_curve_lab_inflight(_RESTARTED_AT) == 0


# -- portfolio router 404s (app/routers/portfolios.py:38-86) ------------------

_UNKNOWN_PORTFOLIO = "no-such-portfolio"


def test_get_unknown_portfolio_returns_404(client) -> None:
    response = client.get(f"/api/portfolios/{_UNKNOWN_PORTFOLIO}")
    assert response.status_code == 404
    assert _UNKNOWN_PORTFOLIO in response.json()["detail"]


def test_portfolio_trades_unknown_portfolio_returns_404(client) -> None:
    response = client.get(f"/api/portfolios/{_UNKNOWN_PORTFOLIO}/trades")
    assert response.status_code == 404
    assert _UNKNOWN_PORTFOLIO in response.json()["detail"]


def test_add_trade_unknown_portfolio_or_trade_returns_404(client) -> None:
    missing_portfolio = client.post(f"/api/portfolios/{_UNKNOWN_PORTFOLIO}/trades/some-trade")
    assert missing_portfolio.status_code == 404
    assert _UNKNOWN_PORTFOLIO in missing_portfolio.json()["detail"]

    portfolio = client.post("/api/portfolios", json={"name": "PF"})
    assert portfolio.status_code == 201
    portfolio_id = portfolio.json()["id"]
    missing_trade = client.post(f"/api/portfolios/{portfolio_id}/trades/no-such-trade")
    assert missing_trade.status_code == 404
    assert "no-such-trade" in missing_trade.json()["detail"]


def test_remove_trade_unknown_portfolio_returns_404(client) -> None:
    response = client.delete(f"/api/portfolios/{_UNKNOWN_PORTFOLIO}/trades/some-trade")
    assert response.status_code == 404
    assert _UNKNOWN_PORTFOLIO in response.json()["detail"]


def test_remove_unknown_trade_from_known_portfolio_is_a_noop(client) -> None:
    portfolio = client.post("/api/portfolios", json={"name": "PF"})
    assert portfolio.status_code == 201
    portfolio_id = portfolio.json()["id"]

    response = client.delete(f"/api/portfolios/{portfolio_id}/trades/no-such-trade")
    assert response.status_code == 200
    assert response.json()["trade_ids"] == []
    assert client.get(f"/api/portfolios/{portfolio_id}/trades").json() == []
