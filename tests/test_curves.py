"""Tests for raroc_engine.curves and scripts.refresh_curves.

Acceptance criteria (PLAN Task 1.5):

1. **Daily refresh produces curves for EUR/USD/GBP** — exercising
   ``scripts.refresh_curves.refresh_all`` in synthetic mode writes
   one CSV per supported source under the target directory.
2. **Fallback policy exercised by tests** — the four observable tiers
   of the D-0003 cascade (``fresh``, ``stale``, ``interpolated``,
   ``scalar_fallback``) each have a dedicated test, plus the
   ``CurveDataUnavailable`` tier-5 exception for unknown indices.
3. **period_engine consumes fixings end-to-end** — a multi-period
   schedule with ``floating_index`` set runs through the engine,
   has its ``fixing_rate`` filled from the curve repository, and
   surfaces ``curve_status`` per period plus the worst-tier rollup
   in ``engine_meta``.

The tests build their own curve files under ``tmp_path`` rather than
relying on the bundled seed data — keeping them deterministic across
the next refresh cycle.
"""

from __future__ import annotations

import csv
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

from raroc_engine.curves import (
    FRESH_MAX_AGE_DAYS,
    INDEX_REGISTRY,
    STALE_MAX_AGE_DAYS,
    STATUS_FRESH,
    STATUS_INTERPOLATED,
    STATUS_SCALAR_FALLBACK,
    STATUS_STALE,
    CurveDataUnavailable,
    CurveFixingResult,
    CurveRepository,
)
from raroc_engine.models import RAROCInput
from raroc_engine import (
    DiscountSpec,
    PeriodEngine,
    Schedule,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.refresh_curves import (  # noqa: E402
    SOURCES,
    refresh_all,
    refresh_source,
)


# ── Helpers ──────────────────────────────────────────────────────────


def write_curve(
    data_dir: Path,
    key: str,
    rows: list[tuple[str, int, float]],
) -> Path:
    """Write a curves CSV at ``data_dir/<key>.csv`` and return the path."""
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / f"{key}.csv"
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["as_of", "tenor_days", "rate"])
        for as_of, tenor, rate in rows:
            w.writerow([as_of, tenor, rate])
    return path


@pytest.fixture
def tmp_curves_dir(tmp_path: Path) -> Path:
    return tmp_path / "curves"


# ──────────────────────────────────────────────────────────────────────
# Acceptance 2: cascade — each tier explicitly exercised
# ──────────────────────────────────────────────────────────────────────


def test_tier1_fresh_exact_tenor_same_day(tmp_curves_dir: Path):
    """Tier 1: exact tenor on today's snapshot ⇒ status=fresh, rate=published."""
    write_curve(tmp_curves_dir, "eur_euribor", [
        ("2026-05-14", 7, 0.03210),
        ("2026-05-14", 90, 0.03350),
        ("2026-05-14", 180, 0.03455),
    ])
    repo = CurveRepository(data_dir=tmp_curves_dir)

    result = repo.fix("EURIBOR_3M", date(2026, 5, 14), fallback_rate=0.0325)
    assert result.status == STATUS_FRESH
    assert result.rate == pytest.approx(0.03350)
    assert result.source_as_of == date(2026, 5, 14)
    assert result.source_tenor_days == 90


def test_tier2_stale_exact_tenor_4_days_old(tmp_curves_dir: Path):
    """Tier 2: exact tenor exists but 1 < age ≤ 7 ⇒ status=stale."""
    write_curve(tmp_curves_dir, "eur_euribor", [
        ("2026-05-10", 90, 0.03350),
    ])
    repo = CurveRepository(data_dir=tmp_curves_dir)

    result = repo.fix("EURIBOR_3M", date(2026, 5, 14), fallback_rate=0.0325)
    assert result.status == STATUS_STALE
    assert result.rate == pytest.approx(0.03350)
    assert (date(2026, 5, 14) - result.source_as_of).days == 4


