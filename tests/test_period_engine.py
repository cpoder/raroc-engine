"""Tests for raroc_engine.period_engine.

Acceptance criterion (PLAN Task 1.3): per-period outputs match the Q1.1
Excel fixtures within 0.5 bp on per-period RAROC. Tolerances are
declared on each fixture (``tests/fixtures/period_*.yaml`` →
``tolerances`` block) and re-stated in
``docs/engine/multiperiod-spec.md`` §10.

Also exercises the spec §9 back-compat hinge: a length-1 schedule with
dt=1.0 reproduces the existing ``RAROCCalculator.calculate`` output to
within 1e-12 on every field.
"""

from __future__ import annotations

import os
from datetime import date

import pytest
import yaml

from raroc_engine import (
    DiscountSpec,
    PeriodEngine,
    PeriodOutput,
    Schedule,
)
from raroc_engine.calculator import RAROCCalculator
from raroc_engine.config import EngineConfig
from raroc_engine.models import RAROCInput


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
START = date(2026, 6, 1)
FIXTURE_NAMES = [
    "period_rcf_5y",
    "period_termloan_7y_amortising",
    "period_projfin_10y_grace",
]


def load_fixture(name: str) -> dict:
    with open(os.path.join(FIXTURES_DIR, f"{name}.yaml")) as f:
        return yaml.safe_load(f)


def make_engine_config(d: dict) -> EngineConfig:
    """Build an EngineConfig from a fixture's engine_config block."""
    return EngineConfig.from_dict(d)


def make_raroc_input(deal: dict) -> RAROCInput:
    """Build the static RAROCInput from a fixture's deal block.

    Period-specific volumes are filled in by the engine per row; here we
    pass zeros for volumes since the engine reads them from the Schedule.
    """
    return RAROCInput(
        product_type=deal["product_type"],
        rating=deal["rating"],
        global_grr=float(deal.get("global_grr", 0.0)),
        confirmed=bool(deal.get("confirmed", True)),
        spread=float(deal.get("spread", 0.0)),
        commitment_fee=float(deal.get("commitment_fee", 0.0)),
    )


def make_discount(d: dict) -> DiscountSpec:
    return DiscountSpec(
        kind=d.get("kind", "scalar"),
        rate=float(d.get("rate", 0.0325)),
        day_count=d.get("day_count", "Act/365F"),
    )


