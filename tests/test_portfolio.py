"""Tests for raroc_engine.portfolio.

Acceptance criteria (PLAN Task 2.1):

1. **Portfolio with 10 facilities across 5 banks produces correct
   concentration metrics** — bank/country/product splits sum to 100% and
   match the underlying EAD weights.
2. **Reallocation respects a 30% per-bank cap** — every bank allocation
   in an ``optimal`` result has ``pct ≤ 30.0``.
3. **Infeasibility surfaces cleanly when caps conflict** — both
   pre-validation (arithmetic caps) and optimizer-side infeasibility
   produce :class:`ReallocationResult` with ``status="infeasible"`` and
   a populated ``error`` message.

Plus supporting checks: facility-id handling, cache invalidation,
wallet RAROC weighting, single-period parity, currency/product
concentration buckets.

Tests inject country explicitly on every :class:`Facility` so they do
not depend on premium :data:`BANK_PROFILES` being loaded in CI.
"""

from __future__ import annotations

from datetime import date
from dataclasses import replace

import pytest

from raroc_engine import (
    ConcentrationCaps,
    ConcentrationView,
    Facility,
    Portfolio,
    RAROCInput,
    ReallocationResult,
    Schedule,
    WalletAggregate,
)
from raroc_engine.banks import BANK_PROFILES


START = date(2026, 1, 1)

# Five-bank universe used by the acceptance test. Free banks (always
# loaded) are paired with explicit country so the test never relies on
# premium data being available.
FIVE_BANKS = [
    ("bnp_paribas", "France"),
    ("hsbc", "United Kingdom"),
    ("deutsche_bank", "Germany"),
    ("jp_morgan", "United States"),
    ("santander_local", "Spain"),  # synthetic — keeps the test independent of premium
]


# ── Helpers ─────────────────────────────────────────────────────────


def make_deal(
    name: str,
    *,
    volume: float = 10_000_000,
    drawn_pct: float = 0.8,
    maturity_months: float = 60,
    spread: float = 0.015,
    rating: str = "Baa2",
    product: str = "mlt_credit",
) -> RAROCInput:
    return RAROCInput(
        operation=name,
        product_type=product,
        average_volume=volume,
        average_drawn=volume * drawn_pct,
        initial_volume=volume,
        initial_drawn=volume * drawn_pct,
        initial_maturity=maturity_months,
        residual_maturity=maturity_months,
        spread=spread,
        commitment_fee=0.001,
        rating=rating,
        confirmed=True,
    )


def make_facility(
    name: str,
    bank: str,
    country: str,
    *,
    volume: float = 10_000_000,
    product: str = "mlt_credit",
    currency: str = "EUR",
    spread: float = 0.015,
) -> Facility:
    deal = make_deal(name, volume=volume, product=product, spread=spread)
    return Facility(
        deal=deal,
        schedule=Schedule.from_raroc_input(deal, start=START),
        bank=bank,
        country=country,
        currency=currency,
    )


def build_10_across_5_banks() -> Portfolio:
    """Acceptance fixture: 10 equally-sized facilities, 2 per bank."""
    facilities = []
    for i in range(10):
        bank, country = FIVE_BANKS[i % 5]
        facilities.append(
            make_facility(
                f"Deal {i + 1}", bank=bank, country=country, volume=10_000_000,
            )
        )
    return Portfolio(facilities)


# ──────────────────────────────────────────────────────────────────
# Acceptance criterion 1 — concentration on 10 facilities / 5 banks
# ──────────────────────────────────────────────────────────────────


def test_acceptance_concentration_10_facilities_5_banks():
    """Equal-size facilities → equal-share concentration (20% each)."""
    p = build_10_across_5_banks()
    assert len(p) == 10

    conc: ConcentrationView = p.concentration()

    # All five banks at 20% each
    assert set(conc.by_bank.keys()) == {b for b, _ in FIVE_BANKS}
    for bk, pct in conc.by_bank.items():
        assert pct == pytest.approx(0.20, abs=1e-9), f"{bk} != 20%"
    assert sum(conc.by_bank.values()) == pytest.approx(1.0, abs=1e-9)

    # All five countries at 20% each
    assert set(conc.by_country.keys()) == {c for _, c in FIVE_BANKS}
    for c, pct in conc.by_country.items():
        assert pct == pytest.approx(0.20, abs=1e-9), f"{c} != 20%"

    # Single product → 100% concentration
    assert conc.by_product == {"mlt_credit": pytest.approx(1.0, abs=1e-9)}
    assert conc.by_currency == {"EUR": pytest.approx(1.0, abs=1e-9)}

    # Aggregate exposure adds up
    total_exp = conc.total_exposure
    assert total_exp > 0
    assert p.total_exposure == pytest.approx(total_exp, rel=1e-12)