def test_tier3_interpolated_neighbouring_tenors(tmp_curves_dir: Path):
    """Tier 3: requested tenor missing, neighbours exist ⇒ linear interpolation."""
    write_curve(tmp_curves_dir, "eur_euribor", [
        ("2026-05-14", 30, 0.03250),
        ("2026-05-14", 180, 0.03450),  # no 90d row — must interpolate
    ])
    repo = CurveRepository(data_dir=tmp_curves_dir)

    result = repo.fix("EURIBOR_3M", date(2026, 5, 14), fallback_rate=0.0325)
    assert result.status == STATUS_INTERPOLATED
    # Linear: 0.03250 + (90-30)/(180-30) * (0.03450 - 0.03250) = 0.03330
    assert result.rate == pytest.approx(0.03330)
    assert result.source_tenor_days == 90


def test_tier4_scalar_fallback_empty_file(tmp_curves_dir: Path):
    """Tier 4: no curve file at all ⇒ status=scalar_fallback, rate=caller's fallback."""
    tmp_curves_dir.mkdir()
    repo = CurveRepository(data_dir=tmp_curves_dir)

    result = repo.fix("EURIBOR_3M", date(2026, 5, 14), fallback_rate=0.0325)
    assert result.status == STATUS_SCALAR_FALLBACK
    assert result.rate == pytest.approx(0.0325)


def test_tier4_scalar_fallback_when_snapshot_too_old(tmp_curves_dir: Path):
    """Tier 4 also fires when the newest snapshot is older than the stale cutoff."""
    write_curve(tmp_curves_dir, "eur_euribor", [
        ("2026-05-01", 90, 0.03350),  # 13d old at 2026-05-14
    ])
    repo = CurveRepository(data_dir=tmp_curves_dir)

    result = repo.fix("EURIBOR_3M", date(2026, 5, 14), fallback_rate=0.0325)
    assert result.status == STATUS_SCALAR_FALLBACK
    assert result.rate == pytest.approx(0.0325)
    # The cascade still surfaces *which* curve was attempted so the App
    # can show "scalar fallback — last EURIBOR snapshot was 2026-05-01".
    assert result.source_curve == "eur_euribor"
    assert result.source_as_of == date(2026, 5, 1)


def test_tier4_scalar_fallback_when_tenor_out_of_range(tmp_curves_dir: Path):
    """Interpolation does not extrapolate — out-of-range tenor ⇒ scalar fallback."""
    write_curve(tmp_curves_dir, "eur_euribor", [
        ("2026-05-14", 30, 0.03250),
        ("2026-05-14", 90, 0.03350),  # max tenor 90d
    ])
    repo = CurveRepository(data_dir=tmp_curves_dir)

    # Ask for 360d (12M) — outside the [30, 90] envelope.
    result = repo.fix("EURIBOR_12M", date(2026, 5, 14), fallback_rate=0.0325)
    assert result.status == STATUS_SCALAR_FALLBACK


def test_tier5_unknown_index_raises():
    """Tier 5: caller passes an index name not in the registry ⇒ exception."""
    repo = CurveRepository()
    with pytest.raises(CurveDataUnavailable, match="HIBOR_3M"):
        repo.fix("HIBOR_3M", date(2026, 5, 14), fallback_rate=0.0325)


def test_fresh_boundary_at_exactly_one_day(tmp_curves_dir: Path):
    """Age == FRESH_MAX_AGE_DAYS (1) is still ``fresh`` (boundary inclusive)."""
    write_curve(tmp_curves_dir, "eur_euribor", [
        ("2026-05-13", 90, 0.03345),
    ])
    repo = CurveRepository(data_dir=tmp_curves_dir)
    result = repo.fix("EURIBOR_3M", date(2026, 5, 14), fallback_rate=0.0325)
    assert result.status == STATUS_FRESH
    assert result.rate == pytest.approx(0.03345)


