"""Native DAL dependency preflight for the web backend."""

from __future__ import annotations

import importlib
import sys
from types import ModuleType


class NativeDalUnavailableError(RuntimeError):
    """Raised when the native-only backend cannot load its DAL package."""


_REQUIRED_SYMBOLS = (
    "BSModelData_New",
    "Cell_",
    "Date_",
    "DoubleMatrix_",
    "DupireModelData_New",
    "EvaluationDate_Get",
    "EvaluationDate_Set",
    "MonteCarlo_Value",
    "Product_Debug",
    "Product_New",
)

_REQUIRED_CALIBRATION_SYMBOLS = (
    "CalibrateJointXccyMarket",
    "CalibrateMultiCurveBundle",
    "CalibrateSingleCurve",
    "CalibrateXccyMarket",
    "CurveCalibrationSpecBuilder_",
    "CrossCurrencyCalibrationSpecBuilder_",
    "InspectCurveCalibrationExecutionIdentity",
    "JointXccyCalibrationSpecBuilder_",
    "MultiCurveCalibrationSpec_",
    "PlanCurveCalibrationKnots",
    "ResolveCurveCalibrationInitialGuess",
    "ValidateCrossCurrencyAnalyticEligibility",
    "ValidateJointXccyAnalyticEligibility",
    "ValidateSingleCurveAnalyticEligibility",
)

_REQUIRED_PRIVATE_SYMBOLS = (
    "_RequiredHistoricalRateTradeFixings",
    "_RequiredHistoricalXccyFixings",
)

_TEST_DOUBLE_MARKER = "__dal_web_test_double__"


def _failure_message(reason: str) -> str:
    return (
        "Native DAL Python package is required by dal-web but could not be loaded.\n"
        "It is a declared dependency; install the environment and retry:\n"
        "  cd backend && uv sync\n"
        "To develop against an unreleased DAL build, install from a DAL source "
        "checkout instead:\n"
        "  uv pip install /path/to/Derivatives-Algorithms-Lib/dal-python "
        '"--config-settings=cmake.define.DAL_INSTALL_PREFIX='
        '/path/to/build/stage/<platform-preset>"\n'
        "See README.md#native-dal-package.\n"
        f"Underlying error: {reason}"
    )


def load_native_dal() -> ModuleType:
    """Import and minimally validate the compiled DAL Python package."""
    try:
        module = importlib.import_module("dal")
    except (ImportError, OSError) as exc:
        raise NativeDalUnavailableError(_failure_message(str(exc))) from exc

    missing = [name for name in _REQUIRED_SYMBOLS if not hasattr(module, name)]
    if not getattr(module, _TEST_DOUBLE_MARKER, False):
        missing.extend(name for name in _REQUIRED_CALIBRATION_SYMBOLS if not hasattr(module, name))
        extension = getattr(module, "_dal", None)
        missing.extend(
            f"_dal.{name}"
            for name in _REQUIRED_PRIVATE_SYMBOLS
            if extension is None or not hasattr(extension, name)
        )
    if missing:
        names = ", ".join(missing)
        raise NativeDalUnavailableError(
            _failure_message(f"the imported 'dal' module is missing required symbols: {names}")
        )
    return module


def main() -> int:
    """Return a shell-friendly status for startup-script preflight checks."""
    try:
        load_native_dal()
    except NativeDalUnavailableError as exc:
        print(exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