def test_concentration_unequal_facility_sizes():
    """Uneven sizes → buckets weighted by EAD, not by row count.

    1 large facility (40M) + 4 small (10M each) → large bank carries
    50% of EAD (40 / 80) regardless of row count.
    """
    facilities = [
        make_facility("Big", bank="bnp_paribas", country="France", volume=40_000_000),
    ]
    for i in range(4):
        bank, country = FIVE_BANKS[(i + 1) % 5]
        facilities.append(make_facility(f"Small {i}", bank=bank, country=country, volume=10_000_000))

    p = Portfolio(facilities)
    conc = p.concentration()

    # The big facility's bank carries 40M / 80M = 50% on EAD basis.
    # Exposure is not 1:1 with volume (EAD depends on confirmed/product), so
    # we compare the actual exposures from the engine.
    rows = p.results()
    big_exp = rows[0].exposure
    total_exp = sum(r.exposure for r in rows)
    expected_pct = big_exp / total_exp
    assert conc.by_bank["bnp_paribas"] == pytest.approx(expected_pct, rel=1e-9)


def test_concentration_empty_portfolio_is_safe():
    """Empty portfolio → empty concentration view + zero total exposure."""
    p = Portfolio([])
    conc = p.concentration()
    assert conc.total_exposure == 0.0
    assert conc.by_bank == {}
    assert conc.by_country == {}
    assert conc.by_product == {}
    assert conc.by_currency == {}


def test_concentration_country_falls_back_to_bank_profiles():
    """Facility with no explicit country → resolves via BANK_PROFILES."""
    deal = make_deal("Deal")
    f = Facility(
        deal=deal,
        schedule=Schedule.from_raroc_input(deal, start=START),
        bank="bnp_paribas",  # in BANK_PROFILES → country "France"
    )
    p = Portfolio([f])
    conc = p.concentration()
    expected = BANK_PROFILES["bnp_paribas"].country
    assert expected in conc.by_country
    assert conc.by_country[expected] == pytest.approx(1.0, abs=1e-9)


def test_concentration_country_unknown_for_unmapped_bank():
    """Bank not in BANK_PROFILES + no explicit country → 'Unknown'."""
    deal = make_deal("Deal")
    f = Facility(
        deal=deal,
        schedule=Schedule.from_raroc_input(deal, start=START),
        bank="some_local_bank_not_in_profiles",
    )
    p = Portfolio([f])
    conc = p.concentration()
    assert "Unknown" in conc.by_country


def test_concentration_by_product_and_currency_multiple_buckets():
    """Mixed products + currencies → distinct buckets summing to 100%."""
    facilities = [
        make_facility("A", bank="bnp_paribas", country="France",
                      product="mlt_credit", currency="EUR"),
        make_facility("B", bank="hsbc", country="United Kingdom",
                      product="short_term_credit", currency="GBP"),
        make_facility("C", bank="jp_morgan", country="United States",
                      product="short_term_credit", currency="USD"),
    ]
    p = Portfolio(facilities)
    conc = p.concentration()

    assert set(conc.by_product.keys()) == {"mlt_credit", "short_term_credit"}
    assert sum(conc.by_product.values()) == pytest.approx(1.0, abs=1e-9)
    assert set(conc.by_currency.keys()) == {"EUR", "GBP", "USD"}
    assert sum(conc.by_currency.values()) == pytest.approx(1.0, abs=1e-9)


# ──────────────────────────────────────────────────────────────────
# Acceptance criterion 2 — reallocation respects 30% bank cap
# ──────────────────────────────────────────────────────────────────