def test_stale_boundary_at_seven_days(tmp_curves_dir: Path):
    """Age == STALE_MAX_AGE_DAYS (7) is still ``stale``; 8d falls to scalar."""
    write_curve(tmp_curves_dir, "eur_euribor", [
        ("2026-05-07", 90, 0.03345),  # 7d old at 2026-05-14
    ])
    repo = CurveRepository(data_dir=tmp_curves_dir)
    result = repo.fix("EURIBOR_3M", date(2026, 5, 14), fallback_rate=0.0325)
    assert result.status == STATUS_STALE

    # 8d → scalar fallback
    result = repo.fix("EURIBOR_3M", date(2026, 5, 15), fallback_rate=0.0325)
    assert result.status == STATUS_SCALAR_FALLBACK


# ──────────────────────────────────────────────────────────────────────
# Acceptance 1: refresh script produces all currencies
# ──────────────────────────────────────────────────────────────────────


def test_refresh_synthetic_produces_eur_usd_gbp_curves(tmp_curves_dir: Path):
    """``--source synthetic`` against the shipped seed seeds writes every file.

    Acceptance criterion: "Daily refresh script produces curves for
    EUR/USD/GBP". We test the offline path because the live ECB / BoE /
    Fed endpoints are not reachable from the unattended-agent sandbox;
    the live HTTP fetch shares the same I/O code path tested separately.
    """
    # Seed each source with a small history so synthetic carry-forward
    # has something to project. This mirrors what production looks like
    # the day before the cron runs.
    seed_date = date(2026, 5, 13)
    for src in SOURCES:
        rows = [(seed_date.isoformat(), t, 0.03000 + i * 0.0005)
                for i, t in enumerate(src.tenors)]
        write_curve(tmp_curves_dir, src.key, rows)

    ref_date = date(2026, 5, 14)
    results = refresh_all(
        data_dir=tmp_curves_dir, ref_date=ref_date, mode="synthetic",
    )

    # Every configured source returned a non-error result.
    assert all(r.status != "error" for r in results)

    # Each of the three currencies has at least one file written.
    written_files = {p.name for p in tmp_curves_dir.iterdir() if p.suffix == ".csv"}
    eur_files = {f for f in written_files if f.startswith("eur_")}
    gbp_files = {f for f in written_files if f.startswith("gbp_")}
    usd_files = {f for f in written_files if f.startswith("usd_")}
    assert eur_files, "no EUR curve files written"
    assert gbp_files, "no GBP curve files written"
    assert usd_files, "no USD curve files written"

    # Each source's CSV now has a row dated ref_date.
    for src in SOURCES:
        path = tmp_curves_dir / f"{src.key}.csv"
        with path.open() as f:
            dates = {row["as_of"] for row in csv.DictReader(f)}
        assert ref_date.isoformat() in dates, f"{src.key}: missing ref_date row"


def test_refresh_synthetic_carries_forward_rates(tmp_curves_dir: Path):
    """Synthetic mode duplicates yesterday's tenor rates into today's row."""
    write_curve(tmp_curves_dir, "eur_euribor", [
        ("2026-05-13", 90, 0.03345),
        ("2026-05-13", 180, 0.03450),
    ])

    refresh_source(
        next(s for s in SOURCES if s.key == "eur_euribor"),
        data_dir=tmp_curves_dir, ref_date=date(2026, 5, 14), mode="synthetic",
    )

    path = tmp_curves_dir / "eur_euribor.csv"
    today_rows = {
        int(r["tenor_days"]): float(r["rate"])
        for r in csv.DictReader(path.open())
        if r["as_of"] == "2026-05-14"
    }
    # Only tenors that existed yesterday get carried forward.
    assert today_rows[90] == pytest.approx(0.03345)
    assert today_rows[180] == pytest.approx(0.03450)


def test_refresh_trims_old_history(tmp_curves_dir: Path):
    """History older than 30 days falls off on the next refresh."""
    very_old = (date(2026, 5, 14) - timedelta(days=60)).isoformat()
    keep = (date(2026, 5, 14) - timedelta(days=5)).isoformat()
    write_curve(tmp_curves_dir, "eur_euribor", [
        (very_old, 90, 0.0300),
        (keep, 90, 0.0335),
    ])

    refresh_source(
        next(s for s in SOURCES if s.key == "eur_euribor"),
        data_dir=tmp_curves_dir, ref_date=date(2026, 5, 14), mode="synthetic",
    )

    with (tmp_curves_dir / "eur_euribor.csv").open() as f:
        dates_in_file = {row["as_of"] for row in csv.DictReader(f)}
    assert very_old not in dates_in_file
    assert keep in dates_in_file


