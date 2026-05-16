"""Tests for raroc_engine.scenarios.

Acceptance (PLAN Task 3.1): the three canonical scenarios — refinance
at year 2, rates -100 bp, bank swap — produce the expected directional
changes against the Q1.1 RCF fixture (period_rcf_5y.yaml). Plus
reproducibility (same inputs always produce the same outputs) and
no-mutation invariants on base inputs.

The fixture-driven assertions reuse the Q1.1 base aggregates as the
counterfactual; the scenarios shift one knob at a time so every
directional change has a single observable cause.
"""

from __future__ import annotations

import copy
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
from raroc_engine.banks import BANK_PROFILES
from raroc_engine.scenarios import (
    BankProfileSwapMod,
    DrawdownPatternMod,
    RatesShiftMod,
    RefinanceMod,
    Scenario,
    ScenarioComparison,
    ScenarioContext,
    ScenarioDelta,
    ScenarioRun,
    ScenarioRunner,
    ScenarioSegment,
    StructureSwapMod,
)


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
RCF_FIXTURE = "period_rcf_5y"


# ──────────────────────────────────────────────────────────────────────
# Fixture helpers (mirror test_period_engine.py for symmetry)
# ──────────────────────────────────────────────────────────────────────


def load_fixture(name: str) -> dict:
    with open(os.path.join(FIXTURES_DIR, f"{name}.yaml")) as f:
        return yaml.safe_load(f)


def make_inputs(fixture_name: str = RCF_FIXTURE) -> Tuple[
    EngineConfig, RAROCInput, Schedule, DiscountSpec, dict
]:
    """Load a fixture and rebuild the engine input bundle."""
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
# Smoke: base run reproduces the fixture's aggregates
# ──────────────────────────────────────────────────────────────────────


def test_base_run_matches_fixture_aggregates():
    """The runner's base case == direct PeriodEngine output on the fixture."""
    cfg, deal, schedule, discount, fx = make_inputs()
    runner = ScenarioRunner(config=cfg)
    base = runner.run_base(deal, schedule, discount)

    expected = fx["expected"]["aggregates"]
    # Fixture aggregate values are rounded to ~8 sig figs in the YAML;
    # use 1e-6 relative tolerance to match the storage precision.
    assert base.npv_borrower_cost == pytest.approx(
        float(expected["npv_borrower_cost"]), rel=1e-6
    )
    assert base.npv_bank_net_margin == pytest.approx(
        float(expected["npv_bank_net_margin"]), rel=1e-6
    )
    assert base.effective_spread_bp == pytest.approx(
        float(expected["effective_spread_bp"]), abs=0.5
    )
    assert base.capital_weighted_raroc == pytest.approx(
        float(expected["fpe_weighted_raroc"]), rel=1e-6
    )
    assert len(base.per_period) == 5
    assert base.engine_meta["n_segments"] == 1
    assert base.mods_applied == []


