"""Tests for raroc_engine.aggregate.

Acceptance criteria (PLAN Task 1.4):

1. **NPV within 0.1%** of the Q1.1 Excel fixtures (``tests/fixtures/period_*.yaml``).
2. **Effective spread monotonic in input spread** — raising the deal spread
   strictly raises the aggregate ``effective_spread``.
3. **Capital-weighted RAROC matches single-period behaviour for 1y bullet
   facilities** — a length-1, dt=1.0 schedule yields
   ``capital_weighted_raroc == per_period[0].raroc`` exactly.

Plus a handful of supporting checks (back-compat dict layout, identities
between PV/undiscounted bank costs, ``attach_discount_factors`` round-trip,
empty-list safety, weighting collapse behaviour).
"""

from __future__ import annotations

import os
from datetime import date

import pytest
import yaml

from raroc_engine import (
    DiscountSpec,
    FacilityAggregates,
    PeriodEngine,
    Schedule,
    aggregate_periods,
    attach_discount_factors,
)
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
    return EngineConfig.from_dict(d)


def make_deal(deal: dict) -> RAROCInput:
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


def run_fixture(name: str):
    """Build engine output + aggregates for a fixture in one call."""
    fx = load_fixture(name)
    cfg = make_engine_config(fx["engine_config"])
    deal = make_deal(fx["deal"])
    schedule = Schedule.from_dict(fx["schedule"])
    discount = make_discount(fx["discount"])

    out = PeriodEngine(config=cfg).run(deal, schedule, discount)
    agg = aggregate_periods(out.per_period)
    return fx, out, agg


# ──────────────────────────────────────────────────────────────────────
# Acceptance criterion 1: NPV within 0.1% of Excel fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_npv_within_excel_fixture_tolerance(fixture_name: str):
    """All NPV aggregates land within the fixture's declared NPV tolerance.

    Acceptance: 0.1% relative on every NPV total (spec §10).
    """
    fx, out, agg = run_fixture(fixture_name)
    expected = fx["expected"]["aggregates"]
    npv_rel = float(fx["tolerances"]["npv_rel"])  # 0.001 = 0.1%

    assert agg.npv_borrower_cost == pytest.approx(
        float(expected["npv_borrower_cost"]), rel=npv_rel
    )
    assert agg.npv_bank_net_margin == pytest.approx(
        float(expected["npv_bank_net_margin"]), rel=npv_rel
    )
    assert agg.npv_drawn_balance == pytest.approx(
        float(expected["npv_drawn_balance"]), rel=npv_rel
    )


# ──────────────────────────────────────────────────────────────────────
# Acceptance criterion 2: effective spread monotonic in input spread
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_effective_spread_is_monotonic_in_input_spread(fixture_name: str):
    """A higher deal spread must produce a strictly higher effective spread.

    The PV of revenue grows linearly in spread (drawn_pv is unchanged), so
    effective_spread = revenue_pv / drawn_pv inherits monotonicity.
    """
    fx = load_fixture(fixture_name)
    cfg = make_engine_config(fx["engine_config"])
    deal = make_deal(fx["deal"])
    schedule = Schedule.from_dict(fx["schedule"])
    discount = make_discount(fx["discount"])
    engine = PeriodEngine(config=cfg)

    spreads = [0.005, 0.010, 0.015, 0.020, 0.030]
    eff_spreads = []
    for s in spreads:
        deal.spread = s
        out = engine.run(deal, schedule, discount)
        eff_spreads.append(aggregate_periods(out.per_period).effective_spread)

    # Strict monotonicity
    for a, b, sa, sb in zip(eff_spreads, eff_spreads[1:], spreads, spreads[1:]):
        assert b > a, (
            f"[{fixture_name}] effective spread non-monotonic: "
            f"spread {sa} → {a:.6f}, spread {sb} → {b:.6f}"
        )


# ──────────────────────────────────────────────────────────────────────
# Acceptance criterion 3: capital-weighted RAROC == single-period RAROC
#                         for a 1y bullet facility
# ──────────────────────────────────────────────────────────────────────