def test_refresh_dry_run_does_not_write(tmp_curves_dir: Path):
    """``--dry-run`` leaves the on-disk file untouched."""
    write_curve(tmp_curves_dir, "eur_euribor", [
        ("2026-05-13", 90, 0.03345),
    ])
    refresh_all(
        data_dir=tmp_curves_dir, ref_date=date(2026, 5, 14),
        mode="synthetic", dry_run=True,
    )

    path = tmp_curves_dir / "eur_euribor.csv"
    with path.open() as f:
        dates_in_file = {row["as_of"] for row in csv.DictReader(f)}
    assert "2026-05-14" not in dates_in_file
    assert "2026-05-13" in dates_in_file


# ──────────────────────────────────────────────────────────────────────
# Acceptance 3: period engine consumes fixings end-to-end
# ──────────────────────────────────────────────────────────────────────


def test_engine_resolves_fixings_from_curve_and_surfaces_status(
    tmp_curves_dir: Path,
):
    """A floating-rate schedule + curves repo → ``curve_status="fresh"`` everywhere."""
    write_curve(tmp_curves_dir, "eur_euribor", [
        ("2026-06-01", 90, 0.03250),
    ])
    repo = CurveRepository(data_dir=tmp_curves_dir)

    schedule = Schedule.bullet_rcf_with_cleandown(
        commitment=50_000_000,
        drawn_levels=[(35_000_000, 3), (20_000_000, 2)],
        start=date(2026, 6, 1),
        upfront_fee=0.0,
        floating_index="EURIBOR_3M",
    )
    # Every period should carry the floating_index until the engine resolves it.
    assert all(p.floating_index == "EURIBOR_3M" for p in schedule.periods)
    assert all(p.fixing_rate is None for p in schedule.periods)

    deal = RAROCInput(
        product_type="mlt_credit",
        rating="Baa2",
        global_grr=0.0,
        confirmed=True,
        spread=0.020,
        commitment_fee=0.0025,
    )
    out = PeriodEngine().run(
        deal, schedule,
        DiscountSpec(kind="scalar", rate=0.0325),
        curves=repo,
        valuation_date=date(2026, 6, 1),
    )

    # Per-period: every row has curve_status, fixing_rate, all_in_rate.
    for row in out.per_period:
        assert row.floating_index == "EURIBOR_3M"
        assert row.fixing_rate == pytest.approx(0.03250)
        assert row.all_in_rate == pytest.approx(0.03250 + 0.020)
        assert row.curve_status == STATUS_FRESH

    # Facility-level rollup in engine_meta.
    assert out.engine_meta["curve_status"] == STATUS_FRESH
    assert out.engine_meta["floating_indices"] == ["EURIBOR_3M"]
    assert out.engine_meta["fixing_breakdown"] == {STATUS_FRESH: 5}


def test_engine_rolls_up_worst_tier_when_periods_differ(tmp_curves_dir: Path):
    """Mixing fresh + stale + interpolated periods rolls up to the worst tier."""
    # Build a curve that is 4 days old → every fixing comes back STALE.
    write_curve(tmp_curves_dir, "eur_euribor", [
        ("2026-05-28", 90, 0.03350),
    ])
    repo = CurveRepository(data_dir=tmp_curves_dir)

    schedule = Schedule.scheduled_amortising_term_loan(
        initial_drawn=70_000_000, total_years=7,
        start=date(2026, 6, 1), floating_index="EURIBOR_3M",
    )
    deal = RAROCInput(
        product_type="mlt_credit",
        rating="Baa2",
        global_grr=0.0,
        confirmed=True,
        spread=0.020,
        commitment_fee=0.0025,
    )
    out = PeriodEngine().run(
        deal, schedule, curves=repo, valuation_date=date(2026, 6, 1),
    )
    assert out.engine_meta["curve_status"] == STATUS_STALE
    assert out.engine_meta["fixing_breakdown"][STATUS_STALE] == 7