def test_base_run_matches_period_engine_directly():
    """Round-trip parity: ScenarioRunner.run_base == PeriodEngine.run."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    base = runner.run_base(deal, schedule, discount)

    direct = PeriodEngine(config=cfg).run(deal, schedule, discount)
    for r1, r2 in zip(base.per_period, direct.per_period):
        assert r1.raroc == pytest.approx(r2.raroc, abs=1e-12)
        assert r1.fpe == pytest.approx(r2.fpe, abs=1e-12)
        assert r1.revenue == pytest.approx(r2.revenue, abs=1e-12)
        assert r1.df == pytest.approx(r2.df, abs=1e-12)
        assert r1.t_end_years == pytest.approx(r2.t_end_years, abs=1e-12)


# ──────────────────────────────────────────────────────────────────────
# Canonical Scenario 1: refinance at year 2 with lower spread
# ──────────────────────────────────────────────────────────────────────


def test_refi_year2_preserves_pre_refi_per_period_raroc():
    """Pre-refi periods belong to the ORIGINAL contract — RAROC unchanged.

    Reduces the pre-refi periods to a 2-year-life facility would change
    the IRB maturity adjustment. The mod must keep the original
    ``remaining_maturity_years`` so periods 1-2 produce the same RAROC.
    """
    cfg, deal, schedule, discount, fx = make_inputs()
    runner = ScenarioRunner(config=cfg)
    base = runner.run_base(deal, schedule, discount)
    scenario = Scenario("refi", [RefinanceMod(at_year=2, new_spread=0.010)])
    run = runner.run_scenario(deal, schedule, scenario, discount)

    # Periods 1 & 2 pre-refi — RAROC must equal the base.
    assert run.per_period[0].raroc == pytest.approx(
        base.per_period[0].raroc, abs=1e-12
    )
    assert run.per_period[1].raroc == pytest.approx(
        base.per_period[1].raroc, abs=1e-12
    )
    # Per-period revenue / FPE / EL also identical pre-refi.
    for i in (0, 1):
        assert run.per_period[i].revenue == pytest.approx(
            base.per_period[i].revenue, abs=1e-12
        )
        assert run.per_period[i].fpe == pytest.approx(
            base.per_period[i].fpe, abs=1e-12
        )
        assert run.per_period[i].el == pytest.approx(
            base.per_period[i].el, abs=1e-12
        )


def test_refi_year2_post_refi_revenue_and_raroc_drop():
    """Lower spread on the post-refi tail → revenue and per-period RAROC drop."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    base = runner.run_base(deal, schedule, discount)
    scenario = Scenario("refi", [RefinanceMod(at_year=2, new_spread=0.010)])
    run = runner.run_scenario(deal, schedule, scenario, discount)

    # Periods 3, 4, 5 post-refi: every per-period RAROC strictly less than base.
    for i in (2, 3, 4):
        assert run.per_period[i].raroc < base.per_period[i].raroc, (
            f"post-refi P{i+1} RAROC {run.per_period[i].raroc} "
            f"should be less than base {base.per_period[i].raroc}"
        )
        # Revenue strictly lower (lower spread on the same drawn balance).
        assert run.per_period[i].revenue < base.per_period[i].revenue


def test_refi_year2_aggregates_directional():
    """Acceptance: NPV borrower cost down, effective spread down vs base."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    scenarios = [Scenario("refi_y2", [RefinanceMod(at_year=2, new_spread=0.010)])]
    comp = runner.compare(deal, schedule, scenarios, discount)
    delta = comp.deltas()[0]

    # Lower spread on years 3-5 ⇒ borrower pays less, bank earns less.
    assert delta.npv_borrower_cost_delta < 0
    assert delta.npv_borrower_cost_pct < -5.0  # at least 5% decrease
    assert delta.npv_bank_net_margin_delta < 0
    # Effective spread DROPS (revenue PV / drawn PV ratio falls).
    assert delta.effective_spread_bp_delta < -10.0
    # FPE-weighted RAROC drops (post-refi periods drag the average down).
    assert delta.capital_weighted_raroc_bp_delta < 0


def test_refi_extends_maturity():
    """new_maturity_years extends the post-refi tail beyond the original life."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    # Original 5y RCF, refi at year 2, extend post-refi to 5 more years
    # (total facility life = 7 years).
    scenario = Scenario(
        "refi_extend",
        [RefinanceMod(at_year=2, new_spread=0.012, new_maturity_years=5)],
    )
    run = runner.run_scenario(deal, schedule, scenario, discount)

    assert len(run.per_period) == 7
    assert run.engine_meta["n_segments"] == 2
    assert run.engine_meta["total_years"] == pytest.approx(7.0)
    # The stitched t_end_years are 1, 2, ..., 7.
    expected_t = [float(i) for i in range(1, 8)]
    actual_t = [r.t_end_years for r in run.per_period]
    assert actual_t == pytest.approx(expected_t)


