"""Tests for raroc_engine.schedule.

Covers Task 1.2 acceptance criteria:
- Constructors produce schedules matching the three Q1.1 fixtures.
- Backward-compat: a single-period schedule maps cleanly to the existing
  single-period calculator inputs (no behavioural drift).
- Period / Schedule validation invariants.
"""

from __future__ import annotations

import os
from datetime import date

import pytest
import yaml

from raroc_engine import Period, Schedule
from raroc_engine.calculator import RAROCCalculator
from raroc_engine.config import EngineConfig
from raroc_engine.models import RAROCInput


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
START = date(2026, 6, 1)


def load_fixture(name: str) -> dict:
    with open(os.path.join(FIXTURES_DIR, f"{name}.yaml")) as f:
        return yaml.safe_load(f)


def assert_periods_equal(actual: list[Period], expected: list[Period]) -> None:
    """Strict equality on the spec-§3 fields. Float fields use exact equality
    because constructors generate the same exact values the fixtures encode."""
    assert len(actual) == len(expected), (
        f"period count differs: {len(actual)} vs {len(expected)}"
    )
    for a, e in zip(actual, expected):
        assert a.index == e.index
        assert a.start == e.start, f"period {a.index} start mismatch"
        assert a.end == e.end, f"period {a.index} end mismatch"
        assert a.dt_years == e.dt_years, f"period {a.index} dt_years mismatch"
        assert a.commitment == e.commitment, f"period {a.index} commitment mismatch"
        assert a.avg_drawn == e.avg_drawn, f"period {a.index} avg_drawn mismatch"
        assert a.remaining_maturity_years == e.remaining_maturity_years, (
            f"period {a.index} remaining_maturity_years mismatch"
        )
        assert a.upfront_fee == e.upfront_fee, f"period {a.index} upfront_fee mismatch"
        assert a.flat_fee == e.flat_fee, f"period {a.index} flat_fee mismatch"
        assert a.participation_fee == e.participation_fee, (
            f"period {a.index} participation_fee mismatch"
        )
        assert a.floating_index == e.floating_index
        assert a.fixing_rate == e.fixing_rate


# ──────────────────────────────────────────────────────────────────
# Constructor → fixture conformance (acceptance criterion 1)
# ──────────────────────────────────────────────────────────────────

def test_bullet_rcf_with_cleandown_matches_fixture():
    """RCF constructor reproduces tests/fixtures/period_rcf_5y.yaml."""
    fixture = load_fixture("period_rcf_5y")
    expected = Schedule.from_dict(fixture["schedule"])

    actual = Schedule.bullet_rcf_with_cleandown(
        commitment=50_000_000,
        drawn_levels=[(35_000_000, 3), (20_000_000, 2)],
        start=START,
        upfront_fee=200_000,
    )

    assert_periods_equal(actual.periods, expected.periods)
    assert actual.is_annual
    assert actual.total_years == 5.0
    assert actual.day_count == expected.day_count


def test_scheduled_amortising_term_loan_matches_fixture():
    """Linear-amortising term-loan constructor reproduces period_termloan_7y_amortising."""
    fixture = load_fixture("period_termloan_7y_amortising")
    expected = Schedule.from_dict(fixture["schedule"])

    actual = Schedule.scheduled_amortising_term_loan(
        initial_drawn=70_000_000,
        total_years=7,
        start=START,
        final_balance=0.0,
        upfront_fee=350_000,
    )

    assert_periods_equal(actual.periods, expected.periods)
    assert actual.is_annual
    assert actual.total_years == 7.0


def test_drawdown_ramp_with_grace_matches_fixture():
    """Ramp+grace+amortise+bullet constructor reproduces period_projfin_10y_grace."""
    fixture = load_fixture("period_projfin_10y_grace")
    expected = Schedule.from_dict(fixture["schedule"])

    actual = Schedule.drawdown_ramp_with_grace(
        commitment=100_000_000,
        ramp_drawns=[30_000_000, 70_000_000, 100_000_000],
        grace_years=2,
        amortise_drawns=[90_000_000, 70_000_000, 50_000_000, 30_000_000],
        bullet_drawn=20_000_000,
        bullet_years=1,
        start=START,
        upfront_fee=1_000_000,
    )

    assert_periods_equal(actual.periods, expected.periods)
    assert actual.is_annual
    assert actual.total_years == 10.0


def test_project_finance_milestones_matches_fixture():
    """The milestones constructor also reproduces the projfin fixture."""
    fixture = load_fixture("period_projfin_10y_grace")
    expected = Schedule.from_dict(fixture["schedule"])

    actual = Schedule.project_finance_milestones(
        commitment=100_000_000,
        milestones=[
            (30_000_000, 1),
            (70_000_000, 1),
            (100_000_000, 3),
            (90_000_000, 1),
            (70_000_000, 1),
            (50_000_000, 1),
            (30_000_000, 1),
            (20_000_000, 1),
        ],
        start=START,
        upfront_fee=1_000_000,
    )

    assert_periods_equal(actual.periods, expected.periods)


# ──────────────────────────────────────────────────────────────────
# Backwards compatibility (acceptance criterion 2)
# ──────────────────────────────────────────────────────────────────

def test_single_period_schedule_has_today_shape():
    """A length-1 schedule built from a RAROCInput preserves the single-period
    fields the existing calculator consumes (spec §9)."""
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

    sched = Schedule.from_raroc_input(inp, start=START)

    assert len(sched.periods) == 1
    assert sched.is_annual
    p = sched.periods[0]
    assert p.dt_years == 1.0
    assert p.commitment == 50_000_000
    assert p.avg_drawn == 35_000_000
    assert p.remaining_maturity_years == pytest.approx(60.0 / 12.0)
    assert p.upfront_fee == 200_000