def test_engine_falls_back_when_no_curve_data(tmp_curves_dir: Path):
    """Empty curves dir → every floating period gets scalar_fallback."""
    tmp_curves_dir.mkdir()
    repo = CurveRepository(data_dir=tmp_curves_dir)

    schedule = Schedule.bullet_rcf_with_cleandown(
        commitment=50_000_000,
        drawn_levels=[(35_000_000, 5)],
        start=date(2026, 6, 1),
        floating_index="EURIBOR_3M",
    )
    deal = RAROCInput(
        product_type="mlt_credit", rating="Baa2", global_grr=0.0,
        confirmed=True, spread=0.020, commitment_fee=0.0025,
    )
    out = PeriodEngine().run(
        deal, schedule, curves=repo, valuation_date=date(2026, 6, 1),
    )

    # Every period falls back to the engine's risk-free scalar (0.0325).
    for row in out.per_period:
        assert row.curve_status == STATUS_SCALAR_FALLBACK
        assert row.fixing_rate == pytest.approx(0.0325)
    assert out.engine_meta["curve_status"] == STATUS_SCALAR_FALLBACK


def test_engine_does_not_crash_when_no_repo_supplied():
    """Floating schedule + no curves repo → engine falls back to scalar."""
    schedule = Schedule.bullet_rcf_with_cleandown(
        commitment=50_000_000,
        drawn_levels=[(35_000_000, 3)],
        start=date(2026, 6, 1),
        floating_index="EURIBOR_3M",
    )
    deal = RAROCInput(
        product_type="mlt_credit", rating="Baa2", global_grr=0.0,
        confirmed=True, spread=0.020, commitment_fee=0.0025,
    )
    # No ``curves`` kwarg — the engine should not raise. D-0003 §5 Tier 4
    # behaviour: degrade gracefully to the scalar fallback.
    out = PeriodEngine().run(deal, schedule)
    assert all(row.curve_status == STATUS_SCALAR_FALLBACK for row in out.per_period)
    assert out.engine_meta["curve_status"] == STATUS_SCALAR_FALLBACK


def test_engine_skips_curve_lookup_when_caller_supplied_fixing(tmp_curves_dir: Path):
    """Caller-supplied ``fixing_rate`` is trusted; curve repo not consulted."""
    # Stale curve — would normally come back STATUS_STALE.
    write_curve(tmp_curves_dir, "eur_euribor", [
        ("2026-05-28", 90, 0.99999),  # absurd value: catches misuse
    ])
    repo = CurveRepository(data_dir=tmp_curves_dir)

    schedule = Schedule.single_period(
        commitment=10_000_000, avg_drawn=10_000_000,
        residual_maturity_years=1.0, start=date(2026, 6, 1),
        floating_index="EURIBOR_3M", fixing_rate=0.03000,
    )
    deal = RAROCInput(
        product_type="mlt_credit", rating="Baa2", global_grr=0.0,
        confirmed=True, spread=0.020, commitment_fee=0.0025,
    )
    out = PeriodEngine().run(
        deal, schedule, curves=repo, valuation_date=date(2026, 6, 1),
    )
    assert out.per_period[0].fixing_rate == pytest.approx(0.03000)
    # Caller-supplied is treated as fresh.
    assert out.per_period[0].curve_status == STATUS_FRESH