def test_refi_truncates_maturity():
    """new_maturity_years < original tail → early payoff."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    # 5y original; refi at year 2 with only 1 year left after refi (early payoff).
    scenario = Scenario(
        "refi_payoff",
        [RefinanceMod(at_year=2, new_spread=0.010, new_maturity_years=1)],
    )
    run = runner.run_scenario(deal, schedule, scenario, discount)
    assert len(run.per_period) == 3  # 2 pre-refi + 1 post-refi


def test_refi_validation_at_year_out_of_range():
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)

    with pytest.raises(ValueError, match="at_year"):
        runner.run_scenario(
            deal, schedule,
            Scenario("bad", [RefinanceMod(at_year=0, new_spread=0.01)]),
            discount,
        )
    with pytest.raises(ValueError, match="at_year"):
        runner.run_scenario(
            deal, schedule,
            Scenario("bad", [RefinanceMod(at_year=5, new_spread=0.01)]),
            discount,
        )


def test_refi_with_upfront_fee_lands_on_post_refi_period_one():
    """Refi fee belongs to post-refi period 1; pre-refi keeps original upfront."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    refi_fee = 75_000
    scenario = Scenario(
        "refi_with_fee",
        [RefinanceMod(at_year=2, new_spread=0.010, new_upfront_fee=refi_fee)],
    )
    run = runner.run_scenario(deal, schedule, scenario, discount)

    # Pre-refi P1 still has the original 200_000 upfront baked into revenue.
    # Post-refi P1 (= run.per_period[2]) has the refi 75_000 baked in.
    base_run = runner.run_base(deal, schedule, discount)
    base_p3_no_upfront_revenue = base_run.per_period[2].revenue  # base P3 has no upfront
    # Post-refi P3 with new spread 100bp would have:
    # spread×drawn = 0.010 × 35_000_000 = 350_000
    # commit_fee × undrawn = 0.0025 × 15_000_000 = 37_500
    # + refi upfront = 75_000
    # Total = 462_500
    expected = 0.010 * 35_000_000 + 0.0025 * 15_000_000 + refi_fee
    assert run.per_period[2].revenue == pytest.approx(expected)


# ──────────────────────────────────────────────────────────────────────
# Canonical Scenario 2: rates shift -100 bp
# ──────────────────────────────────────────────────────────────────────


def test_rates_shift_minus_100bp_lifts_borrower_npv():
    """Lower discount rate ⇒ DFs up ⇒ NPV of fixed cash flows rises."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    scenarios = [Scenario("rates_-100", [RatesShiftMod(shift_bps=-100)])]
    comp = runner.compare(deal, schedule, scenarios, discount)
    d = comp.deltas()[0]

    # NPV borrower up because DFs rose.
    assert d.npv_borrower_cost_delta > 0
    assert 1.0 < d.npv_borrower_cost_pct < 6.0  # within sensible range


def test_rates_shift_minus_100bp_drops_raroc_by_exactly_after_tax_shift():
    """For a fixed-rate facility with funding_cost_bp=0, RAROC drop = (1-tax) × shift.

    The RAROC formula: (1-tax) × ((rev-cost-fc-el)/fpe + rfr). With
    funding_cost_bp=0, the numerator does not depend on rfr; only the
    additive ``rfr`` term shifts. Δrfr = -1% ⇒ ΔRAROC = -0.75% (exact)
    when tax = 25%.
    """
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    scenarios = [Scenario("rates_-100", [RatesShiftMod(shift_bps=-100)])]
    comp = runner.compare(deal, schedule, scenarios, discount)
    d = comp.deltas()[0]

    expected_drop_bp = -100.0 * (1.0 - cfg.bank_tax_rate)  # -75 bp
    assert d.capital_weighted_raroc_bp_delta == pytest.approx(
        expected_drop_bp, abs=1e-9
    )
    # And every per-period RAROC drops by the same amount.
    base = comp.base
    for r_base, r_scenario in zip(base.per_period, comp.scenarios[0].per_period):
        delta_bp = (r_scenario.raroc - r_base.raroc) * 10000.0
        assert delta_bp == pytest.approx(expected_drop_bp, abs=1e-9)


def test_rates_shift_does_not_change_per_period_revenue_for_fixed_rate():
    """Fixed-rate facility: cash flows don't move with rates — only DFs do."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    base = runner.run_base(deal, schedule, discount)
    run = runner.run_scenario(
        deal, schedule,
        Scenario("rates_-100", [RatesShiftMod(shift_bps=-100)]),
        discount,
    )
    for r_base, r_scenario in zip(base.per_period, run.per_period):
        assert r_scenario.revenue == pytest.approx(r_base.revenue, abs=1e-12)
        assert r_scenario.cost == pytest.approx(r_base.cost, abs=1e-12)
        assert r_scenario.el == pytest.approx(r_base.el, abs=1e-12)


