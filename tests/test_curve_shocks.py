"""Tests for raroc_engine.curve_shocks.

Acceptance (PLAN Task 4.1): a parallel shock of ±100 bp on a 5y RCF
produces directionally correct NPV deltas; combined shocks compose
correctly; regression test pins outputs to seeded inputs.

This file also covers the four richer shock shapes (steepening,
flattening, curvature, cut-path) and the distribution helper that
fans out a list of shocks into an NPV distribution — the
"what is the worst case if rates fall 200 bp in the next 18 months"
use case in the task brief.
"""

from __future__ import annotations

import os
from datetime import date
from typing import Tuple

import pytest
import yaml

from raroc_engine import (
    DiscountSpec,
    EngineConfig,
    PeriodEngine,
    RAROCInput,
    Schedule,
)
from raroc_engine.curve_shocks import (
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
from raroc_engine.scenarios import (
    RatesShiftMod,
    RefinanceMod,
    Scenario,
    ScenarioRunner,
)


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
RCF_FIXTURE = "period_rcf_5y"


def load_fixture(name: str) -> dict:
    with open(os.path.join(FIXTURES_DIR, f"{name}.yaml")) as f:
        return yaml.safe_load(f)


def make_inputs(fixture_name: str = RCF_FIXTURE) -> Tuple[
    EngineConfig, RAROCInput, Schedule, DiscountSpec, dict
]:
    fx = load_fixture(fixture_name)
    cfg = EngineConfig.from_dict(fx["engine_config"])
    deal = RAROCInput(
        product_type=fx["deal"]["product_type"],
        rating=fx["deal"]["rating"],
        global_grr=float(fx["deal"].get("global_grr", 0.0)),
        confirmed=bool(fx["deal"].get("confirmed", True)),
        spread=float(fx["deal"].get("spread", 0.0)),
        commitment_fee=float(fx["deal"].get("commitment_fee", 0.0)),
    )
    schedule = Schedule.from_dict(fx["schedule"])
    discount = DiscountSpec(
        kind=fx["discount"].get("kind", "scalar"),
        rate=float(fx["discount"].get("rate", 0.0325)),
        day_count=fx["discount"].get("day_count", "Act/365F"),
    )
    return cfg, deal, schedule, discount, fx


# ──────────────────────────────────────────────────────────────────────
# Shock primitives — math sanity (no engine)
# ──────────────────────────────────────────────────────────────────────


def test_parallel_shock_constant_across_tenor():
    s = ParallelShock(75)
    for t in (0.0, 0.5, 1.0, 5.0, 30.0):
        assert s.shock_bp(t) == 75.0
        assert s.shock_decimal(t) == pytest.approx(0.0075)


def test_steepening_shock_interpolates_linearly():
    s = SteepeningShock(short_shift_bps=0, long_shift_bps=100, long_anchor_years=10)
    assert s.shock_bp(0) == 0.0
    assert s.shock_bp(5) == 50.0
    assert s.shock_bp(10) == 100.0
    # Clamps outside the anchor.
    assert s.shock_bp(15) == 100.0
    assert s.shock_bp(-1) == 0.0


def test_flattening_shock_uses_same_math_as_steepening():
    """FlatteningShock differs from SteepeningShock only in describe()."""
    a = SteepeningShock(short_shift_bps=50, long_shift_bps=-50)
    b = FlatteningShock(short_shift_bps=50, long_shift_bps=-50)
    for t in (0.0, 2.5, 5.0, 7.5):
        assert a.shock_bp(t) == b.shock_bp(t)
    # Describes differ.
    assert "steepening" in a.describe()
    assert "flattening" in b.describe()


def test_curvature_shock_triangular_bump():
    s = CurvatureShock(peak_shift_bps=100, peak_years=3.0, half_width_years=2.0)
    # At the peak.
    assert s.shock_bp(3.0) == 100.0
    # Half-way down each flank.
    assert s.shock_bp(2.0) == pytest.approx(50.0)
    assert s.shock_bp(4.0) == pytest.approx(50.0)
    # At and beyond the edges.
    assert s.shock_bp(1.0) == 0.0
    assert s.shock_bp(5.0) == 0.0
    assert s.shock_bp(0.0) == 0.0
    assert s.shock_bp(10.0) == 0.0


def test_curvature_shock_degenerate_zero_width():
    """Zero half-width = no bump (avoids divide-by-zero)."""
    s = CurvatureShock(peak_shift_bps=100, peak_years=2.0, half_width_years=0.0)
    for t in (0.0, 2.0, 5.0):
        assert s.shock_bp(t) == 0.0


def test_cut_path_shock_is_step_function():
    """200 bp cumulative drop over 18 months in 3 steps."""
    s = CutPathShock(cuts=((0.5, -50), (1.0, -100), (1.5, -200)))
    assert s.shock_bp(0.0) == 0.0
    assert s.shock_bp(0.4) == 0.0
    assert s.shock_bp(0.5) == -50.0
    assert s.shock_bp(0.9) == -50.0
    assert s.shock_bp(1.0) == -100.0
    assert s.shock_bp(1.4) == -100.0
    assert s.shock_bp(1.5) == -200.0
    # After the last anchor, the last cumulative value sticks.
    assert s.shock_bp(5.0) == -200.0


def test_cut_path_shock_unordered_input_is_normalised():
    """Input pairs may arrive in any order; class sorts internally."""
    a = CutPathShock(cuts=((1.5, -200), (0.5, -50), (1.0, -100)))
    b = CutPathShock(cuts=((0.5, -50), (1.0, -100), (1.5, -200)))
    for t in (0.0, 0.4, 0.5, 0.9, 1.0, 1.4, 1.5, 2.0):
        assert a.shock_bp(t) == b.shock_bp(t)


def test_compose_shocks_sums_pointwise():
    a = ParallelShock(50)
    b = SteepeningShock(short_shift_bps=0, long_shift_bps=100)
    c = compose_shocks(a, b)
    for t in (0.0, 2.5, 5.0, 10.0):
        assert c.shock_bp(t) == pytest.approx(a.shock_bp(t) + b.shock_bp(t))


def test_compose_shocks_flattens_nested_composites():
    a = ParallelShock(10)
    b = ParallelShock(20)
    c = ParallelShock(30)
    nested = compose_shocks(compose_shocks(a, b), c)
    assert isinstance(nested, CompositeShock)
    assert len(nested.components) == 3
    assert nested.shock_bp(0.0) == pytest.approx(60.0)


def test_compose_shocks_empty_returns_zero_parallel():
    s = compose_shocks()
    assert isinstance(s, ParallelShock)
    assert s.shock_bp(0.0) == 0.0


def test_compose_shocks_single_returns_input():
    a = ParallelShock(42)
    assert compose_shocks(a) is a


def test_shock_addition_operator():
    """``a + b`` returns a CompositeShock equivalent to compose_shocks(a, b)."""
    a = ParallelShock(50)
    b = SteepeningShock(short_shift_bps=10, long_shift_bps=110)
    s = a + b
    for t in (0.0, 2.5, 5.0):
        assert s.shock_bp(t) == pytest.approx(a.shock_bp(t) + b.shock_bp(t))


def test_shock_negation_operator():
    """``-shock`` produces a ScaledShock that inverts the original."""
    a = ParallelShock(100)
    neg = -a
    assert isinstance(neg, ScaledShock)
    for t in (0.0, 2.5, 5.0):
        assert neg.shock_bp(t) == -100.0


def test_shock_scalar_multiplication():
    a = ParallelShock(100)
    scaled = 2.5 * a
    for t in (0.0, 2.5, 5.0):
        assert scaled.shock_bp(t) == 250.0


def test_shock_to_curve_points_samples_pillar_tenors():
    s = SteepeningShock(short_shift_bps=0, long_shift_bps=100)
    pts = shock_to_curve_points(s, [0.0, 2.5, 5.0, 10.0])
    assert pts == [(0.0, 0.0), (2.5, 25.0), (5.0, 50.0), (10.0, 100.0)]


# ──────────────────────────────────────────────────────────────────────
# Acceptance criterion 1: parallel ±100 bp on 5y RCF — directional
# ──────────────────────────────────────────────────────────────────────


def test_parallel_plus_100_bp_lowers_npv_borrower_cost():
    """+100 bp on the discount curve → DFs fall → NPV borrower cost falls."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    base = runner.run_base(deal, schedule, discount)
    scenario = Scenario("parallel_+100", [CurveShockMod(shock=ParallelShock(100))])
    run = runner.run_scenario(deal, schedule, scenario, discount)
    assert run.npv_borrower_cost < base.npv_borrower_cost
    # Sensible magnitude: the rate is going from 3.25% to 4.25% on a 5y
    # facility — expect a 1-5% drop in NPV (DFs compound).
    rel_drop = (base.npv_borrower_cost - run.npv_borrower_cost) / base.npv_borrower_cost
    assert 0.005 < rel_drop < 0.05


def test_parallel_minus_100_bp_lifts_npv_borrower_cost():
    """-100 bp → DFs rise → NPV borrower cost rises."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    base = runner.run_base(deal, schedule, discount)
    scenario = Scenario("parallel_-100", [CurveShockMod(shock=ParallelShock(-100))])
    run = runner.run_scenario(deal, schedule, scenario, discount)
    assert run.npv_borrower_cost > base.npv_borrower_cost
    rel_lift = (run.npv_borrower_cost - base.npv_borrower_cost) / base.npv_borrower_cost
    assert 0.005 < rel_lift < 0.05


def test_parallel_shock_symmetric_around_zero():
    """±100 bp produce approximately equal-magnitude (opposite-sign) NPV deltas.

    Exact symmetry is broken by the non-linear (1+r)^(-t) DF — the
    +100 drop is slightly smaller than the -100 lift. We test that
    the asymmetry is within reason (< 20% of the mean magnitude).
    """
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    base = runner.run_base(deal, schedule, discount)
    up = runner.run_scenario(
        deal, schedule,
        Scenario("up", [CurveShockMod(shock=ParallelShock(100))]),
        discount,
    )
    down = runner.run_scenario(
        deal, schedule,
        Scenario("dn", [CurveShockMod(shock=ParallelShock(-100))]),
        discount,
    )
    drop = base.npv_borrower_cost - up.npv_borrower_cost
    lift = down.npv_borrower_cost - base.npv_borrower_cost
    assert drop > 0 and lift > 0
    asymmetry = abs(lift - drop) / ((lift + drop) / 2)
    assert asymmetry < 0.20


def test_parallel_shock_does_not_change_raroc_by_default():
    """affect_engine_rate=False (default) → cfg.rfr unchanged → RAROC unchanged.

    Curve shocks describe rate scenarios; the engine ``rfr`` term is
    a hurdle rate — by default it stays put under curve shocks.
    """
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    base = runner.run_base(deal, schedule, discount)
    run = runner.run_scenario(
        deal, schedule,
        Scenario("noop_engine", [CurveShockMod(shock=ParallelShock(-100))]),
        discount,
    )
    for r_base, r_scen in zip(base.per_period, run.per_period):
        assert r_scen.raroc == pytest.approx(r_base.raroc, abs=1e-12)


def test_parallel_shock_with_engine_rate_matches_rates_shift_mod():
    """With affect_engine_rate=True a ParallelShock collapses onto RatesShiftMod.

    For a fixed-rate facility with funding_cost_bp=0 the RAROC delta
    is exactly (1-tax) × shift_bps; both mods produce the same
    numerical result.
    """
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    curve_run = runner.run_scenario(
        deal, schedule,
        Scenario("curve", [CurveShockMod(
            shock=ParallelShock(-100),
            affect_engine_rate=True,
        )]),
        discount,
    )
    level_run = runner.run_scenario(
        deal, schedule,
        Scenario("level", [RatesShiftMod(shift_bps=-100)]),
        discount,
    )
    assert curve_run.npv_borrower_cost == pytest.approx(
        level_run.npv_borrower_cost, rel=1e-9
    )
    for a, b in zip(curve_run.per_period, level_run.per_period):
        assert a.raroc == pytest.approx(b.raroc, abs=1e-12)


# ──────────────────────────────────────────────────────────────────────
# Acceptance criterion 2: combined shocks compose correctly
# ──────────────────────────────────────────────────────────────────────


def test_compose_two_parallels_equals_single_parallel():
    """ParallelShock(50) ⊕ ParallelShock(50) ≡ ParallelShock(100)."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    composed = runner.run_scenario(
        deal, schedule,
        Scenario("compose", [CurveShockMod(
            shock=compose_shocks(ParallelShock(50), ParallelShock(50)),
        )]),
        discount,
    )
    single = runner.run_scenario(
        deal, schedule,
        Scenario("single", [CurveShockMod(shock=ParallelShock(100))]),
        discount,
    )
    assert composed.npv_borrower_cost == pytest.approx(
        single.npv_borrower_cost, abs=1e-9
    )
    for a, b in zip(composed.per_period, single.per_period):
        assert a.df == pytest.approx(b.df, abs=1e-15)


def test_compose_parallel_plus_steepening_matches_pointwise_sum():
    """Discount rate per period = base + parallel + steepening at that tenor."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    parallel = ParallelShock(25)
    steep = SteepeningShock(short_shift_bps=0, long_shift_bps=100, long_anchor_years=10)
    composed = runner.run_scenario(
        deal, schedule,
        Scenario("p+s", [CurveShockMod(shock=parallel + steep)]),
        discount,
    )
    # Each period's DF should be (1 + base + parallel + steep)^(-t).
    base_rate = float(discount.rate)
    for row in composed.per_period:
        t = row.t_end_years
        expected_rate = base_rate + parallel.shock_decimal(t) + steep.shock_decimal(t)
        expected_df = (1.0 + expected_rate) ** (-t)
        assert row.df == pytest.approx(expected_df, rel=1e-12)


def test_compose_via_runner_chained_mods_equals_single_composite():
    """Two CurveShockMods chained in a scenario sum the same as one composite mod."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    a = ParallelShock(30)
    b = SteepeningShock(short_shift_bps=10, long_shift_bps=70)
    chained = runner.run_scenario(
        deal, schedule,
        Scenario("chained", [
            CurveShockMod(shock=a),
            CurveShockMod(shock=b),
        ]),
        discount,
    )
    composite = runner.run_scenario(
        deal, schedule,
        Scenario("composite", [CurveShockMod(shock=a + b)]),
        discount,
    )
    assert chained.npv_borrower_cost == pytest.approx(
        composite.npv_borrower_cost, abs=1e-9
    )
    for x, y in zip(chained.per_period, composite.per_period):
        assert x.df == pytest.approx(y.df, abs=1e-15)


def test_zero_shock_equals_base():
    """ParallelShock(0) leaves the engine output unchanged."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    base = runner.run_base(deal, schedule, discount)
    run = runner.run_scenario(
        deal, schedule,
        Scenario("zero", [CurveShockMod(shock=ParallelShock(0))]),
        discount,
    )
    assert run.npv_borrower_cost == pytest.approx(base.npv_borrower_cost, abs=1e-9)
    for a, b in zip(run.per_period, base.per_period):
        assert a.df == pytest.approx(b.df, abs=1e-15)


def test_negate_shock_inverts_npv_delta_approximately():
    """For small shocks, +ε and -ε produce roughly equal-magnitude NPV moves."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    base = runner.run_base(deal, schedule, discount)
    s = ParallelShock(25)
    up = runner.run_scenario(
        deal, schedule,
        Scenario("up", [CurveShockMod(shock=s)]),
        discount,
    )
    down = runner.run_scenario(
        deal, schedule,
        Scenario("down", [CurveShockMod(shock=-s)]),
        discount,
    )
    drop = base.npv_borrower_cost - up.npv_borrower_cost
    lift = down.npv_borrower_cost - base.npv_borrower_cost
    # For small ±25 bp asymmetry is < 5%.
    assert abs(lift - drop) / ((lift + drop) / 2) < 0.05


# ──────────────────────────────────────────────────────────────────────
# Acceptance criterion 3: regression test pins outputs to seeded inputs
# ──────────────────────────────────────────────────────────────────────


# Values pinned from a deterministic run on the Q1.1 RCF fixture. Any
# change here means the curve-shock math drifted — investigate before
# updating the pins.
_REGRESSION_NPVS = {
    "base": 2426729.8983258074,
    "parallel_-100": 2488499.382758991,
    "parallel_+100": 2367490.348985242,
    "steepening_-50_to_+100": 2426918.7399653504,
    "curvature_+50_at_2_5y": 2418421.6886915816,
    "cut_path_-200bp_18m": 2545578.9276915616,
    "parallel_-100_engine_rfr": 2488499.382758991,
}
_REGRESSION_RAROCS = {
    "base": 0.0773946903250509,
    "parallel_-100_engine_rfr": 0.0698946903250509,
}


def test_regression_pins_npv_across_canonical_shocks():
    """All five canonical shocks reproduce their pinned NPV borrower cost."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    base = runner.run_base(deal, schedule, discount)
    assert base.npv_borrower_cost == pytest.approx(
        _REGRESSION_NPVS["base"], rel=1e-9
    )

    shocks = [
        ("parallel_-100", ParallelShock(-100)),
        ("parallel_+100", ParallelShock(100)),
        ("steepening_-50_to_+100", SteepeningShock(-50, 100)),
        ("curvature_+50_at_2_5y", CurvatureShock(50, 2.5, 1.5)),
        ("cut_path_-200bp_18m", CutPathShock(cuts=(
            (0.5, -50), (1.0, -100), (1.5, -200),
        ))),
    ]
    for label, shock in shocks:
        run = runner.run_scenario(
            deal, schedule,
            Scenario(label, [CurveShockMod(shock=shock)]),
            discount,
        )
        assert run.npv_borrower_cost == pytest.approx(
            _REGRESSION_NPVS[label], rel=1e-9
        ), f"NPV regression drift for {label}"


def test_regression_pins_raroc_under_engine_rate_shock():
    """RAROC pin when affect_engine_rate=True: -100bp ⇒ -75bp after-tax drop."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    base = runner.run_base(deal, schedule, discount)
    assert base.capital_weighted_raroc == pytest.approx(
        _REGRESSION_RAROCS["base"], abs=1e-9
    )
    run = runner.run_scenario(
        deal, schedule,
        Scenario("engine", [CurveShockMod(
            shock=ParallelShock(-100),
            affect_engine_rate=True,
        )]),
        discount,
    )
    assert run.capital_weighted_raroc == pytest.approx(
        _REGRESSION_RAROCS["parallel_-100_engine_rfr"], abs=1e-9
    )


def test_regression_per_period_dfs_match_analytic_formula():
    """Per-period DFs under a parallel shock satisfy DF_i = (1 + r + δ)^(-t_i)."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    delta_bp = -100.0
    delta = delta_bp / 10000.0
    run = runner.run_scenario(
        deal, schedule,
        Scenario("p", [CurveShockMod(shock=ParallelShock(delta_bp))]),
        discount,
    )
    rate = float(discount.rate)
    for i, row in enumerate(run.per_period, start=1):
        expected = (1.0 + rate + delta) ** (-float(i))
        assert row.df == pytest.approx(expected, rel=1e-12), (
            f"Period {i}: expected DF {expected}, got {row.df}"
        )


# ──────────────────────────────────────────────────────────────────────
# Steepening / curvature shapes — directional behaviour
# ──────────────────────────────────────────────────────────────────────


def test_steepening_affects_long_periods_more_than_short():
    """Short-rate floor at 0 / long-rate +100 ⇒ later DFs drop more than early ones."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    base = runner.run_base(deal, schedule, discount)
    run = runner.run_scenario(
        deal, schedule,
        Scenario(
            "steep",
            [CurveShockMod(shock=SteepeningShock(0, 100, long_anchor_years=10))],
        ),
        discount,
    )
    # Period 1: shock at t=1 → 10bp.
    # Period 5: shock at t=5 → 50bp.
    # The relative DF drop should grow with t.
    rel_drops = [
        (b.df - r.df) / b.df for b, r in zip(base.per_period, run.per_period)
    ]
    # Strictly monotonic increase in the relative drop.
    for a, b in zip(rel_drops, rel_drops[1:]):
        assert a < b


def test_curvature_only_affects_periods_inside_the_window():
    """Bump at t=2.5y, half-width 1y → periods 1 and 5 untouched, 2/3 hit, 4 borderline."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    base = runner.run_base(deal, schedule, discount)
    # Window: [1.5, 3.5]; periods 2 (t_end=2) and 3 (t_end=3) inside.
    shock = CurvatureShock(peak_shift_bps=80, peak_years=2.5, half_width_years=1.0)
    run = runner.run_scenario(
        deal, schedule,
        Scenario("bump", [CurveShockMod(shock=shock)]),
        discount,
    )
    # Period 1 (t=1.0): outside the window → DF unchanged.
    assert run.per_period[0].df == pytest.approx(base.per_period[0].df, abs=1e-12)
    # Period 5 (t=5.0): outside the window → DF unchanged.
    assert run.per_period[4].df == pytest.approx(base.per_period[4].df, abs=1e-12)
    # Periods 2 & 3: inside the window → DF lower (positive shock).
    assert run.per_period[1].df < base.per_period[1].df
    assert run.per_period[2].df < base.per_period[2].df


def test_cut_path_200bp_18m_creates_largest_npv_lift():
    """The task-brief stress: -200bp cumulative cut → biggest NPV lift among shocks."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    base = runner.run_base(deal, schedule, discount)
    shocks = [
        ("parallel_-50", ParallelShock(-50)),
        ("parallel_-100", ParallelShock(-100)),
        ("cut_path_-200_18m", CutPathShock(cuts=(
            (0.5, -50), (1.0, -100), (1.5, -200),
        ))),
    ]
    lifts = []
    for label, shock in shocks:
        run = runner.run_scenario(
            deal, schedule,
            Scenario(label, [CurveShockMod(shock=shock)]),
            discount,
        )
        lifts.append(run.npv_borrower_cost - base.npv_borrower_cost)
    # All three lift NPV; cut path -200 lifts the most.
    assert all(l > 0 for l in lifts)
    assert lifts[2] > lifts[1] > lifts[0]


# ──────────────────────────────────────────────────────────────────────
# Floating fixings under a shock
# ──────────────────────────────────────────────────────────────────────


def test_floating_fixings_shift_under_parallel_shock_when_pinned():
    """Pinned floating fixings shift by shock(t_period_start)."""
    cfg = EngineConfig(funding_cost_bp=0.0)
    deal = RAROCInput(
        product_type="mlt_credit",
        rating="Baa2",
        spread=0.012,
        commitment_fee=0.0025,
        global_grr=0.0,
        confirmed=True,
    )
    schedule = Schedule.bullet_rcf_with_cleandown(
        commitment=20_000_000,
        drawn_levels=[(15_000_000, 3)],
        start=date(2026, 6, 1),
        floating_index="EURIBOR_3M",
    )
    for p in schedule.periods:
        p.fixing_rate = 0.030

    runner = ScenarioRunner(config=cfg)
    run = runner.run_scenario(
        deal, schedule,
        Scenario("p", [CurveShockMod(shock=ParallelShock(50))]),
        DiscountSpec(kind="scalar", rate=0.0325),
    )
    for row in run.per_period:
        assert row.fixing_rate == pytest.approx(0.030 + 0.005, abs=1e-12)


def test_floating_fixings_under_steepening_shock_vary_by_period():
    """Pinned fixings shift by different amounts under a non-parallel shock."""
    cfg = EngineConfig(funding_cost_bp=0.0)
    deal = RAROCInput(
        product_type="mlt_credit",
        rating="Baa2",
        spread=0.012,
        commitment_fee=0.0025,
        global_grr=0.0,
        confirmed=True,
    )
    schedule = Schedule.bullet_rcf_with_cleandown(
        commitment=20_000_000,
        drawn_levels=[(15_000_000, 5)],
        start=date(2026, 6, 1),
        floating_index="EURIBOR_3M",
    )
    for p in schedule.periods:
        p.fixing_rate = 0.030

    shock = SteepeningShock(short_shift_bps=0, long_shift_bps=100, long_anchor_years=10)
    runner = ScenarioRunner(config=cfg)
    run = runner.run_scenario(
        deal, schedule,
        Scenario("s", [CurveShockMod(shock=shock)]),
        DiscountSpec(kind="scalar", rate=0.0325),
    )
    # Each period's fixing should be 0.030 + shock(t_period_start) / 10000.
    # Period 1 start at t=0.0 → +0 bp. Period 5 start at t=4.0 → +40 bp.
    expected = [0.030, 0.033, 0.0340, 0.0350, 0.0360]
    for i, row in enumerate(run.per_period):
        # Period 1 fixing = 0.030 + 0/10000 = 0.0300
        # Period 2 fixing = 0.030 + 10/10000 = 0.0310
        # Period 3 fixing = 0.030 + 20/10000 = 0.0320
        # Period 4 fixing = 0.030 + 30/10000 = 0.0330
        # Period 5 fixing = 0.030 + 40/10000 = 0.0340
        expected_i = 0.030 + (i * 10) / 10000
        assert row.fixing_rate == pytest.approx(expected_i, abs=1e-12), (
            f"Period {i+1}: expected {expected_i}, got {row.fixing_rate}"
        )


def test_floating_fixings_not_shifted_when_flag_off():
    """affect_floating_fixings=False leaves pre-pinned fixings untouched."""
    cfg = EngineConfig(funding_cost_bp=0.0)
    deal = RAROCInput(
        product_type="mlt_credit",
        rating="Baa2",
        spread=0.012,
        commitment_fee=0.0025,
        global_grr=0.0,
        confirmed=True,
    )
    schedule = Schedule.bullet_rcf_with_cleandown(
        commitment=20_000_000,
        drawn_levels=[(15_000_000, 3)],
        start=date(2026, 6, 1),
        floating_index="EURIBOR_3M",
    )
    for p in schedule.periods:
        p.fixing_rate = 0.030

    runner = ScenarioRunner(config=cfg)
    run = runner.run_scenario(
        deal, schedule,
        Scenario("p", [CurveShockMod(
            shock=ParallelShock(50),
            affect_floating_fixings=False,
        )]),
        DiscountSpec(kind="scalar", rate=0.0325),
    )
    for row in run.per_period:
        assert row.fixing_rate == pytest.approx(0.030, abs=1e-12)


# ──────────────────────────────────────────────────────────────────────
# Multi-segment scenarios (compose with RefinanceMod)
# ──────────────────────────────────────────────────────────────────────


def test_shock_after_refi_applies_on_global_timeline():
    """RefinanceMod splits into 2 segments; shock evaluated at GLOBAL t_end_years."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    # Steepening: short=0 long=+100 over 10y → at t=5 shock is +50 bp.
    shock = SteepeningShock(short_shift_bps=0, long_shift_bps=100, long_anchor_years=10)
    scenario = Scenario("refi+shock", [
        RefinanceMod(at_year=2, new_spread=0.010),
        CurveShockMod(shock=shock),
    ])
    run = runner.run_scenario(deal, schedule, scenario, discount)

    # Per-period DFs should follow base_rate + shock(global_t).
    base_rate = float(discount.rate)
    for row in run.per_period:
        t = row.t_end_years
        expected_rate = base_rate + shock.shock_decimal(t)
        expected_df = (1.0 + expected_rate) ** (-t)
        assert row.df == pytest.approx(expected_df, rel=1e-12)


def test_shock_before_refi_segments_share_consistent_shocked_discount():
    """Curve shock applied first; refi splits into 2 segments using shocked discount."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    shock = ParallelShock(50)
    # Shock first, then refi — the refi inherits the shocked discount on both segments.
    scenario = Scenario("shock+refi", [
        CurveShockMod(shock=shock),
        RefinanceMod(at_year=2, new_spread=0.010),
    ])
    run = runner.run_scenario(deal, schedule, scenario, discount)

    expected_rate = float(discount.rate) + shock.shock_decimal(0)
    for row in run.per_period:
        expected_df = (1.0 + expected_rate) ** (-row.t_end_years)
        assert row.df == pytest.approx(expected_df, rel=1e-12)


# ──────────────────────────────────────────────────────────────────────
# Distribution helper
# ──────────────────────────────────────────────────────────────────────


def test_simulate_curve_distribution_returns_one_run_per_shock():
    cfg, deal, schedule, discount, _ = make_inputs()
    shocks = [
        ("parallel_+100", ParallelShock(100)),
        ("parallel_-100", ParallelShock(-100)),
        ("steepening", SteepeningShock(-50, 100)),
    ]
    dist = simulate_curve_distribution(
        deal, schedule, shocks, discount=discount, config=cfg,
    )
    assert isinstance(dist, ScenarioDistribution)
    assert len(dist.runs) == 3
    assert dist.labels == ["parallel_+100", "parallel_-100", "steepening"]
    assert dist.base.name == "base"


def test_distribution_worst_case_is_largest_npv_borrower_cost():
    """Worst case for the borrower = highest NPV cost; -200bp shock dominates."""
    cfg, deal, schedule, discount, _ = make_inputs()
    shocks = [
        ("parallel_+100", ParallelShock(100)),
        ("parallel_-100", ParallelShock(-100)),
        ("cut_path_-200_18m", CutPathShock(cuts=(
            (0.5, -50), (1.0, -100), (1.5, -200),
        ))),
    ]
    dist = simulate_curve_distribution(
        deal, schedule, shocks, discount=discount, config=cfg,
    )
    label, value = dist.worst_case("npv_borrower_cost", side="high")
    assert label == "cut_path_-200_18m"
    assert value == max(dist.values("npv_borrower_cost"))


def test_distribution_best_case_for_borrower_is_lowest_npv():
    """Best case for borrower = lowest NPV cost; +100bp dominates."""
    cfg, deal, schedule, discount, _ = make_inputs()
    shocks = [
        ("parallel_+100", ParallelShock(100)),
        ("parallel_-100", ParallelShock(-100)),
        ("steep", SteepeningShock(-50, 100)),
    ]
    dist = simulate_curve_distribution(
        deal, schedule, shocks, discount=discount, config=cfg,
    )
    label, value = dist.best_case("npv_borrower_cost", side="low")
    assert label == "parallel_+100"
    assert value == min(dist.values("npv_borrower_cost"))


def test_distribution_percentile_matches_numpy_method_linear():
    """percentile(q) interpolates linearly between sorted values."""
    cfg, deal, schedule, discount, _ = make_inputs()
    shocks = [
        ("a", ParallelShock(-50)),
        ("b", ParallelShock(-25)),
        ("c", ParallelShock(0)),
        ("d", ParallelShock(25)),
        ("e", ParallelShock(50)),
    ]
    dist = simulate_curve_distribution(
        deal, schedule, shocks, discount=discount, config=cfg,
    )
    vals = sorted(dist.values("npv_borrower_cost"))
    # P50 is the middle of 5 sorted values.
    assert dist.percentile(50.0) == pytest.approx(vals[2], abs=1e-9)
    # P0 = min, P100 = max.
    assert dist.percentile(0.0) == pytest.approx(vals[0], abs=1e-9)
    assert dist.percentile(100.0) == pytest.approx(vals[-1], abs=1e-9)


def test_distribution_to_table_includes_base_and_summary():
    cfg, deal, schedule, discount, _ = make_inputs()
    shocks = [
        ("parallel_+100", ParallelShock(100)),
        ("parallel_-100", ParallelShock(-100)),
    ]
    dist = simulate_curve_distribution(
        deal, schedule, shocks, discount=discount, config=cfg,
    )
    table = dist.to_table()
    assert table["base_name"] == "base"
    assert len(table["rows"]) == 3  # base + 2 shocks
    assert table["rows"][0]["is_base"] is True
    assert table["rows"][1]["label"] == "parallel_+100"
    assert table["rows"][1]["shock"] == "parallel +100bp"
    summary = table["summary"]
    assert summary["npv_borrower_cost_min"] <= summary["npv_borrower_cost_p25"]
    assert summary["npv_borrower_cost_p25"] <= summary["npv_borrower_cost_p50"]
    assert summary["npv_borrower_cost_p50"] <= summary["npv_borrower_cost_p75"]
    assert summary["npv_borrower_cost_p75"] <= summary["npv_borrower_cost_max"]


def test_distribution_values_with_base_first():
    cfg, deal, schedule, discount, _ = make_inputs()
    shocks = [("p", ParallelShock(100))]
    dist = simulate_curve_distribution(
        deal, schedule, shocks, discount=discount, config=cfg,
    )
    with_base = dist.values_with_base("npv_borrower_cost")
    without_base = dist.values("npv_borrower_cost")
    assert with_base[0] == pytest.approx(dist.base.npv_borrower_cost, abs=1e-12)
    assert with_base[1:] == without_base


def test_distribution_unknown_metric_raises():
    cfg, deal, schedule, discount, _ = make_inputs()
    dist = simulate_curve_distribution(
        deal, schedule, [("p", ParallelShock(0))], discount=discount, config=cfg,
    )
    with pytest.raises(ValueError, match="Unknown metric"):
        dist.values("not_a_metric")


# ──────────────────────────────────────────────────────────────────────
# Reproducibility + no-mutation invariants
# ──────────────────────────────────────────────────────────────────────


def test_curve_shock_runs_are_reproducible():
    """Identical inputs → identical engine outputs across runs."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner_a = ScenarioRunner(config=cfg)
    runner_b = ScenarioRunner(config=cfg)
    shock = compose_shocks(
        ParallelShock(-25),
        SteepeningShock(short_shift_bps=10, long_shift_bps=50),
        CurvatureShock(peak_shift_bps=15, peak_years=3.0, half_width_years=1.5),
    )
    a = runner_a.run_scenario(
        deal, schedule,
        Scenario("multi", [CurveShockMod(shock=shock)]),
        discount,
    )
    b = runner_b.run_scenario(
        deal, schedule,
        Scenario("multi", [CurveShockMod(shock=shock)]),
        discount,
    )
    assert a.npv_borrower_cost == pytest.approx(b.npv_borrower_cost, abs=1e-12)
    for x, y in zip(a.per_period, b.per_period):
        assert x.df == pytest.approx(y.df, abs=1e-15)


def test_curve_shock_does_not_mutate_caller_inputs():
    """Runner deepcopies internally; caller objects survive intact."""
    import copy as _copy
    cfg, deal, schedule, discount, _ = make_inputs()

    deal_snapshot = _copy.deepcopy(deal)
    schedule_snapshot = _copy.deepcopy(schedule)
    discount_snapshot = _copy.deepcopy(discount)

    runner = ScenarioRunner(config=cfg)
    runner.run_scenario(
        deal, schedule,
        Scenario("p", [CurveShockMod(shock=ParallelShock(-100))]),
        discount,
    )

    assert deal == deal_snapshot
    assert discount == discount_snapshot
    assert schedule.to_dict() == schedule_snapshot.to_dict()


def test_describe_chains_through_composite():
    """A composite shock's describe() lists each component."""
    shock = compose_shocks(
        ParallelShock(50),
        SteepeningShock(0, 100),
        CurvatureShock(25, 3.0, 1.0),
    )
    desc = shock.describe()
    assert "parallel" in desc
    assert "steepening" in desc
    assert "curvature" in desc


# ──────────────────────────────────────────────────────────────────────
# Engine vocabulary preserved — no shadowed names
# ──────────────────────────────────────────────────────────────────────


def test_curve_shock_mod_is_a_scenario_mod():
    """CurveShockMod plugs into Scenario.mods without subclass surgery."""
    from raroc_engine.scenarios import ScenarioMod
    assert issubclass(CurveShockMod, ScenarioMod)


def test_all_shocks_are_forward_curve_shocks():
    for cls in (
        ParallelShock,
        SteepeningShock,
        FlatteningShock,
        CurvatureShock,
        CutPathShock,
        CompositeShock,
        ScaledShock,
    ):
        assert issubclass(cls, ForwardCurveShock)


def test_curve_shock_mod_with_period_engine_directly_matches_runner():
    """Sanity: CurveShockMod-produced discount round-trips through PeriodEngine."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    shock = ParallelShock(-50)
    run = runner.run_scenario(
        deal, schedule,
        Scenario("p", [CurveShockMod(shock=shock)]),
        discount,
    )
    # Compute a direct equivalent: build the schedule-shape DiscountSpec
    # the mod would have built and run PeriodEngine.run directly.
    shocked_points = []
    for i, p in enumerate(schedule.periods, start=1):
        shocked_points.append((p.end, float(discount.rate) + shock.shock_decimal(float(i))))
    direct_discount = DiscountSpec(
        kind="schedule",
        rate=float(discount.rate),
        points=shocked_points,
        day_count=discount.day_count,
    )
    direct = PeriodEngine(config=cfg).run(deal, schedule, direct_discount)
    for a, b in zip(run.per_period, direct.per_period):
        assert a.df == pytest.approx(b.df, abs=1e-15)
        assert a.revenue_pv == pytest.approx(b.revenue_pv, rel=1e-12)