def test_acceptance_reallocate_respects_30pct_bank_cap():
    """10 equal-size facilities, 4 free banks, 30% cap → every bank ≤ 30%."""
    free_keys = [k for k, p in BANK_PROFILES.items() if p.tier == "free"]
    assert len(free_keys) >= 4, "free bank tier must include ≥ 4 banks"

    facilities = []
    for i in range(10):
        # Start them all at the same bank — the optimizer's job is to
        # spread them out under the 30% cap.
        facilities.append(
            make_facility(
                f"Deal {i + 1}",
                bank=free_keys[0],
                country=BANK_PROFILES[free_keys[0]].country,
                volume=10_000_000,
            )
        )
    p = Portfolio(facilities)

    result = p.reallocate(
        ConcentrationCaps(
            max_bank_pct=0.30,
            min_banks=3,
            # 4 free banks each in their own region, so the regional
            # cap has to be relaxed enough to fit a 30% bank cap.
            max_region_pct=0.80,
        ),
        bank_universe=free_keys[:4],
    )

    assert result.is_feasible, f"expected optimal, got {result.status}: {result.error}"
    assert result.summary["banks_used"] >= 3

    for alloc in result.bank_allocations:
        # ``pct`` is returned as a percentage (0-100) by the optimizer.
        assert alloc["pct"] <= 30.0 + 1e-6, (
            f"bank {alloc['bank_key']} got {alloc['pct']}% — exceeds 30% cap"
        )

    # Every facility must be assigned exactly once.
    assigned_ids = {row["facility_id"] for row in result.assignments}
    assert len(assigned_ids) == len(facilities)
    assert assigned_ids == {f.facility_id for f in p.facilities}


# ──────────────────────────────────────────────────────────────────
# Acceptance criterion 3 — infeasibility surfacing
# ──────────────────────────────────────────────────────────────────


def test_acceptance_infeasibility_when_caps_conflict_arithmetic():
    """max_bank_pct × |universe| < 100% → fast-fail with explanation.

    4 banks × 15% = 60% < 100% — no allocation can cover total exposure,
    and the optimizer should never be invoked. We check both the
    ``infeasible`` status and that the error message names the
    arithmetic shortfall.
    """
    free_keys = [k for k, p in BANK_PROFILES.items() if p.tier == "free"][:4]
    facilities = [
        make_facility(
            f"Deal {i + 1}",
            bank=free_keys[i % 4],
            country=BANK_PROFILES[free_keys[i % 4]].country,
        )
        for i in range(8)
    ]
    p = Portfolio(facilities)
    result = p.reallocate(
        ConcentrationCaps(max_bank_pct=0.15, min_banks=3, max_region_pct=0.80),
        bank_universe=free_keys,
    )
    assert not result.is_feasible
    assert result.status == "infeasible"
    assert result.error is not None
    # The error message names the percentage shortfall in human terms.
    assert "max_bank_pct" in result.error
    assert "100%" in result.error


def test_acceptance_infeasibility_when_min_banks_exceeds_universe():
    """min_banks > |universe| → fast-fail before the MILP is invoked."""
    free_keys = [k for k, p in BANK_PROFILES.items() if p.tier == "free"][:4]
    facilities = [
        make_facility(f"Deal {i}",
                      bank=free_keys[i % 4],
                      country=BANK_PROFILES[free_keys[i % 4]].country)
        for i in range(5)
    ]
    p = Portfolio(facilities)

    result = p.reallocate(
        ConcentrationCaps(max_bank_pct=0.40, min_banks=10, max_region_pct=0.80),
        bank_universe=free_keys,
    )
    assert not result.is_feasible
    assert "min_banks" in (result.error or "")


def test_infeasibility_when_facility_exceeds_per_bank_cap():
    """One huge facility > 30% of total → no bank can absorb it under the cap."""
    free_keys = [k for k, p in BANK_PROFILES.items() if p.tier == "free"][:4]
    facilities = [
        # One 80M facility — 80 / (80 + 4 × 10) = ~67% of total. With a 30%
        # bank cap, no single bank can hold it, and you can't split a
        # facility (assignment is 1-to-1 in the MILP).
        make_facility("Big", bank=free_keys[0],
                      country=BANK_PROFILES[free_keys[0]].country,
                      volume=80_000_000),
    ] + [
        make_facility(f"Small {i}", bank=free_keys[i % 4],
                      country=BANK_PROFILES[free_keys[i % 4]].country,
                      volume=10_000_000)
        for i in range(4)
    ]
    p = Portfolio(facilities)

    result = p.reallocate(
        ConcentrationCaps(max_bank_pct=0.30, min_banks=2, max_region_pct=0.80),
        bank_universe=free_keys,
    )
    assert not result.is_feasible
    assert "exceeds" in (result.error or "").lower()