def test_rates_shift_with_engine_rate_isolated_only_changes_npv():
    """affect_engine_rate=False → discount-only sensitivity, RAROC unchanged."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    base = runner.run_base(deal, schedule, discount)
    run = runner.run_scenario(
        deal, schedule,
        Scenario(
            "rates_disc_only",
            [RatesShiftMod(shift_bps=-100, affect_engine_rate=False)],
        ),
        discount,
    )

    # NPV borrower still moves up (DFs lifted).
    assert run.npv_borrower_cost > base.npv_borrower_cost
    # Per-period RAROC unchanged.
    for r_base, r_scenario in zip(base.per_period, run.per_period):
        assert r_scenario.raroc == pytest.approx(r_base.raroc, abs=1e-12)


def test_rates_shift_floating_fixings_when_present():
    """Floating periods with a pre-set fixing get the shift applied."""
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
    # Pin a fixing on every period so the mod has something to shift.
    for p in schedule.periods:
        p.fixing_rate = 0.030

    runner = ScenarioRunner(config=cfg)
    run = runner.run_scenario(
        deal, schedule,
        Scenario("rates_+50", [RatesShiftMod(shift_bps=50)]),
        DiscountSpec(kind="scalar", rate=0.0325),
    )
    # Every period's fixing should be shifted by +50bp.
    for row in run.per_period:
        assert row.fixing_rate == pytest.approx(0.030 + 0.005, abs=1e-12)


# ──────────────────────────────────────────────────────────────────────
# Canonical Scenario 3: bank swap (different funding cost / tax)
# ──────────────────────────────────────────────────────────────────────


def test_bank_swap_higher_funding_cuts_net_margin_and_raroc():
    """Higher funding_cost_bp → lower net margin and lower RAROC.

    Borrower cash flows are unchanged (the borrower doesn't see the
    bank's cost of funds), so npv_borrower_cost stays exactly the same.
    """
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    # Fixture has funding_cost_bp=0; bump to 50bp ⇒ visible funding cost.
    scenarios = [Scenario(
        "bank_swap_funding_+50",
        [BankProfileSwapMod(funding_cost_bp=0.005)],
    )]
    comp = runner.compare(deal, schedule, scenarios, discount)
    d = comp.deltas()[0]

    assert d.npv_borrower_cost_delta == pytest.approx(0.0, abs=1e-9)
    assert d.npv_bank_net_margin_delta < 0
    assert d.capital_weighted_raroc_bp_delta < -100.0  # large drop


def test_bank_swap_changes_per_period_funding_cost():
    """Each period's funding_cost line should reflect the new funding rate."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    base = runner.run_base(deal, schedule, discount)
    run = runner.run_scenario(
        deal, schedule,
        Scenario("bs", [BankProfileSwapMod(funding_cost_bp=0.005)]),
        discount,
    )
    for r_base, r_scenario in zip(base.per_period, run.per_period):
        # funding_cost = funding_cost_bp × exposure × dt
        expected = 0.005 * r_base.exposure * r_base.dt_years
        assert r_scenario.funding_cost == pytest.approx(expected)
        assert r_base.funding_cost == pytest.approx(0.0)


def test_bank_swap_lower_tax_lifts_raroc():
    """Lower bank tax rate → higher after-tax RAROC."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    base = runner.run_base(deal, schedule, discount)
    run = runner.run_scenario(
        deal, schedule,
        Scenario("low_tax", [BankProfileSwapMod(bank_tax_rate=0.15)]),
        discount,
    )
    # All per-period RAROCs should move up (lower tax wedge).
    for r_base, r_scenario in zip(base.per_period, run.per_period):
        assert r_scenario.raroc > r_base.raroc


@pytest.mark.skipif(
    "bnp_paribas" not in BANK_PROFILES,
    reason="premium_banks.json not loaded in this environment",
)
def test_bank_swap_with_profile_key_applies_profile_parameters():
    """When profile_key is set, EngineConfig.apply_bank_profile is invoked."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    profile = BANK_PROFILES["bnp_paribas"]
    run = runner.run_scenario(
        deal, schedule,
        Scenario("bnp", [BankProfileSwapMod(profile_key="bnp_paribas")]),
        discount,
    )
    base = runner.run_base(deal, schedule, discount)
    # When the profile's funding spread > 0, funding cost lifts off zero.
    assert profile.funding_spread_bp > 0
    for r_base, r_scenario in zip(base.per_period, run.per_period):
        assert r_scenario.funding_cost > r_base.funding_cost


def test_bank_swap_unknown_profile_key_silently_no_ops():
    """An unknown profile key does not raise; cfg is left unchanged.

    This matches EngineConfig.apply_bank_profile's quiet behaviour —
    callers can dial up a list of bank candidates without worrying
    about which ones the local data file knows.
    """
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    base = runner.run_base(deal, schedule, discount)
    run = runner.run_scenario(
        deal, schedule,
        Scenario("ghost", [BankProfileSwapMod(profile_key="ghost_bank_42")]),
        discount,
    )
    # No-op profile + no overrides → exactly the same engine output.
    for r_base, r_scenario in zip(base.per_period, run.per_period):
        assert r_scenario.raroc == pytest.approx(r_base.raroc, abs=1e-12)


# ──────────────────────────────────────────────────────────────────────
# DrawdownPatternMod
# ──────────────────────────────────────────────────────────────────────


def test_drawdown_mod_replaces_avg_drawn_per_period():
    """Replace the cleandown profile; commitment & maturities preserved."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    base = runner.run_base(deal, schedule, discount)
    # Original profile: 35M ×3, 20M ×2. New: heavier drawdown 40M ×5.
    run = runner.run_scenario(
        deal, schedule,
        Scenario("heavier", [DrawdownPatternMod(new_drawn_levels=[(40_000_000, 5)])]),
        discount,
    )
    # Every period's avg_drawn = 40M now.
    for row in run.per_period:
        assert row.avg_drawn == pytest.approx(40_000_000)
    # Higher drawn → higher revenue (more interest, less commit fee).
    assert run.aggregates.total_revenue_undisc > base.aggregates.total_revenue_undisc


def test_drawdown_mod_clamps_to_commitment():
    """avg_drawn cannot exceed the period's commitment."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    run = runner.run_scenario(
        deal, schedule,
        Scenario("over", [DrawdownPatternMod(
            new_drawn_levels=[(80_000_000, 5)],  # commitment is 50M
        )]),
        discount,
    )
    for row in run.per_period:
        assert row.avg_drawn == pytest.approx(50_000_000)