def test_single_period_constructor_matches_today_calculator_unchanged():
    """The existing single-period RAROCCalculator output is unchanged by the
    introduction of the Schedule model — it doesn't consume one yet.

    This is the 'backward-compat: existing single-period calls unchanged'
    half of the acceptance criterion. It pins today's calculator outputs so
    a regression in the engine would surface.
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
    calc = RAROCCalculator(config=EngineConfig())
    out = calc.calculate(inp)

    # Anchor values: bank revenue = 1.5%×35M + 0.25%×15M + 200k upfront
    expected_revenue = 0.015 * 35_000_000 + 0.0025 * 15_000_000 + 200_000
    assert out.revenue == pytest.approx(expected_revenue)
    # Exposure under confirmed-MLT CCF = 0.25×drawn + 0.75×commitment
    assert out.exposure == pytest.approx(0.25 * 35_000_000 + 0.75 * 50_000_000)

    # The Schedule wrapper exposes those same volumes intact.
    sched = Schedule.from_raroc_input(inp, start=START)
    p = sched.periods[0]
    assert p.commitment == inp.average_volume
    assert p.avg_drawn == inp.average_drawn
    # Schedule object does NOT mutate inp.
    assert inp.average_drawn == 35_000_000


# ──────────────────────────────────────────────────────────────────
# Round-trip / serialisation
# ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", [
    "period_rcf_5y",
    "period_termloan_7y_amortising",
    "period_projfin_10y_grace",
])
def test_from_dict_to_dict_roundtrip(name: str):
    fixture = load_fixture(name)
    s = Schedule.from_dict(fixture["schedule"])
    d = s.to_dict()
    s2 = Schedule.from_dict(d)
    assert_periods_equal(s2.periods, s.periods)
    assert s2.day_count == s.day_count
    assert s2.type_ == s.type_


# ──────────────────────────────────────────────────────────────────
# Validation
# ──────────────────────────────────────────────────────────────────

def _good_period(**overrides) -> Period:
    base = dict(
        index=1, start=START, end=date(2027, 6, 1), dt_years=1.0,
        commitment=100.0, avg_drawn=80.0, remaining_maturity_years=5.0,
    )
    base.update(overrides)
    return Period(**base)


def test_period_rejects_drawn_above_commitment():
    with pytest.raises(ValueError, match="avg_drawn"):
        _good_period(avg_drawn=120.0, commitment=100.0)


def test_period_rejects_zero_dt_years():
    with pytest.raises(ValueError, match="dt_years"):
        _good_period(dt_years=0.0)


def test_period_rejects_zero_remaining_maturity():
    with pytest.raises(ValueError, match="remaining_maturity_years"):
        _good_period(remaining_maturity_years=0.0)


def test_period_accepts_floating_index_without_fixing():
    """``floating_index`` set + ``fixing_rate=None`` = "unresolved floating".

    Task 1.5 relaxed this invariant: the period engine's curve cascade
    resolves these at run time (D-0003 §5), so the schema has to allow
    the unresolved state at construction.
    """
    p = _good_period(floating_index="EURIBOR_3M", fixing_rate=None)
    assert p.floating_index == "EURIBOR_3M"
    assert p.fixing_rate is None


def test_period_rejects_fixing_rate_without_floating_index():
    with pytest.raises(ValueError, match="floating_index"):
        _good_period(floating_index=None, fixing_rate=0.03)


def test_period_accepts_matched_floating_pair():
    p = _good_period(floating_index="EURIBOR_3M", fixing_rate=0.03)
    assert p.all_in_rate(0.015) == pytest.approx(0.045)


def test_period_avg_undrawn_property():
    p = _good_period(commitment=100.0, avg_drawn=80.0)
    assert p.avg_undrawn == 20.0


def test_schedule_rejects_empty_periods():
    with pytest.raises(ValueError, match="at least one"):
        Schedule(periods=[])


def test_schedule_rejects_non_contiguous_periods():
    p1 = _good_period(index=1, start=date(2026, 6, 1), end=date(2027, 6, 1))
    p2 = _good_period(index=2, start=date(2027, 7, 1), end=date(2028, 7, 1))
    with pytest.raises(ValueError, match="not contiguous"):
        Schedule(periods=[p1, p2])


def test_schedule_rejects_out_of_order_index():
    p1 = _good_period(index=2, start=date(2026, 6, 1), end=date(2027, 6, 1))
    with pytest.raises(ValueError, match="period index"):
        Schedule(periods=[p1])


def test_principal_paydowns_for_amortising_loan():
    """Last entry is residual (commitment of the last period); preceding entries
    are the commitment drops between successive periods."""
    s = Schedule.scheduled_amortising_term_loan(
        initial_drawn=70_000_000,
        total_years=7,
        start=START,
    )
    paydowns = s.principal_paydowns()
    # commitments are 70, 60, 50, 40, 30, 20, 10 → diffs are 10 each, residual 10.
    assert paydowns == [10_000_000] * 7


def test_principal_paydowns_for_bullet_rcf():
    """Bullet RCF: commitment constant, so paydowns are all 0 except the residual."""
    s = Schedule.bullet_rcf_with_cleandown(
        commitment=50_000_000,
        drawn_levels=[(35_000_000, 3), (20_000_000, 2)],
        start=START,
    )
    paydowns = s.principal_paydowns()
    assert paydowns[:-1] == [0.0, 0.0, 0.0, 0.0]
    assert paydowns[-1] == 50_000_000
