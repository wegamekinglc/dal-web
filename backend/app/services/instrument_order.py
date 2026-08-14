"""Canonical calibration-instrument ordering shared by admission and gateway.

Admission (``calibrations.py``) persists instruments with a
``calibration_index`` assigned in canonical order; the gateway
(``dal_gateway.py``) must present instruments to the native solver in the
exact same order, otherwise the persisted index mapping breaks. Both sides
import from here so the ordering rule exists exactly once.
"""

from __future__ import annotations

from collections.abc import Sequence

_NATIVE_INSTRUMENT_NAMES = {
    "DEPOSIT": "Deposit",
    "FRA": "FRA",
    "FUTURE": "Future",
    "SWAP": "Swap",
    "OIS_SWAP": "OISSwap",
    "BASIS_SWAP": "BasisSwap",
    "XCCY_SWAP": "CrossCurrencySwap",
}


def native_instrument_name(kind: str) -> str:
    return _NATIVE_INSTRUMENT_NAMES[kind]


def instrument_order_key(instrument: object, native_name: str) -> tuple[object, object, str]:
    return (instrument.maturity, instrument.start, native_name)  # type: ignore[attr-defined]


def canonical_instrument_order(
    instruments: Sequence[object],
    native_names: Sequence[str] | None = None,
) -> list[int]:
    """Input indices sorted by (maturity, start, native instrument name)."""
    names = (
        list(native_names)
        if native_names is not None
        else [native_instrument_name(instrument.kind) for instrument in instruments]  # type: ignore[attr-defined]
    )
    return sorted(
        range(len(instruments)),
        key=lambda index: instrument_order_key(instruments[index], names[index]),
    )