def test_drawdown_mod_validation_length_mismatch():
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    with pytest.raises(ValueError, match="profile has"):
        runner.run_scenario(
            deal, schedule,
            Scenario("bad", [DrawdownPatternMod(new_drawn_levels=[(10_000_000, 3)])]),
            discount,
        )


# ──────────────────────────────────────────────────────────────────────
# StructureSwapMod
# ──────────────────────────────────────────────────────────────────────


def test_structure_swap_replaces_schedule_wholesale():
    """RCF → amortising term loan: period count + exposure shape change."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    new_schedule = Schedule.scheduled_amortising_term_loan(
        initial_drawn=35_000_000,
        total_years=5,
        start=date(2026, 6, 1),
    )
    run = runner.run_scenario(
        deal, schedule,
        Scenario(
            "to_termloan",
            [StructureSwapMod(new_schedule=new_schedule)],
        ),
        discount,
    )
    assert len(run.per_period) == 5
    # Amortising: P1 drawn ≈ 31.5M, P5 ≈ 3.5M (linear amortisation).
    assert run.per_period[0].avg_drawn > run.per_period[-1].avg_drawn


def test_structure_swap_can_override_deal_fields():
    """deal_overrides applied to the post-swap deal copy.

    Compares two structure-swap scenarios with the SAME amortising
    schedule but different spreads; only the spread override should
    drive the revenue difference (so the schedule shape doesn't
    confound the test).
    """
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    new_schedule = Schedule.scheduled_amortising_term_loan(
        initial_drawn=35_000_000,
        total_years=5,
        start=date(2026, 6, 1),
    )
    keep_spread_run = runner.run_scenario(
        deal, schedule,
        Scenario("structure_only", [StructureSwapMod(new_schedule=new_schedule)]),
        discount,
    )
    bumped_spread_run = runner.run_scenario(
        deal, schedule,
        Scenario("structure+price", [StructureSwapMod(
            new_schedule=new_schedule,
            deal_overrides={"spread": 0.020},  # bumped from 150bp to 200bp
        )]),
        discount,
    )
    # Higher spread on the same schedule → strictly higher revenue per period.
    for r_keep, r_bump in zip(keep_spread_run.per_period, bumped_spread_run.per_period):
        assert r_bump.revenue > r_keep.revenue


# ──────────────────────────────────────────────────────────────────────
# Reproducibility
# ──────────────────────────────────────────────────────────────────────


def test_scenario_runs_are_reproducible():
    """Same inputs → identical aggregates and per-period rows.

    The acceptance criterion's "reproducible given seed inputs" pins
    that there is no RNG, no global state mutation, and no non-
    deterministic ordering across multiple runs.
    """
    cfg, deal, schedule, discount, _ = make_inputs()
    scenarios = [
        Scenario("refi_y2", [RefinanceMod(at_year=2, new_spread=0.010)]),
        Scenario("rates_-100", [RatesShiftMod(shift_bps=-100)]),
        Scenario("bank_swap", [BankProfileSwapMod(funding_cost_bp=0.005)]),
    ]

    runner_a = ScenarioRunner(config=copy.deepcopy(cfg))
    runner_b = ScenarioRunner(config=copy.deepcopy(cfg))
    a = runner_a.compare(deal, schedule, scenarios, discount)
    b = runner_b.compare(
        copy.deepcopy(deal),
        copy.deepcopy(schedule),
        copy.deepcopy(scenarios),
        copy.deepcopy(discount),
    )

    for r_a, r_b in zip(a.all_runs, b.all_runs):
        assert r_a.npv_borrower_cost == pytest.approx(r_b.npv_borrower_cost, abs=1e-12)
        assert r_a.npv_bank_net_margin == pytest.approx(
            r_b.npv_bank_net_margin, abs=1e-12
        )
        assert r_a.capital_weighted_raroc == pytest.approx(
            r_b.capital_weighted_raroc, abs=1e-12
        )
        for row_a, row_b in zip(r_a.per_period, r_b.per_period):
            assert row_a.raroc == pytest.approx(row_b.raroc, abs=1e-12)
            assert row_a.fpe == pytest.approx(row_b.fpe, abs=1e-12)
            assert row_a.df == pytest.approx(row_b.df, abs=1e-12)


def test_scenario_runner_does_not_mutate_caller_inputs():
    """The runner deepcopies inputs internally; caller objects survive intact."""
    cfg, deal, schedule, discount, _ = make_inputs()

    deal_snapshot = copy.deepcopy(deal)
    schedule_snapshot = copy.deepcopy(schedule)
    discount_snapshot = copy.deepcopy(discount)
    cfg_snapshot = copy.deepcopy(cfg)

    runner = ScenarioRunner(config=cfg)
    runner.compare(
        deal, schedule,
        [
            Scenario("refi", [RefinanceMod(at_year=2, new_spread=0.010)]),
            Scenario("rates", [RatesShiftMod(shift_bps=-100)]),
            Scenario("bank", [BankProfileSwapMod(funding_cost_bp=0.005)]),
        ],
        discount,
    )

    assert deal == deal_snapshot
    assert discount == discount_snapshot
    # Schedule equality compared via dict shape (Schedule itself is not frozen).
    assert schedule.to_dict() == schedule_snapshot.to_dict()
    # Cfg fields untouched.
    assert cfg.risk_free_rate == cfg_snapshot.risk_free_rate
    assert cfg.funding_cost_bp == cfg_snapshot.funding_cost_bp
    assert cfg.bank_tax_rate == cfg_snapshot.bank_tax_rate


# ──────────────────────────────────────────────────────────────────────
# Comparison shape + delta arithmetic
# ──────────────────────────────────────────────────────────────────────


def test_comparison_to_table_shape():
    """to_table() emits one base row + one row per scenario, plus deltas."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    scenarios = [
        Scenario("refi", [RefinanceMod(at_year=2, new_spread=0.010)],
                 description="Refinance year 2 at 100bp"),
        Scenario("rates", [RatesShiftMod(shift_bps=-100)]),
    ]
    comp = runner.compare(deal, schedule, scenarios, discount)
    table = comp.to_table()

    assert table["base_name"] == "base"
    assert len(table["rows"]) == 3  # base + 2 scenarios
    assert table["rows"][0]["is_base"] is True
    assert table["rows"][1]["is_base"] is False
    assert table["rows"][1]["name"] == "refi"
    assert table["rows"][1]["description"] == "Refinance year 2 at 100bp"
    assert table["rows"][1]["mods_applied"] == ["refi at year 2, spread→100bp"]
    assert len(table["rows"][1]["per_period_raroc_bp"]) == 5
    assert len(table["deltas"]) == 2