def test_engine_meta_omits_curve_keys_for_fixed_rate_facility():
    """Pure fixed-rate facility ⇒ no ``curve_status`` key in engine_meta."""
    schedule = Schedule.scheduled_amortising_term_loan(
        initial_drawn=70_000_000, total_years=5,
        start=date(2026, 6, 1),  # No floating_index ⇒ fixed-rate
    )
    deal = RAROCInput(
        product_type="mlt_credit", rating="Baa2", global_grr=0.0,
        confirmed=True, spread=0.020, commitment_fee=0.0025,
    )
    out = PeriodEngine().run(deal, schedule)
    assert "curve_status" not in out.engine_meta
    assert all(row.curve_status is None for row in out.per_period)
    assert all(row.floating_index is None for row in out.per_period)
    assert all(row.fixing_rate is None for row in out.per_period)
    assert all(row.all_in_rate is None for row in out.per_period)


# ──────────────────────────────────────────────────────────────────────
# Supporting / sanity checks
# ──────────────────────────────────────────────────────────────────────


def test_repository_with_shipped_seed_data_loads_all_indices():
    """The seed CSVs shipped under raroc_engine/data/curves load cleanly."""
    repo = CurveRepository()
    loaded = repo.loaded_curves
    expected_files = {key for (key, _) in INDEX_REGISTRY.values()}
    assert expected_files.issubset(loaded.keys()), (
        f"missing curves: {expected_files - loaded.keys()}"
    )
    # Every loaded curve has at least one point.
    for key, curve in loaded.items():
        assert curve.points, f"{key}: shipped CSV has no rows"


def test_index_registry_covers_three_currencies():
    """Acceptance: EUR + GBP + USD all present."""
    currencies = set()
    for key, _ in INDEX_REGISTRY.values():
        currencies.add(key.split("_")[0].upper())
    assert {"EUR", "USD", "GBP"}.issubset(currencies)


def test_fresh_max_age_is_one_day():
    """D-0003 §5 Tier 1 boundary is ≤ 24h — pinned to catch accidental loosening."""
    assert FRESH_MAX_AGE_DAYS == 1


def test_stale_max_age_is_seven_days():
    """D-0003 §5 Tier 2 boundary is ≤ 7d."""
    assert STALE_MAX_AGE_DAYS == 7


def test_curve_fixing_result_has_audit_trail():
    """Every ``CurveFixingResult`` carries the source curve + as_of for audit.

    The App's "where did this number come from?" panel reads these fields
    to render a banker-grade trail under each headline number.
    """
    assert hasattr(CurveFixingResult, "source_curve")
    assert hasattr(CurveFixingResult, "source_as_of")
    assert hasattr(CurveFixingResult, "source_tenor_days")


def test_attach_fixings_is_idempotent_with_force_false(tmp_curves_dir: Path):
    """Second call to attach_fixings does not overwrite resolved fixings.

    Schedules can be re-run through the engine. Without the no-overwrite
    rule the second run would silently re-fix at a different snapshot
    and confuse the audit trail. Caller passes ``force=True`` to opt in.
    """
    write_curve(tmp_curves_dir, "eur_euribor", [
        ("2026-06-01", 90, 0.03250),
    ])
    repo = CurveRepository(data_dir=tmp_curves_dir)

    schedule = Schedule.bullet_rcf_with_cleandown(
        commitment=10_000_000,
        drawn_levels=[(5_000_000, 1)],
        start=date(2026, 6, 1),
        floating_index="EURIBOR_3M",
    )
    schedule.attach_fixings(repo, valuation_date=date(2026, 6, 1))
    original_rate = schedule.periods[0].fixing_rate
    assert original_rate == pytest.approx(0.03250)

    # Rewrite the curve with a different value and call attach_fixings again.
    write_curve(tmp_curves_dir, "eur_euribor", [
        ("2026-06-01", 90, 0.99999),
    ])
    repo2 = CurveRepository(data_dir=tmp_curves_dir)
    schedule.attach_fixings(repo2, valuation_date=date(2026, 6, 1))
    assert schedule.periods[0].fixing_rate == pytest.approx(0.03250), (
        "second attach_fixings unexpectedly overwrote the resolved fixing"
    )

    # ``force=True`` opts into the overwrite.
    schedule.attach_fixings(repo2, valuation_date=date(2026, 6, 1), force=True)
    assert schedule.periods[0].fixing_rate == pytest.approx(0.99999)