def test_infeasibility_when_locked_facility_unknown():
    """Lock referencing a non-existent facility_id → infeasible with hint."""
    free_keys = [k for k, p in BANK_PROFILES.items() if p.tier == "free"][:4]
    p = Portfolio([make_facility("Only deal", bank=free_keys[0],
                                 country=BANK_PROFILES[free_keys[0]].country)])
    result = p.reallocate(
        ConcentrationCaps(
            max_bank_pct=0.40, min_banks=1, max_region_pct=1.0,
            locked={"facility-99": free_keys[0]},  # not in the portfolio
        ),
        bank_universe=free_keys,
    )
    assert not result.is_feasible
    assert "facility-99" in (result.error or "") or "Locked" in (result.error or "")


def test_reallocate_locked_facility_pins_assignment():
    """Lock pins a facility's bank; optimizer must honour it."""
    free_keys = [k for k, p in BANK_PROFILES.items() if p.tier == "free"][:4]
    facilities = [
        make_facility(f"Deal {i + 1}", bank=free_keys[0],
                      country=BANK_PROFILES[free_keys[0]].country,
                      volume=10_000_000)
        for i in range(6)
    ]
    p = Portfolio(facilities)
    pinned_to = free_keys[2]
    pinned_id = p.facilities[0].facility_id  # "Deal 1" — derived from operation
    result = p.reallocate(
        ConcentrationCaps(
            max_bank_pct=0.35, min_banks=3, max_region_pct=0.80,
            locked={pinned_id: pinned_to},
        ),
        bank_universe=free_keys,
    )
    assert result.is_feasible, f"expected optimal, got {result.error}"
    # Find the pinned facility in assignments and verify its bank
    pinned_row = next(r for r in result.assignments if r["facility_id"] == pinned_id)
    assert pinned_row["bank_key"] == pinned_to
    assert pinned_row.get("locked") is True


def test_reallocate_empty_portfolio_is_infeasible():
    """Empty portfolio → not 'optimal'; clear error."""
    p = Portfolio([])
    result = p.reallocate(ConcentrationCaps())
    assert not result.is_feasible
    assert "empty" in (result.error or "").lower()


def test_reallocate_no_default_universe_when_banks_not_in_profiles():
    """All facilities' banks are free-form labels → empty default universe → infeasible."""
    facilities = [
        make_facility(f"Deal {i}", bank=f"local_bank_{i}", country="France")
        for i in range(3)
    ]
    p = Portfolio(facilities)
    result = p.reallocate(ConcentrationCaps())  # no bank_universe → falls back to profiles
    assert not result.is_feasible
    assert "universe" in (result.error or "").lower()


def test_reallocate_default_universe_uses_in_portfolio_bank_profiles():
    """No explicit ``bank_universe`` → uses distinct in-portfolio BANK_PROFILES keys."""
    free_keys = [k for k, p in BANK_PROFILES.items() if p.tier == "free"][:4]
    facilities = []
    for i in range(8):
        facilities.append(
            make_facility(f"Deal {i + 1}",
                          bank=free_keys[i % 4],
                          country=BANK_PROFILES[free_keys[i % 4]].country)
        )
    p = Portfolio(facilities)
    # Don't pass bank_universe — it should default to the 4 free banks.
    result = p.reallocate(
        ConcentrationCaps(max_bank_pct=0.40, min_banks=3, max_region_pct=0.80)
    )
    assert result.is_feasible, f"expected optimal, got {result.error}"


# ──────────────────────────────────────────────────────────────────
# Wallet RAROC + supporting checks
# ──────────────────────────────────────────────────────────────────