def test_delta_pct_handles_zero_base():
    """When base value is exactly zero, the % delta is 0 (no divide error)."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)

    # Build a degenerate base with zero revenue (no spread, no fees).
    deal_zero = copy.deepcopy(deal)
    deal_zero.spread = 0.0
    deal_zero.commitment_fee = 0.0
    schedule_no_fees = copy.deepcopy(schedule)
    for p in schedule_no_fees.periods:
        p.upfront_fee = 0.0
    base = runner.run_base(deal_zero, schedule_no_fees, discount)
    assert base.npv_borrower_cost == pytest.approx(0.0, abs=1e-9)

    comp = runner.compare(
        deal_zero, schedule_no_fees,
        [Scenario("rates", [RatesShiftMod(shift_bps=-100)])],
        discount,
    )
    d = comp.deltas()[0]
    # Both base and scenario have zero borrower cost; delta_pct is 0.
    assert d.npv_borrower_cost_pct == 0.0


def test_empty_scenario_equals_base():
    """A Scenario with zero mods is the base run with a different label."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    base = runner.run_base(deal, schedule, discount)
    run = runner.run_scenario(deal, schedule, Scenario("nop", []), discount)
    assert run.npv_borrower_cost == pytest.approx(base.npv_borrower_cost, abs=1e-12)
    assert run.capital_weighted_raroc == pytest.approx(
        base.capital_weighted_raroc, abs=1e-12
    )