def test_capital_weighted_raroc_matches_single_period_for_1y_bullet():
    """1-period, dt=1.0 schedule: weighted RAROC == per_period[0].raroc exactly.

    This is the spec §9 corollary: any aggregation scheme that "weights"
    one period collapses to that period's number. We assert exact equality
    (no tolerance) because there's only one term in each sum.
    """
    inp = RAROCInput(
        product_type="mlt_credit",
        average_volume=50_000_000,
        average_drawn=50_000_000,  # bullet drawn = commitment
        initial_maturity=12,
        residual_maturity=12,       # 1y bullet
        spread=0.020,
        commitment_fee=0.0,
        global_grr=0.0,
        confirmed=True,
        rating="Baa2",
    )
    schedule = Schedule.from_raroc_input(inp, start=START)
    deal = RAROCInput(
        product_type=inp.product_type,
        rating=inp.rating,
        global_grr=inp.global_grr,
        confirmed=inp.confirmed,
        spread=inp.spread,
        commitment_fee=inp.commitment_fee,
    )
    out = PeriodEngine().run(deal, schedule)
    agg = aggregate_periods(out.per_period)

    single = out.per_period[0].raroc
    assert agg.capital_weighted_raroc == single
    assert agg.avg_raroc == single
    assert agg.n_periods == 1
    assert agg.total_years == pytest.approx(1.0)


# ──────────────────────────────────────────────────────────────────────
# Supporting checks — back-compat dict, identities, edge cases
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_dict_layout_preserves_engine_keys(fixture_name: str):
    """``FacilityAggregates.to_dict()`` keeps every key PeriodEngine returned.

    Task 1.3 already shipped a dict-shaped ``aggregates`` field — callers may
    be indexing by string. The wallet aggregator is the source of truth
    now, so this guards against accidental key churn.
    """
    fx, out, agg = run_fixture(fixture_name)
    d = agg.to_dict()

    required_keys = {
        "npv_borrower_cost",
        "npv_bank_net_margin",
        "npv_drawn_balance",
        "effective_spread",
        "effective_spread_bp",
        "fpe_weighted_raroc",
        "total_revenue_undisc",
        "total_el_undisc",
        "avg_exposure",
    }
    assert required_keys.issubset(d.keys())

    # Engine's aggregate dict must match the aggregate.py source of truth.
    for k in required_keys:
        assert out.aggregates[k] == pytest.approx(d[k], rel=1e-12, abs=1e-12)


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_bank_cost_identity_undiscounted_and_pv(fixture_name: str):
    """Bank cost = Σ(operating + funding + EL). Both undisc and PV variants."""
    fx, out, agg = run_fixture(fixture_name)
    rows = out.per_period

    expected_undisc = sum(r.cost + r.funding_cost + r.el for r in rows)
    expected_pv = sum((r.cost + r.funding_cost + r.el) * r.df for r in rows)

    assert agg.total_bank_costs_undisc == pytest.approx(expected_undisc, rel=1e-12)
    assert agg.npv_bank_costs == pytest.approx(expected_pv, rel=1e-12)


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_borrower_cost_equals_total_revenue(fixture_name: str):
    """Borrower cost (undisc) = total revenue (undisc) — same cash flow, two names."""
    fx, out, agg = run_fixture(fixture_name)
    assert agg.total_borrower_cost_undisc == pytest.approx(
        agg.total_revenue_undisc, rel=1e-12
    )
    # The PV view matches `npv_borrower_cost` for the same reason.
    rows = out.per_period
    assert agg.npv_borrower_cost == pytest.approx(
        sum(r.revenue * r.df for r in rows), rel=1e-12
    )


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_per_period_net_margin_identity(fixture_name: str):
    """Per-period: net_margin_i == revenue_i − (cost_i + funding_i + EL_i) + fpe_return_i.

    Anchors the bank-cost decomposition the aggregate exposes — if this
    drifts, aggregate's ``npv_bank_costs`` stops corresponding to the
    cash-flow line items the wallet UI shows.
    """
    fx, out, _ = run_fixture(fixture_name)
    for r in out.per_period:
        expected = r.revenue - (r.cost + r.funding_cost + r.el) + r.fpe_return
        assert r.net_margin == pytest.approx(expected, rel=1e-12, abs=1e-9)


def test_aggregate_periods_empty_list_returns_zeros():
    """No periods → all-zero aggregate (no division-by-zero / NaN)."""
    agg = aggregate_periods([])
    assert agg.npv_borrower_cost == 0.0
    assert agg.npv_bank_net_margin == 0.0
    assert agg.effective_spread == 0.0
    assert agg.capital_weighted_raroc == 0.0
    assert agg.avg_raroc == 0.0
    assert agg.n_periods == 0
    assert agg.total_years == 0.0