# ──────────────────────────────────────────────────────────────────────
# Fixture-driven per-period + aggregate conformance
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_fixture_per_period_within_tolerance(fixture_name: str):
    """Per-period outputs match the fixture cells within declared tolerances."""
    fx = load_fixture(fixture_name)
    cfg = make_engine_config(fx["engine_config"])
    deal = make_raroc_input(fx["deal"])
    schedule = Schedule.from_dict(fx["schedule"])
    discount = make_discount(fx["discount"])
    tol = fx["tolerances"]

    engine = PeriodEngine(config=cfg)
    out = engine.run(deal, schedule, discount)

    assert len(out.per_period) == len(fx["expected"]["per_period"]), (
        f"period count mismatch: engine={len(out.per_period)} "
        f"fixture={len(fx['expected']['per_period'])}"
    )

    raroc_bp_abs = float(tol["per_period_raroc_bp_abs"])
    fpe_rel = float(tol["per_period_fpe_rel"])

    for actual, expected in zip(out.per_period, fx["expected"]["per_period"]):
        idx = expected["index"]

        # Volumes / metadata (exact)
        assert actual.index == expected["index"]
        assert actual.dt_years == pytest.approx(1.0)

        # Per-period RAROC: 0.5 bp absolute (the headline tolerance).
        assert abs(actual.raroc_bp - float(expected["raroc_bp"])) <= raroc_bp_abs, (
            f"[{fixture_name} p{idx}] RAROC bp drift "
            f"{actual.raroc_bp:.4f} vs {expected['raroc_bp']:.4f} "
            f"> {raroc_bp_abs} bp"
        )

        # Per-period FPE: 0.5% relative
        assert actual.fpe == pytest.approx(
            float(expected["fpe"]), rel=fpe_rel
        ), f"[{fixture_name} p{idx}] FPE drift"

        # Other per-period fields — same family of tolerances, kept tight
        # because the math is reused from the same calculator.
        assert actual.revenue == pytest.approx(float(expected["revenue"]), rel=1e-9)
        assert actual.cost == pytest.approx(float(expected["cost"]), rel=1e-9)
        assert actual.funding_cost == pytest.approx(
            float(expected["funding_cost"]), abs=1e-9
        )
        assert actual.exposure == pytest.approx(
            float(expected["exposure"]), rel=1e-12
        )
        assert actual.pd == pytest.approx(float(expected["pd"]), rel=1e-10)
        assert actual.pd_basel2 == pytest.approx(
            float(expected["pd_basel2"]), rel=1e-10
        )
        assert actual.lgd == pytest.approx(float(expected["lgd"]), rel=1e-10)
        assert actual.correlation == pytest.approx(
            float(expected["correlation_R"]), rel=1e-9
        )
        assert actual.maturity_adj_b == pytest.approx(
            float(expected["maturity_adj_b"]), rel=1e-9
        )
        assert actual.z == pytest.approx(float(expected["z"]), rel=1e-7, abs=1e-9)
        assert actual.K_irb == pytest.approx(float(expected["K_irb"]), rel=1e-7)
        assert actual.sa_rw == pytest.approx(float(expected["sa_rw"]), abs=1e-12)
        assert actual.K_floor == pytest.approx(
            float(expected["K_floor"]), rel=1e-9
        )
        assert actual.K == pytest.approx(float(expected["K"]), rel=1e-7)
        assert actual.el == pytest.approx(float(expected["el"]), rel=1e-9)
        assert actual.gross_margin == pytest.approx(
            float(expected["gross_margin"]), rel=1e-9
        )
        assert actual.fpe_return == pytest.approx(
            float(expected["fpe_return"]), rel=fpe_rel
        )
        assert actual.net_margin == pytest.approx(
            float(expected["net_margin"]), rel=fpe_rel
        )
        # Discount layer
        assert actual.t_end_years == pytest.approx(
            float(expected["t_end_years"]), abs=1e-12
        )
        assert actual.df == pytest.approx(float(expected["df"]), rel=1e-9)
        assert actual.revenue_pv == pytest.approx(
            float(expected["revenue_pv"]), rel=1e-7
        )
        assert actual.net_margin_pv == pytest.approx(
            float(expected["net_margin_pv"]), rel=fpe_rel
        )
        assert actual.drawn_pv == pytest.approx(
            float(expected["drawn_pv"]), rel=1e-7
        )


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_fixture_aggregates_within_tolerance(fixture_name: str):
    """§7 aggregates match the fixture's expected aggregates within tolerance."""
    fx = load_fixture(fixture_name)
    cfg = make_engine_config(fx["engine_config"])
    deal = make_raroc_input(fx["deal"])
    schedule = Schedule.from_dict(fx["schedule"])
    discount = make_discount(fx["discount"])
    tol = fx["tolerances"]

    engine = PeriodEngine(config=cfg)
    out = engine.run(deal, schedule, discount)

    expected = fx["expected"]["aggregates"]
    npv_rel = float(tol["npv_rel"])
    spread_bp_abs = float(tol["effective_spread_bp_abs"])

    assert out.aggregates["npv_borrower_cost"] == pytest.approx(
        float(expected["npv_borrower_cost"]), rel=npv_rel
    )
    assert out.aggregates["npv_bank_net_margin"] == pytest.approx(
        float(expected["npv_bank_net_margin"]), rel=npv_rel
    )
    assert out.aggregates["npv_drawn_balance"] == pytest.approx(
        float(expected["npv_drawn_balance"]), rel=npv_rel
    )
    assert abs(
        out.aggregates["effective_spread_bp"]
        - float(expected["effective_spread_bp"])
    ) <= spread_bp_abs, (
        f"[{fixture_name}] effective spread drift "
        f"{out.aggregates['effective_spread_bp']:.4f} vs "
        f"{expected['effective_spread_bp']:.4f}"
    )
    # FPE-weighted RAROC — same 0.5 bp tolerance as per-period RAROC.
    raroc_bp_abs = float(tol["per_period_raroc_bp_abs"])
    assert abs(
        out.aggregates["fpe_weighted_raroc"] * 10000.0
        - float(expected["fpe_weighted_raroc"]) * 10000.0
    ) <= raroc_bp_abs, (
        f"[{fixture_name}] FPE-weighted RAROC drift "
        f"{out.aggregates['fpe_weighted_raroc']:.6f} vs "
        f"{expected['fpe_weighted_raroc']:.6f}"
    )
    assert out.aggregates["total_revenue_undisc"] == pytest.approx(
        float(expected["total_revenue_undisc"]), rel=1e-9
    )
    assert out.aggregates["total_el_undisc"] == pytest.approx(
        float(expected["total_el_undisc"]), rel=1e-9
    )
    assert out.aggregates["avg_exposure"] == pytest.approx(
        float(expected["avg_exposure"]), rel=1e-9
    )

    # Discount meta carries the D-0003 cascade flag.
    assert out.discount_meta["curve_status"] == expected.get(
        "curve_status", fx["expected"]["discount_meta"]["curve_status"]
    ) or out.discount_meta["curve_status"] == "scalar"


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_fixture_capital_release_sums_to_initial_commitment(fixture_name: str):
    """Capital release: total principal repaid must equal the initial commitment.

    For a 50M RCF, principal flows back as cleandown reduces the drawn balance
    *only when the commitment itself amortises*; for a constant-commitment RCF
    all 50M flows back at maturity. For an amortising loan, it flows back step
    by step. Either way, the sum is the full initial commitment.
    """
    fx = load_fixture(fixture_name)
    cfg = make_engine_config(fx["engine_config"])
    deal = make_raroc_input(fx["deal"])
    schedule = Schedule.from_dict(fx["schedule"])
    discount = make_discount(fx["discount"])
    engine = PeriodEngine(config=cfg)
    out = engine.run(deal, schedule, discount)

    total_repayment = sum(r.principal_repayment for r in out.per_period)
    initial_commitment = schedule.periods[0].commitment
    assert total_repayment == pytest.approx(initial_commitment, rel=1e-12)