# ──────────────────────────────────────────────────────────────────────
# Mod composition + segment stitching
# ──────────────────────────────────────────────────────────────────────


def test_compose_refi_then_rates_shift():
    """A scenario can chain mods; each applies to the prior context."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    base = runner.run_base(deal, schedule, discount)

    combined = Scenario("refi+rates", [
        RefinanceMod(at_year=2, new_spread=0.010),
        RatesShiftMod(shift_bps=-100),
    ])
    run = runner.run_scenario(deal, schedule, combined, discount)

    # Per-period RAROC: pre-refi periods get the rates shift only; post-refi
    # get both spread reduction AND rates shift.
    expected_drop_bp = -100.0 * (1.0 - cfg.bank_tax_rate)
    pre_refi_drop_bp = (run.per_period[0].raroc - base.per_period[0].raroc) * 10000.0
    assert pre_refi_drop_bp == pytest.approx(expected_drop_bp, abs=1e-9)
    # Post-refi RAROC strictly less than (base - rates_shift) because of
    # the spread reduction on top.
    post_refi_drop_bp = (run.per_period[2].raroc - base.per_period[2].raroc) * 10000.0
    assert post_refi_drop_bp < expected_drop_bp


def test_segments_stitched_t_end_years_are_global_timeline():
    """Multi-segment runs must produce monotonic global t_end_years."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    run = runner.run_scenario(
        deal, schedule,
        Scenario("refi", [RefinanceMod(at_year=3, new_spread=0.010)]),
        discount,
    )
    t_ends = [r.t_end_years for r in run.per_period]
    assert t_ends == pytest.approx([1.0, 2.0, 3.0, 4.0, 5.0])
    # Indices renumber 1..5 across segments.
    assert [r.index for r in run.per_period] == [1, 2, 3, 4, 5]