def test_avg_raroc_collapses_to_capital_weighted_for_uniform_fpe():
    """When every period has the same FPE × dt, the two weighted means coincide.

    A 5y RCF with constant commitment and constant drawn → FPE varies because
    K depends on remaining maturity. To get *uniform* FPE we'd need
    pathological inputs. Easier: build a synthetic case with two identical
    rows and check both means equal the row's RAROC.
    """
    schedule = Schedule.bullet_rcf_with_cleandown(
        commitment=10_000_000,
        drawn_levels=[(8_000_000, 1)],
        start=START,
    )
    deal = RAROCInput(
        product_type="mlt_credit",
        rating="Baa2",
        global_grr=0.0,
        confirmed=True,
        spread=0.020,
        commitment_fee=0.0025,
    )
    out = PeriodEngine().run(deal, schedule)
    agg = aggregate_periods(out.per_period)
    assert agg.avg_raroc == pytest.approx(
        agg.capital_weighted_raroc, rel=1e-12, abs=1e-12
    )


def test_avg_raroc_differs_from_capital_weighted_under_non_uniform_fpe():
    """A multi-period amortiser → FPE varies → the two means must differ.

    This protects against accidentally collapsing the avg/cap-weighted
    distinction during a future refactor.
    """
    fx, out, agg = run_fixture("period_termloan_7y_amortising")
    fpes = {r.fpe for r in out.per_period}
    assert len(fpes) > 1, "fixture should have non-uniform FPE across periods"
    assert agg.avg_raroc != pytest.approx(agg.capital_weighted_raroc, abs=1e-6), (
        f"avg ({agg.avg_raroc:.6f}) and capital-weighted ({agg.capital_weighted_raroc:.6f}) "
        "should diverge when FPE varies — they collapsed, suggesting a weighting bug"
    )


def test_attach_discount_factors_roundtrip_at_new_rate():
    """Calling attach_discount_factors with a fresh rate yields the same
    per-row DFs the engine would have produced if asked initially.
    """
    fx = load_fixture("period_rcf_5y")
    cfg = make_engine_config(fx["engine_config"])
    deal = make_deal(fx["deal"])
    schedule = Schedule.from_dict(fx["schedule"])
    engine = PeriodEngine(config=cfg)

    # Run once at 4.5%, then re-discount engine output at 2.0% and check
    # it matches a fresh engine run at 2.0%.
    out_high = engine.run(deal, schedule, DiscountSpec(kind="scalar", rate=0.045))
    out_low = engine.run(deal, schedule, DiscountSpec(kind="scalar", rate=0.020))

    attach_discount_factors(out_high.per_period, DiscountSpec(kind="scalar", rate=0.020))
    agg_redisc = aggregate_periods(out_high.per_period)
    agg_low = aggregate_periods(out_low.per_period)

    assert agg_redisc.npv_borrower_cost == pytest.approx(agg_low.npv_borrower_cost, rel=1e-12)
    assert agg_redisc.npv_bank_net_margin == pytest.approx(agg_low.npv_bank_net_margin, rel=1e-12)
    assert agg_redisc.npv_drawn_balance == pytest.approx(agg_low.npv_drawn_balance, rel=1e-12)
    assert agg_redisc.effective_spread == pytest.approx(agg_low.effective_spread, rel=1e-12)


def test_effective_spread_bp_units_match_decimal_form():
    """Sanity: ``effective_spread_bp`` is exactly 10_000 × ``effective_spread``."""
    _, _, agg = run_fixture("period_rcf_5y")
    assert agg.effective_spread_bp == pytest.approx(
        agg.effective_spread * 10000.0, rel=1e-12
    )


def test_fpe_years_matches_capital_usage_proxy():
    """``fpe_years`` = Σ FPE_i × dt_i is the capital-usage line.

    Pinned because the wallet view will show this as "average FPE × years"
    and downstream tasks will sum it across facilities (Task 1.5).
    """
    fx, out, agg = run_fixture("period_rcf_5y")
    assert agg.fpe_years == pytest.approx(
        sum(r.fpe * r.dt_years for r in out.per_period), rel=1e-12
    )


def test_facility_aggregates_is_immutable():
    """``FacilityAggregates`` is frozen — accidental mutation should raise."""
    agg = aggregate_periods([])
    with pytest.raises(Exception):
        agg.npv_borrower_cost = 1.0  # type: ignore[misc]
    assert isinstance(agg, FacilityAggregates)