# ──────────────────────────────────────────────────────────────────────
# Single-period back-compat (spec §9)
# ──────────────────────────────────────────────────────────────────────


def test_single_period_parity_to_existing_calculator():
    """A length-1 schedule, dt=1.0, reproduces RAROCCalculator output to 1e-12.

    This is the spec §9 contract that OpenRAROC's public single-period API
    depends on — any regression here means the engine has drifted.
    """
    inp = RAROCInput(
        product_type="mlt_credit",
        average_volume=50_000_000,
        average_drawn=35_000_000,
        initial_maturity=60,
        residual_maturity=60,
        spread=0.015,
        commitment_fee=0.0025,
        upfront_fee=200_000,
        global_grr=0.0,
        confirmed=True,
        rating="Baa2",
    )
    cfg = EngineConfig()
    calc_out = RAROCCalculator(config=cfg).calculate(inp)

    schedule = Schedule.from_raroc_input(inp, start=START)
    deal = RAROCInput(
        product_type=inp.product_type,
        rating=inp.rating,
        global_grr=inp.global_grr,
        confirmed=inp.confirmed,
        spread=inp.spread,
        commitment_fee=inp.commitment_fee,
    )
    engine_out = PeriodEngine(config=cfg).run(deal, schedule)

    row: PeriodOutput = engine_out.per_period[0]
    abs_tol = 1e-12

    assert row.revenue == pytest.approx(calc_out.revenue, abs=abs_tol)
    assert row.cost == pytest.approx(calc_out.cost, abs=abs_tol)
    assert row.exposure == pytest.approx(calc_out.exposure, abs=abs_tol)
    assert row.pd == pytest.approx(calc_out.pd, abs=abs_tol)
    assert row.pd_basel2 == pytest.approx(calc_out.pd_basel2, abs=abs_tol)
    assert row.correlation == pytest.approx(calc_out.correlation, abs=abs_tol)
    assert row.maturity_adj_b == pytest.approx(
        calc_out.maturity_adj_b, abs=abs_tol
    )
    assert row.K == pytest.approx(calc_out.risk_weight, abs=abs_tol)
    assert row.fpe == pytest.approx(calc_out.fpe, abs=abs_tol)
    assert row.el == pytest.approx(calc_out.average_loss, abs=abs_tol)
    assert row.gross_margin == pytest.approx(calc_out.gross_margin, abs=abs_tol)
    assert row.fpe_return == pytest.approx(calc_out.revenues_of_fpe, abs=abs_tol)
    assert row.net_margin == pytest.approx(calc_out.net_margin, abs=abs_tol)
    assert row.raroc == pytest.approx(calc_out.raroc, abs=abs_tol)


