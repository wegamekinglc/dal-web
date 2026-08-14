"""Native request-building paths in ``DalGateway`` the shared fake DAL never reaches.

The canned ``dal`` module in ``tests/fake_dal.py`` only fakes the valuation
surface, so every calibration path gates on ``hasattr(self._dal, ...)`` and
drops into synthetic fallbacks.  The richer recording double below drives the
native branches directly: single-curve spec construction, all six
``_build_rate_instrument`` kinds, and the ``price_curve_lab_trades`` failure
branches that the risk API tests monkeypatch away.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from app.schemas.calibrations import SingleCalibrationRequest
from tests.fake_gateway import NativeDalGateway

DISCOUNT_KEY = "clab/v1/local/discount/USD/OIS"
PROJECTION_KEY = "clab/v1/local/projection/USD/3M"


class _ConventionRecord:
    """Mutable stand-in for a native index/leg convention struct."""

    def __init__(self, kind: str, args: tuple[Any, ...]) -> None:
        self.kind = kind
        self.args = args


class _FixingIdentity:
    def __init__(self) -> None:
        self.index_name = ""
        self.fixing_hour = 0
        self.fixing_minute = 0


class _SingleSpecBuilder:
    def __init__(self) -> None:
        self.built = False

    def Build(self):  # noqa: N802 - mirrors native DAL
        self.built = True
        return self


class _ArchiveExtension:
    """Private ``_dal`` bridge: records and decodes hash-verified archives."""

    def __init__(self, restored: list[bytes]) -> None:
        self._restored = restored

    def _StorableFromJson(self, payload: bytes) -> Any:  # noqa: N802
        self._restored.append(payload)
        return json.loads(payload)


class _RecordingNativeDal:
    """Richer fake DAL surface covering native calibration request construction."""

    CurveSolveMode = SimpleNamespace(EXACT="SOLVE.EXACT")
    CurveParameterization = SimpleNamespace(
        PIECEWISE_CONSTANT_FWD="PARAM.PWC_FWD",
        LOG_DISCOUNT="PARAM.LOG_DISCOUNT",
    )
    CurveKnotPolicy = SimpleNamespace(INPUT="KNOT.INPUT")
    LogDfScheme = SimpleNamespace(LOG_LINEAR="SCHEME.LOG_LINEAR")
    BizDayConvention_ = SimpleNamespace(FOLLOWING="BDC.FOLLOWING")
    RateInstrumentType = SimpleNamespace(
        DEPOSIT="RIT.DEPOSIT",
        FRA="RIT.FRA",
        FUTURE="RIT.FUTURE",
        OIS="RIT.OIS",
        IRS="RIT.IRS",
        BASIS_SWAP="RIT.BASIS_SWAP",
        XCCY="RIT.XCCY",
    )
    FixingIdentity_ = _FixingIdentity

    def __init__(self) -> None:
        self.spec_builders: list[_SingleSpecBuilder] = []
        self.instruments: list[dict[str, Any]] = []
        self.curve_blocks: list[dict[str, Any]] = []
        self.xccy_markets: list[dict[str, Any]] = []
        self.restored: list[bytes] = []
        self.markets: list[dict[str, Any]] = []
        self.price_calls: list[dict[str, Any]] = []
        self.sensitivity_calls: list[str] = []
        self.gradient: list[str] = ["0.0"]
        self._dal = _ArchiveExtension(self.restored)

        builders = self.spec_builders

        class BoundBuilder(_SingleSpecBuilder):
            def __init__(self) -> None:
                super().__init__()
                builders.append(self)

        self.CurveCalibrationSpecBuilder_ = BoundBuilder

    @staticmethod
    def Date_(year: int, month: int, day: int) -> str:  # noqa: N802
        return f"{year:04d}-{month:02d}-{day:02d}"

    @staticmethod
    def DateTime_(day: Any, hour: int, minute: int, second: int) -> tuple:  # noqa: N802
        return (day, hour, minute, second)

    @staticmethod
    def String_(value: str) -> str:  # noqa: N802
        return value

    @staticmethod
    def CollateralType_(value: str) -> str:  # noqa: N802
        return f"COLLATERAL.{value}"

    @staticmethod
    def PeriodLength_New(value: str) -> str:  # noqa: N802
        return f"PERIOD.{value}"

    @staticmethod
    def DayBasis_New(value: str) -> str:  # noqa: N802
        return f"BASIS.{value}"

    @staticmethod
    def Holidays_(value: str) -> str:  # noqa: N802
        return f"HOLIDAYS.{value}"

    @staticmethod
    def RateIndexConvention_New(*args: Any) -> _ConventionRecord:  # noqa: N802
        return _ConventionRecord("INDEX", args)

    @staticmethod
    def RateLegConvention_New(*args: Any) -> _ConventionRecord:  # noqa: N802
        return _ConventionRecord("LEG", args)

    def _instrument(self, kind: str, args: tuple[Any, ...]) -> dict[str, Any]:
        record = {"kind": kind, "args": args}
        self.instruments.append(record)
        return record

    def Deposit_New(self, *args: Any) -> dict[str, Any]:  # noqa: N802
        return self._instrument("DEPOSIT", args)

    def FRA_New(self, *args: Any) -> dict[str, Any]:  # noqa: N802
        return self._instrument("FRA", args)

    def Future_New(self, *args: Any) -> dict[str, Any]:  # noqa: N802
        return self._instrument("FUTURE", args)

    def Swap_New(self, *args: Any) -> dict[str, Any]:  # noqa: N802
        return self._instrument("SWAP", args)

    def OISSwap_New(self, *args: Any) -> dict[str, Any]:  # noqa: N802
        return self._instrument("OIS_SWAP", args)

    def BasisSwap_New(self, *args: Any) -> dict[str, Any]:  # noqa: N802
        return self._instrument("BASIS_SWAP", args)

    @staticmethod
    def MarketFixingSnapshot_New(values: Any) -> dict[str, Any]:  # noqa: N802
        return {"fixings": values}

    def CurveBlock_New(  # noqa: N802
        self,
        name: str,
        currency: str,
        discounts: dict[Any, Any],
        forwards: dict[Any, Any],
        basis: Any,
    ) -> dict[str, Any]:
        record = {
            "name": name,
            "currency": currency,
            "discounts": discounts,
            "forwards": forwards,
            "basis": basis,
        }
        self.curve_blocks.append(record)
        return record

    def CrossCurrencyMarket_New(self, **kwargs: Any) -> dict[str, Any]:  # noqa: N802
        self.xccy_markets.append(kwargs)
        return {"xccy_market": kwargs}

    def RatePricingMarket_(self, **kwargs: Any) -> dict[str, Any]:  # noqa: N802
        self.markets.append(kwargs)
        return {"market": kwargs}

    @staticmethod
    def DepositTradeTerms_(**kwargs: Any) -> dict[str, Any]:  # noqa: N802
        return {"kind": "DEPOSIT_TERMS", **kwargs}

    @staticmethod
    def RateTradeDefinition_(**kwargs: Any) -> dict[str, Any]:  # noqa: N802
        return {"kind": "TRADE", **kwargs}

    def PriceRateTrades(self, *, trades: Any, market: Any) -> list[Any]:  # noqa: N802
        self.price_calls.append({"trades": trades, "market": market})
        return [
            SimpleNamespace(
                succeeded=True,
                pv="1.0",
                currency="USD",
                required_historical_fixings=[],
                missing_historical_fixings=[],
                dependency_component_keys=[],
                error="",
            )
            for _ in trades
        ]

    def RateTradeNodeSensitivities(  # noqa: N802
        self,
        *,
        trade: Any,
        market: Any,
        component_key: str,
    ) -> Any:
        self.sensitivity_calls.append(component_key)
        return SimpleNamespace(eligible=True, gradient=self.gradient, reason="")


def _gateway_with_native_dal() -> tuple[NativeDalGateway, _RecordingNativeDal]:
    gateway = NativeDalGateway()
    dal = _RecordingNativeDal()
    gateway._dal = dal
    return gateway, dal


def _rate_index(tenor: str, collateral: str, *, basis: str = "ACT_365F") -> dict[str, object]:
    return {
        "spot_lag": 2,
        "fixing_lag": 1,
        "use_projection_curve": True,
        "forecast_tenor": tenor,
        "day_basis": basis,
        "business_day_convention": "Following",
        "fixing_holidays": "US-NY",
        "accrual_holidays": "",
        "end_of_month": False,
        "collateral": collateral,
    }


def _rate_leg(frequency: str, *, basis: str = "ACT_365F") -> dict[str, object]:
    return {
        "payment_frequency": frequency,
        "day_basis": basis,
        "payment_lag": 2,
        "business_day_convention": "Following",
        "payment_convention": "Following",
        "accrual_holidays": "",
        "payment_holidays": "US-NY",
        "end_of_month": False,
    }


def _instrument_payload(
    kind: str,
    start: str,
    maturity: str,
    rate: float,
    **extra: object,
) -> dict[str, object]:
    return {
        "kind": kind,
        "label": f"{kind} {maturity}",
        "trade_date": "2026-01-02",
        "start": start,
        "maturity": maturity,
        "market_rate": rate,
        **extra,
    }


def _declaration(**overrides: object) -> dict[str, object]:
    declaration: dict[str, object] = {
        "curve_name": "usd_ois",
        "target_collateral": "OIS",
        "target_tenor": None,
        "calibrate_discount_curve": True,
        "libor_basis": "ACT_365F",
        "parameterization": "PIECEWISE_CONSTANT_FWD",
        "log_df_scheme": None,
        "knot_policy": "INPUT",
        "knot_dates": ["2027-01-02", "2028-01-02"],
        "base_curve_id": None,
        "discount_curve_ids": {},
        "forward_curve_ids": {},
        "initial_guess_per_node": [],
    }
    declaration.update(overrides)
    return declaration


def _single_request(
    instruments: list[dict[str, object]],
    declaration: dict[str, object] | None = None,
) -> SingleCalibrationRequest:
    return SingleCalibrationRequest.model_validate(
        {
            "schema_version": 1,
            "name": "usd_ois_2026_01_02",
            "today": "2026-01-02",
            "currency": "USD",
            "declaration": _declaration() if declaration is None else declaration,
            "instruments": instruments,
            "solver": {
                "solve_mode": "EXACT",
                "smoothing_weight": 1.5,
                "tolerance": 1.0e-10,
                "fit_tolerance": 1.0e-7,
                "initial_guess": 0.05,
                "max_evaluations": 321,
                "max_restarts": 9,
            },
            "options": {
                "jacobian_mode": "ANALYTIC",
                "include_jacobian": False,
                "include_effective_inverse": False,
            },
        }
    )


def _plan(*node_dates: date, free_parameters: int) -> Any:
    return SimpleNamespace(
        storage_nodes=[SimpleNamespace(date=value) for value in node_dates],
        counts=SimpleNamespace(free_parameters=free_parameters),
    )


def test_single_spec_builder_receives_canonical_instruments_and_solver_surface() -> None:
    """``_configure_single_spec_builder`` maps the request onto the native builder."""
    gateway, dal = _gateway_with_native_dal()
    request = _single_request(
        [
            _instrument_payload(
                "FUTURE",
                "2026-03-18",
                "2028-01-05",
                0.024,
                index=_rate_index("P3M", "SOFR", basis="ACT_360"),
                convexity_adjustment=0.0,
            ),
            _instrument_payload(
                "SWAP",
                "2026-01-05",
                "2027-01-05",
                0.023,
                fixed_leg=_rate_leg("P6M", basis="30_360"),
                float_index=_rate_index("P3M", "SOFR"),
                float_leg=_rate_leg("P3M"),
            ),
            _instrument_payload(
                "DEPOSIT",
                "2026-01-05",
                "2027-01-05",
                0.022,
                index=_rate_index("P3M", "OIS"),
            ),
            _instrument_payload(
                "DEPOSIT",
                "2026-01-05",
                "2026-07-06",
                0.021,
                index=_rate_index("P6M", "OIS"),
            ),
        ]
    )
    plan = _plan(
        date(2026, 1, 2),
        date(2027, 1, 2),
        date(2028, 1, 2),
        free_parameters=3,
    )

    spec = gateway._build_single_spec(request, {}, plan)

    assert len(dal.spec_builders) == 1
    assert spec is dal.spec_builders[0]
    assert spec.built is True
    # Canonical (maturity, start, native-name) order, not submission order.
    assert [(item["kind"], item["args"][2], item["args"][3]) for item in spec.instruments_] == [
        ("DEPOSIT", "2026-07-06", 0.021),
        ("DEPOSIT", "2027-01-05", 0.022),
        ("SWAP", "2027-01-05", 0.023),
        ("FUTURE", "2028-01-05", 0.024),
    ]
    # The anchor storage node is excluded for non-LOG_DISCOUNT parameterizations.
    assert spec.knotDates_ == ["2027-01-02", "2028-01-02"]
    # Empty per-node guesses fall back to scalar x free-parameter count.
    assert spec.initialGuessPerNode_ == [0.05, 0.05, 0.05]
    assert spec.today_ == "2026-01-02"
    assert spec.ccy_ == "USD"
    assert spec.curveName_ == "usd_ois"
    assert spec.targetCollateral_ == "COLLATERAL.OIS"
    assert spec.calibrateDiscountCurve_ is True
    assert spec.liborBasis_ == "BASIS.ACT_365F"
    assert spec.smoothingWeight_ == 1.5
    assert spec.tolerance_ == 1.0e-10
    assert spec.fitTolerance_ == 1.0e-7
    assert spec.maxEvaluations_ == 321
    assert spec.maxRestarts_ == 9
    assert spec.initialGuess_ == 0.05
    assert spec.solveMode_ == "SOLVE.EXACT"
    assert spec.parameterization_ == "PARAM.PWC_FWD"
    assert spec.knotPolicy_ == "KNOT.INPUT"
    assert spec.logDfScheme_ == "SCHEME.LOG_LINEAR"
    assert spec.discountCurves_ == {}
    assert spec.forwardCurves_ == {}
    assert not hasattr(spec, "targetTenor_")


def test_single_spec_log_discount_keeps_anchor_and_explicit_guesses() -> None:
    gateway, dal = _gateway_with_native_dal()
    declaration = _declaration(
        target_tenor="P3M",
        calibrate_discount_curve=False,
        parameterization="LOG_DISCOUNT",
        log_df_scheme="LOG_LINEAR",
        knot_dates=["2026-01-02", "2027-01-02", "2028-01-02"],
        initial_guess_per_node=[0.011, 0.012, 0.013],
    )
    request = _single_request(
        [
            _instrument_payload(
                "DEPOSIT",
                "2026-01-05",
                "2027-01-05",
                0.02,
                index=_rate_index("P3M", "OIS"),
            )
        ],
        declaration,
    )
    plan = _plan(
        date(2026, 1, 2),
        date(2027, 1, 2),
        date(2028, 1, 2),
        free_parameters=3,
    )

    spec = gateway._build_single_spec(request, {}, plan)

    assert len(dal.spec_builders) == 1
    assert spec.knotDates_ == ["2026-01-02", "2027-01-02", "2028-01-02"]
    assert spec.initialGuessPerNode_ == [0.011, 0.012, 0.013]
    assert spec.parameterization_ == "PARAM.LOG_DISCOUNT"
    assert spec.logDfScheme_ == "SCHEME.LOG_LINEAR"
    assert spec.targetTenor_ == "PERIOD.3M"
    assert spec.calibrateDiscountCurve_ is False


def test_build_rate_instrument_maps_all_six_kinds() -> None:
    """Every rate-instrument kind must reach its native constructor with exact arguments."""
    gateway, dal = _gateway_with_native_dal()
    request = _single_request(
        [
            _instrument_payload(
                "DEPOSIT",
                "2026-01-05",
                "2026-04-06",
                0.031,
                index=_rate_index("P3M", "SOFR", basis="ACT_360"),
            ),
            _instrument_payload(
                "FRA",
                "2026-07-06",
                "2027-01-04",
                0.032,
                index=_rate_index("P6M", "OIS"),
            ),
            _instrument_payload(
                "FUTURE",
                "2026-03-18",
                "2026-06-17",
                0.033,
                index=_rate_index("P3M", "SOFR", basis="ACT_360"),
                convexity_adjustment=0.0025,
            ),
            _instrument_payload(
                "SWAP",
                "2026-01-05",
                "2028-01-05",
                0.034,
                fixed_leg=_rate_leg("P6M", basis="30_360"),
                float_index=_rate_index("P3M", "SOFR", basis="ACT_360"),
                float_leg=_rate_leg("P3M"),
            ),
            _instrument_payload(
                "OIS_SWAP",
                "2026-01-05",
                "2029-01-05",
                0.035,
                fixed_leg=_rate_leg("P12M"),
                overnight_index=_rate_index("P1D", "OIS", basis="ACT_360"),
                float_leg=_rate_leg("P12M", basis="ACT_360"),
            ),
            _instrument_payload(
                "BASIS_SWAP",
                "2026-01-05",
                "2030-01-05",
                0.0015,
                spread_index=_rate_index("P3M", "SOFR"),
                spread_leg=_rate_leg("P3M"),
                reference_index=_rate_index("P6M", "OIS"),
                reference_leg=_rate_leg("P6M"),
            ),
        ]
    )

    built = [gateway._build_rate_instrument(item) for item in request.instruments]

    assert [record["kind"] for record in dal.instruments] == [
        "DEPOSIT",
        "FRA",
        "FUTURE",
        "SWAP",
        "OIS_SWAP",
        "BASIS_SWAP",
    ]
    assert built == dal.instruments

    deposit, fra, future, swap, ois, basis = (record["args"] for record in dal.instruments)
    assert deposit[:4] == ("2026-01-02", "2026-01-05", "2026-04-06", 0.031)
    assert fra[:4] == ("2026-01-02", "2026-07-06", "2027-01-04", 0.032)
    assert future[:4] == ("2026-01-02", "2026-03-18", "2026-06-17", 0.033)
    assert future[5] == 0.0025

    deposit_index = deposit[4]
    assert deposit_index.args == ("PERIOD.3M", "BASIS.ACT_360", "COLLATERAL.SOFR", True)
    assert deposit_index.spot_lag == 2
    assert deposit_index.fixing_lag == 1
    assert deposit_index.business_day_convention == "BDC.FOLLOWING"
    assert deposit_index.fixing_holidays == "HOLIDAYS.US-NY"
    assert deposit_index.accrual_holidays == "HOLIDAYS."
    assert deposit_index.end_of_month is False
    assert fra[4].args == ("PERIOD.6M", "BASIS.ACT_365F", "COLLATERAL.OIS", True)
    assert future[4].args == ("PERIOD.3M", "BASIS.ACT_360", "COLLATERAL.SOFR", True)

    assert swap[:4] == ("2026-01-02", "2026-01-05", "2028-01-05", 0.034)
    fixed_leg, float_index, float_leg = swap[4:]
    assert fixed_leg.args == ("PERIOD.6M", "BASIS.30_360")
    assert fixed_leg.payment_lag == 2
    assert fixed_leg.business_day_convention == "BDC.FOLLOWING"
    assert fixed_leg.payment_convention == "BDC.FOLLOWING"
    assert fixed_leg.accrual_holidays == "HOLIDAYS."
    assert fixed_leg.payment_holidays == "HOLIDAYS.US-NY"
    assert fixed_leg.end_of_month is False
    assert float_index.args == ("PERIOD.3M", "BASIS.ACT_360", "COLLATERAL.SOFR", True)
    assert float_leg.args == ("PERIOD.3M", "BASIS.ACT_365F")

    assert ois[:4] == ("2026-01-02", "2026-01-05", "2029-01-05", 0.035)
    assert ois[4].args == ("PERIOD.12M", "BASIS.ACT_365F")
    # The OIS float index comes from ``overnight_index``, not ``float_index``.
    assert ois[5].args == ("PERIOD.1D", "BASIS.ACT_360", "COLLATERAL.OIS", True)
    assert ois[6].args == ("PERIOD.12M", "BASIS.ACT_360")

    assert basis[:4] == ("2026-01-02", "2026-01-05", "2030-01-05", 0.0015)
    spread_index, spread_leg, reference_index, reference_leg = basis[4:]
    assert spread_index.args == ("PERIOD.3M", "BASIS.ACT_365F", "COLLATERAL.SOFR", True)
    assert spread_leg.args == ("PERIOD.3M", "BASIS.ACT_365F")
    assert reference_index.args == ("PERIOD.6M", "BASIS.ACT_365F", "COLLATERAL.OIS", True)
    assert reference_leg.args == ("PERIOD.6M", "BASIS.ACT_365F")


def _archive_payload(name: str, rate: float) -> bytes:
    return json.dumps(
        {
            "~type": "DiscountPWC_v1",
            "name": name,
            "ccy": "USD",
            "knotDates": ["2027-01-15"],
            "rightVals": [rate],
        },
        separators=(",", ":"),
    ).encode()


def _version(payload: bytes) -> dict[str, object]:
    return {
        "native_payload": payload,
        "native_payload_hash": hashlib.sha256(payload).hexdigest(),
        "root_kind": "DISCOUNT_CURVE",
    }


def _single_declaration_document(component_key: str, role: str) -> dict[str, object]:
    return {
        "mode": "SINGLE",
        "as_of_date": "2026-01-15",
        "declarations": [
            {
                "component_key": component_key,
                "role": role,
                "currency": "USD",
                "parameterization": "PIECEWISE_CONSTANT_FWD",
            }
        ],
    }


def _xccy_trade() -> dict[str, object]:
    return {
        "trade_id": "f" * 32,
        "instrument_type": "XCCY",
        "trade_date": "2026-01-15",
        "start_date": "2026-01-16",
        "maturity_date": "2027-01-15",
        "currency_or_pair": "USD-EUR",
        "terms": {
            "fx_spot": 1.1,
            "position_count": "1",
            "contract_spread": "0.001",
            "side": "RECEIVE_NON_SPREAD_PAY_SPREAD",
            "domestic_notional": "100",
            "foreign_notional": "90",
        },
    }


def _deposit_trade() -> dict[str, object]:
    return {
        "trade_id": "a" * 32,
        "instrument_type": "DEPOSIT",
        "trade_date": "2026-01-15",
        "start_date": "2026-01-16",
        "maturity_date": "2027-01-15",
        "currency_or_pair": "USD",
        "terms": {
            "notional": "100",
            "contract_rate": "0.04",
            "side": "LEND",
            "forecast_tenor": "3M",
            "day_basis": "ACT_365F",
            "collateral": "OIS",
        },
    }


def test_price_curve_lab_trades_rejects_unavailable_version_archive() -> None:
    gateway, dal = _gateway_with_native_dal()
    document = _single_declaration_document(DISCOUNT_KEY, "DISCOUNT")

    with pytest.raises(ValueError) as excinfo:
        gateway.price_curve_lab_trades(
            document,
            [],
            "2026-01-15T10:30:00Z",
            "USD",
            curve_version={"root_kind": "DISCOUNT_CURVE"},
        )

    assert str(excinfo.value) == "selected Curve Lab version archive is unavailable"
    assert dal.restored == []


def test_price_curve_lab_trades_rejects_dependency_duplicating_selected_version() -> None:
    gateway, dal = _gateway_with_native_dal()
    document = _single_declaration_document(DISCOUNT_KEY, "DISCOUNT")
    selected = _archive_payload("selected", 0.04)
    dependency = _archive_payload("dependency", 0.03)
    dependencies = [
        {
            **_version(dependency),
            "verification": {
                "document": {"declarations": [{"component_key": DISCOUNT_KEY}]}
            },
        }
    ]

    with pytest.raises(ValueError) as excinfo:
        gateway.price_curve_lab_trades(
            document,
            [],
            "2026-01-15T10:30:00Z",
            "USD",
            curve_version=_version(selected),
            dependencies=dependencies,
        )

    assert (
        str(excinfo.value)
        == f"selected version duplicates dependency component {DISCOUNT_KEY!r}"
    )
    # Both archives are hash-verified and restored before the duplicate check.
    assert dal.restored == [selected, dependency]


def test_price_curve_lab_trades_requires_xccy_domestic_discount() -> None:
    gateway, dal = _gateway_with_native_dal()
    document = _single_declaration_document(PROJECTION_KEY, "PROJECTION")

    with pytest.raises(ValueError) as excinfo:
        gateway.price_curve_lab_trades(
            document,
            [_xccy_trade()],
            "2026-01-15T10:30:00Z",
            "USD",
            curve_version=_version(_archive_payload("projection", 0.02)),
        )

    assert str(excinfo.value) == "XCCY pricing is missing a discount declaration for USD"
    assert dal.curve_blocks == []
    assert dal.xccy_markets == []


def test_price_curve_lab_trades_requires_xccy_foreign_discount() -> None:
    gateway, dal = _gateway_with_native_dal()
    document = _single_declaration_document(DISCOUNT_KEY, "DISCOUNT")
    payload = _archive_payload("discount", 0.04)

    with pytest.raises(ValueError) as excinfo:
        gateway.price_curve_lab_trades(
            document,
            [_xccy_trade()],
            "2026-01-15T10:30:00Z",
            "USD",
            curve_version=_version(payload),
        )

    assert str(excinfo.value) == "XCCY pricing is missing a discount declaration for EUR"
    # The domestic block was fully constructed before the foreign side failed.
    assert dal.curve_blocks == [
        {
            "name": "curve-lab-USD",
            "currency": "USD",
            "discounts": {"COLLATERAL.OIS": json.loads(payload)},
            "forwards": {},
            "basis": "BASIS.ACT_365F",
        }
    ]
    assert dal.xccy_markets == []


def test_price_curve_lab_trades_rejects_mismatched_aad_gradient() -> None:
    gateway, dal = _gateway_with_native_dal()
    document = _single_declaration_document(DISCOUNT_KEY, "DISCOUNT")
    payload = _archive_payload("discount", 0.04)
    dal.gradient = ["0.75"]  # one gradient value against a two-entry parameter axis
    parameter_axis = [
        {
            "parameter_id": "p-late",
            "component_key": DISCOUNT_KEY,
            "node_date": "2028-01-15",
        },
        {
            "parameter_id": "p-early",
            "component_key": DISCOUNT_KEY,
            "node_date": "2027-01-15",
        },
    ]

    with pytest.raises(ValueError) as excinfo:
        gateway.price_curve_lab_trades(
            document,
            [_deposit_trade()],
            "2026-01-15T10:30:00Z",
            "USD",
            curve_version=_version(payload),
            parameter_axis=parameter_axis,
            include_node_sensitivities=True,
        )

    assert (
        str(excinfo.value)
        == "native AAD gradient does not match the persisted parameter axis"
    )
    # Pricing ran natively before the AAD axis check rejected the gradient.
    assert dal.markets[0]["curve_components"] == {DISCOUNT_KEY: json.loads(payload)}
    assert dal.markets[0]["xccy_market"] is None
    assert len(dal.price_calls) == 1
    trade_definition = dal.price_calls[0]["trades"][0]
    assert trade_definition["instrument_type"] == "RIT.DEPOSIT"
    assert trade_definition["terms"]["notional"] == 100.0
    assert trade_definition["terms"]["discount_component_key"] == DISCOUNT_KEY
    assert dal.sensitivity_calls == [DISCOUNT_KEY]