def test_segments_stitched_dfs_at_global_timeline():
    """DFs after stitching must use the global t_end (not segment-local)."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    rate = float(discount.rate)
    run = runner.run_scenario(
        deal, schedule,
        Scenario("refi", [RefinanceMod(at_year=2, new_spread=0.010)]),
        discount,
    )
    for row in run.per_period:
        expected_df = (1.0 + rate) ** (-row.t_end_years)
        assert row.df == pytest.approx(expected_df, rel=1e-12)


# ──────────────────────────────────────────────────────────────────────
# All three canonical scenarios in one comparison (acceptance pin)
# ──────────────────────────────────────────────────────────────────────


def test_acceptance_three_canonical_scenarios_directional():
    """PLAN Task 3.1 acceptance: refi y2, rates -100bp, bank swap.

    All three produce the expected directional changes against the
    Q1.1 RCF fixture.
    """
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    scenarios = [
        Scenario("refi_y2", [RefinanceMod(at_year=2, new_spread=0.010)]),
        Scenario("rates_-100bp", [RatesShiftMod(shift_bps=-100)]),
        Scenario("bank_swap_funding+50bp", [BankProfileSwapMod(funding_cost_bp=0.005)]),
    ]
    comp = runner.compare(deal, schedule, scenarios, discount)
    deltas = {d.name: d for d in comp.deltas()}

    # 1. Refinance at year 2, lower spread → borrower NPV down, RAROC down.
    refi = deltas["refi_y2"]
    assert refi.npv_borrower_cost_delta < 0
    assert refi.effective_spread_bp_delta < 0
    assert refi.capital_weighted_raroc_bp_delta < 0

    # 2. Rates -100bp → borrower NPV up, RAROC down by exactly 75bp.
    rates = deltas["rates_-100bp"]
    assert rates.npv_borrower_cost_delta > 0
    assert rates.capital_weighted_raroc_bp_delta == pytest.approx(
        -100.0 * (1.0 - cfg.bank_tax_rate), abs=1e-9
    )

    # 3. Bank swap (higher funding) → borrower NPV unchanged,
    #    bank net margin down, RAROC down.
    bank = deltas["bank_swap_funding+50bp"]
    assert bank.npv_borrower_cost_delta == pytest.approx(0.0, abs=1e-9)
    assert bank.npv_bank_net_margin_delta < 0
    assert bank.capital_weighted_raroc_bp_delta < 0


# ──────────────────────────────────────────────────────────────────────
# Public-surface smoke
# ──────────────────────────────────────────────────────────────────────


def test_scenario_run_property_accessors():
    """ScenarioRun exposes the headline aggregates as properties."""
    cfg, deal, schedule, discount, _ = make_inputs()
    runner = ScenarioRunner(config=cfg)
    run = runner.run_base(deal, schedule, discount)
    assert run.npv_borrower_cost == run.aggregates.npv_borrower_cost
    assert run.npv_bank_net_margin == run.aggregates.npv_bank_net_margin
    assert run.effective_spread_bp == run.aggregates.effective_spread_bp
    assert run.capital_weighted_raroc == run.aggregates.capital_weighted_raroc
    assert run.avg_raroc == run.aggregates.avg_raroc


def test_scenario_context_replace_first_returns_new_context():
    """ScenarioContext.replace_first does not mutate the original context."""
    deal = RAROCInput(spread=0.015, rating="Baa2")
    schedule = Schedule.single_period(
        commitment=10_000_000, avg_drawn=10_000_000,
        residual_maturity_years=1.0, start=date(2026, 1, 1),
    )
    seg = ScenarioSegment(
        deal=deal, schedule=schedule,
        discount=DiscountSpec(), config=EngineConfig(),
    )
    ctx = ScenarioContext(segments=[seg])

    new_ctx = ctx.replace_first(t_offset_years=2.5)
    assert new_ctx.segments[0].t_offset_years == 2.5
    assert ctx.segments[0].t_offset_years == 0.0  # original untouched