def test_engine_handles_missing_discount_with_config_default():
    """When no DiscountSpec is supplied, fall back to EngineConfig.risk_free_rate."""
    cfg = EngineConfig(risk_free_rate=0.04)
    inp = RAROCInput(
        product_type="mlt_credit",
        spread=0.015,
        commitment_fee=0.0025,
        rating="Baa2",
        global_grr=0.0,
        confirmed=True,
    )
    schedule = Schedule.bullet_rcf_with_cleandown(
        commitment=10_000_000,
        drawn_levels=[(8_000_000, 2)],
        start=START,
    )
    engine = PeriodEngine(config=cfg)
    out = engine.run(inp, schedule)

    assert out.discount_meta["curve_status"] == "scalar"
    assert out.discount_meta["rate_used"] == pytest.approx(0.04)
    # DF for period 1: (1.04)^-1 ≈ 0.96154
    assert out.per_period[0].df == pytest.approx(1.0 / 1.04, rel=1e-12)
    # DF for period 2: (1.04)^-2
    assert out.per_period[1].df == pytest.approx(1.0 / (1.04 ** 2), rel=1e-12)


def test_engine_meta_has_useful_provenance():
    """``engine_meta`` should carry enough to identify a run downstream."""
    fx = load_fixture("period_rcf_5y")
    cfg = make_engine_config(fx["engine_config"])
    deal = make_raroc_input(fx["deal"])
    schedule = Schedule.from_dict(fx["schedule"])
    discount = make_discount(fx["discount"])

    out = PeriodEngine(config=cfg).run(deal, schedule, discount)
    assert out.engine_meta["regime"] == "basel3"
    assert out.engine_meta["n_periods"] == 5
    assert out.engine_meta["total_years"] == pytest.approx(5.0)
    assert out.engine_meta["rating"] == "Baa2"
    assert "engine_version" in out.engine_meta


# ──────────────────────────────────────────────────────────────────────
# DiscountSpec interpolation
# ──────────────────────────────────────────────────────────────────────


def test_discount_spec_schedule_interpolates_linearly():
    """Schedule-shape discount spec linearly interpolates between dated points."""
    spec = DiscountSpec(
        kind="schedule",
        points=[(date(2026, 1, 1), 0.03), (date(2031, 1, 1), 0.05)],
    )
    # Half-way (mid-2028): rate should be ~0.04
    mid = date(2028, 7, 2)  # roughly halfway through the 5-year span
    rate = spec.rate_at(t_years=2.5, period_end=mid)
    assert 0.039 < rate < 0.041


def test_discount_spec_scalar_returns_fixed_rate():
    spec = DiscountSpec(kind="scalar", rate=0.045)
    assert spec.rate_at(t_years=3.7) == pytest.approx(0.045)
    assert spec.curve_status() == "scalar"