def test_wallet_raroc_single_facility_matches_facility_aggregate():
    """1-facility portfolio: wallet_raroc collapses to that facility's capital-weighted RAROC."""
    deal = make_deal("Solo")
    f = Facility(
        deal=deal,
        schedule=Schedule.from_raroc_input(deal, start=START),
        bank="bnp_paribas",
        country="France",
    )
    p = Portfolio([f])
    res = p.result_for(f.facility_id)
    wa = p.wallet_raroc()
    assert wa.n_facilities == 1
    assert wa.wallet_raroc == pytest.approx(res.capital_weighted_raroc, rel=1e-12)
    assert wa.avg_raroc == pytest.approx(res.avg_raroc, rel=1e-12)
    assert wa.total_exposure == pytest.approx(res.exposure, rel=1e-12)


def test_wallet_raroc_two_identical_facilities_collapses_to_one():
    """Two identical facilities → wallet_raroc equals each facility's RAROC."""
    deal = make_deal("Twin")
    f1 = Facility(deal=deal,
                  schedule=Schedule.from_raroc_input(deal, start=START),
                  bank="bnp_paribas", country="France", facility_id="t1")
    f2 = Facility(deal=replace(deal),
                  schedule=Schedule.from_raroc_input(deal, start=START),
                  bank="hsbc", country="United Kingdom", facility_id="t2")
    p = Portfolio([f1, f2])
    wa = p.wallet_raroc()
    single = p.result_for("t1").capital_weighted_raroc
    assert wa.wallet_raroc == pytest.approx(single, rel=1e-12)
    assert wa.avg_raroc == pytest.approx(p.result_for("t1").avg_raroc, rel=1e-12)


def test_wallet_raroc_weighted_by_fpe_years():
    """Two facilities with different sizes → wallet_raroc weighted by FPE-years.

    Reproduces the FPE-weighted formula in :class:`Portfolio.wallet_raroc`
    by hand and checks the engine matches.
    """
    deal_a = make_deal("A", volume=20_000_000)
    deal_b = make_deal("B", volume=5_000_000, spread=0.025)
    fa = Facility(deal=deal_a, schedule=Schedule.from_raroc_input(deal_a, start=START),
                  bank="bnp_paribas", country="France", facility_id="A")
    fb = Facility(deal=deal_b, schedule=Schedule.from_raroc_input(deal_b, start=START),
                  bank="hsbc", country="United Kingdom", facility_id="B")
    p = Portfolio([fa, fb])
    ra = p.result_for("A")
    rb = p.result_for("B")
    wa = p.wallet_raroc()

    total_fpe_years = ra.fpe_years + rb.fpe_years
    expected_wallet = (
        ra.capital_weighted_raroc * ra.fpe_years
        + rb.capital_weighted_raroc * rb.fpe_years
    ) / total_fpe_years
    assert wa.wallet_raroc == pytest.approx(expected_wallet, rel=1e-12)
    assert wa.total_fpe_years == pytest.approx(total_fpe_years, rel=1e-12)


def test_wallet_raroc_empty_portfolio_is_zero():
    p = Portfolio([])
    wa = p.wallet_raroc()
    assert wa.n_facilities == 0
    assert wa.total_exposure == 0.0
    assert wa.wallet_raroc == 0.0
    assert wa.avg_raroc == 0.0


# ──────────────────────────────────────────────────────────────────
# Facility / Portfolio mechanics
# ──────────────────────────────────────────────────────────────────


def test_add_facility_assigns_positional_id_when_blank():
    """``facility_id`` is filled in on add when both id and deal.operation are blank."""
    deal = RAROCInput(product_type="mlt_credit", average_volume=10_000_000,
                      average_drawn=8_000_000, initial_maturity=60,
                      residual_maturity=60, spread=0.01, rating="Baa2")
    f = Facility(deal=deal, schedule=Schedule.from_raroc_input(deal, start=START),
                 bank="bnp_paribas", country="France")
    assert f.facility_id == ""  # empty before add (no operation, no explicit id)

    p = Portfolio([f])
    assert p.facilities[0].facility_id == "facility-1"


def test_add_facility_uses_deal_operation_when_id_blank():
    """When ``facility_id`` is blank but deal.operation is set, that becomes the id."""
    deal = make_deal("My Loan")
    f = Facility(deal=deal, schedule=Schedule.from_raroc_input(deal, start=START),
                 bank="bnp_paribas", country="France")
    assert f.facility_id == "My Loan"
    p = Portfolio([f])
    assert p.facilities[0].facility_id == "My Loan"


