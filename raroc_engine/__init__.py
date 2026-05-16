"""OpenRAROC — Risk-Adjusted Return on Capital engine.

Public Python API for both the v1 single-period calculator (Basel III IRB
formulas, reverse solver, bank comparison) and the v2 multi-period engine
(Schedule + PeriodEngine, FacilityAggregates, curve-driven floating fixings).

v1 surface (kept unchanged for back-compat):
    from raroc_engine import RAROCCalculator, RAROCInput, RAROCOutput
    from raroc_engine import Repository, EngineConfig
    from raroc_engine import normalize_rating, PRODUCT_TYPES, RATING_ORDER

v2 surface (new in v2.0):
    from raroc_engine import Schedule, Period, PeriodEngine
    from raroc_engine import DiscountSpec, FacilityAggregates
    from raroc_engine import CurveRepository

See ``CHANGELOG.md`` for migration notes and ``METHODOLOGY.md`` for the math.
"""

from .aggregate import FacilityAggregates, aggregate_periods, attach_discount_factors
from .calculator import RAROCCalculator
from .config import EngineConfig
from .curve_shocks import (
    CompositeShock,
    CurvatureShock,
    CurveShockMod,
    CutPathShock,
    FlatteningShock,
    ForwardCurveShock,
    ParallelShock,
    ScaledShock,
    ScenarioDistribution,
    SteepeningShock,
    compose_shocks,
    shock_to_curve_points,
    simulate_curve_distribution,
)
from .curves import (
    CurveDataUnavailable,
    CurveFixingResult,
    CurvePoint,
    CurveRepository,
    ForwardCurve,
)
from .models import (
    ALL_VALID_RATINGS,
    FITCH_TO_MOODYS,
    MOODYS_TO_SP,
    PRODUCT_DESCRIPTIONS,
    PRODUCT_TYPES,
    RATING_ORDER,
    RAROCInput,
    RAROCOutput,
    SP_TO_MOODYS,
    Settings,
    normalize_rating,
)
from .period_engine import (
    DiscountSpec,
    PeriodEngine,
    PeriodEngineInput,
    PeriodEngineOutput,
    PeriodOutput,
)
from .portfolio import (
    ConcentrationCaps,
    ConcentrationView,
    Facility,
    FacilityResult,
    Portfolio,
    ReallocationResult,
    WalletAggregate,
)
from .repository import Repository
from .scenarios import (
    BankProfileSwapMod,
    DrawdownPatternMod,
    RatesShiftMod,
    RefinanceMod,
    Scenario,
    ScenarioComparison,
    ScenarioContext,
    ScenarioDelta,
    ScenarioMod,
    ScenarioRun,
    ScenarioRunner,
    ScenarioSegment,
    StructureSwapMod,
)
from .schedule import Period, Schedule

__version__ = "2.0.0"

__all__ = [
    # v1 single-period
    "RAROCCalculator",
    "RAROCInput",
    "RAROCOutput",
    "Repository",
    "EngineConfig",
    "Settings",
    "normalize_rating",
    "PRODUCT_TYPES",
    "PRODUCT_DESCRIPTIONS",
    "RATING_ORDER",
    "ALL_VALID_RATINGS",
    "SP_TO_MOODYS",
    "FITCH_TO_MOODYS",
    "MOODYS_TO_SP",
    # v2 multi-period
    "Period",
    "Schedule",
    "DiscountSpec",
    "PeriodEngine",
    "PeriodEngineInput",
    "PeriodEngineOutput",
    "PeriodOutput",
    "FacilityAggregates",
    "aggregate_periods",
    "attach_discount_factors",
    # Curves
    "CurveDataUnavailable",
    "CurveFixingResult",
    "CurvePoint",
    "CurveRepository",
    "ForwardCurve",
    # Portfolio (Task 2.1)
    "ConcentrationCaps",
    "ConcentrationView",
    "Facility",
    "FacilityResult",
    "Portfolio",
    "ReallocationResult",
    "WalletAggregate",
    # Scenarios (Task 3.1)
    "Scenario",
    "ScenarioComparison",
    "ScenarioContext",
    "ScenarioDelta",
    "ScenarioMod",
    "ScenarioRun",
    "ScenarioRunner",
    "ScenarioSegment",
    "RefinanceMod",
    "RatesShiftMod",
    "DrawdownPatternMod",
    "BankProfileSwapMod",
    "StructureSwapMod",
    # Forward-curve shocks (Task 4.1)
    "ForwardCurveShock",
    "ParallelShock",
    "SteepeningShock",
    "FlatteningShock",
    "CurvatureShock",
    "CutPathShock",
    "CompositeShock",
    "ScaledShock",
    "compose_shocks",
    "CurveShockMod",
    "ScenarioDistribution",
    "simulate_curve_distribution",
    "shock_to_curve_points",
]