def test_add_facility_rejects_duplicate_id():
    deal = make_deal("X")
    f1 = Facility(deal=deal, schedule=Schedule.from_raroc_input(deal, start=START),
                  bank="bnp_paribas", country="France", facility_id="same")
    f2 = Facility(deal=deal, schedule=Schedule.from_raroc_input(deal, start=START),
                  bank="hsbc", country="UK", facility_id="same")
    p = Portfolio([f1])
    with pytest.raises(ValueError, match="duplicate facility_id"):
        p.add_facility(f2)


def test_remove_facility_drops_cache_and_returns_row():
    facilities = [
        make_facility(f"Deal {i}", bank=FIVE_BANKS[i][0], country=FIVE_BANKS[i][1])
        for i in range(3)
    ]
    p = Portfolio(facilities)
    # Prime the cache
    _ = p.wallet_raroc()
    fid = facilities[1].facility_id
    removed = p.remove_facility(fid)
    assert removed.facility_id == fid
    assert len(p) == 2
    with pytest.raises(KeyError):
        p.get_facility(fid)


def test_invalidate_drops_cached_results():
    facilities = [make_facility(f"Deal {i}", bank=FIVE_BANKS[i][0],
                                country=FIVE_BANKS[i][1]) for i in range(3)]
    p = Portfolio(facilities)
    _ = p.wallet_raroc()
    assert len(p._results_cache) == 3
    p.invalidate()
    assert len(p._results_cache) == 0
    # Re-populate
    _ = p.wallet_raroc()
    assert len(p._results_cache) == 3
    # Targeted invalidate
    p.invalidate(facilities[0].facility_id)
    assert facilities[0].facility_id not in p._results_cache
    assert facilities[1].facility_id in p._results_cache


def test_facility_from_deal_builds_length_1_schedule():
    deal = make_deal("Quick", maturity_months=60)
    f = Facility.from_deal(deal, bank="bnp_paribas", country="France")
    assert len(f.schedule.periods) == 1
    assert f.schedule.periods[0].dt_years == pytest.approx(1.0)
    assert f.bank == "bnp_paribas"
    assert f.country == "France"
    assert f.maturity_years == pytest.approx(1.0)


def test_facility_maturity_years_from_multi_period_schedule():
    """maturity_years sums dt across periods (5y RCF → 5 years)."""
    deal = make_deal("RCF", volume=50_000_000, maturity_months=60)
    sched = Schedule.bullet_rcf_with_cleandown(
        commitment=50_000_000,
        drawn_levels=[(40_000_000, 3), (20_000_000, 2)],
        start=START,
    )
    f = Facility(deal=deal, schedule=sched, bank="bnp_paribas", country="France")
    assert f.maturity_years == pytest.approx(5.0)
    assert f.commitment == pytest.approx(50_000_000)


def test_portfolio_iteration_and_len():
    facilities = [make_facility(f"Deal {i}", bank=FIVE_BANKS[i][0],
                                country=FIVE_BANKS[i][1]) for i in range(5)]
    p = Portfolio(facilities)
    assert len(p) == 5
    iterated = [f.facility_id for f in p]
    assert iterated == [f.facility_id for f in facilities]


def test_reallocation_result_is_immutable_dataclass():
    """ReallocationResult is frozen — accidental mutation raises."""
    res = ReallocationResult(status="optimal")
    with pytest.raises(Exception):
        res.status = "infeasible"  # type: ignore[misc]


def test_concentration_view_is_immutable_dataclass():
    p = build_10_across_5_banks()
    conc = p.concentration()
    assert isinstance(conc, ConcentrationView)
    with pytest.raises(Exception):
        conc.total_exposure = 0.0  # type: ignore[misc]


def test_wallet_aggregate_is_immutable_dataclass():
    p = build_10_across_5_banks()
    wa = p.wallet_raroc()
    assert isinstance(wa, WalletAggregate)
    with pytest.raises(Exception):
        wa.wallet_raroc = 0.0  # type: ignore[misc]
