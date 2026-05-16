"""Backwards-compatibility regression tests for the v1 single-period API.

These tests pin the v1 public surface to its v1 behaviour. The v2.0
release added the multi-period engine on top of v1 *without* breaking
existing v1 callers — these tests prove that contract by exercising
the v1 symbols directly.

If any of these tests fails, v1 has drifted: do not ship until either
the regression is fixed or the change is documented as a SemVer-major
break in CHANGELOG.md.

Spec: METHODOLOGY.md §1–15 (single-period), CHANGELOG.md v2.0
"Unchanged (v1 back-compat contract)" section.
"""

from __future__ import annotations

import inspect

import pytest

from raroc_engine import (
    ALL_VALID_RATINGS,
    EngineConfig,
    MOODYS_TO_SP,
    PRODUCT_DESCRIPTIONS,
    PRODUCT_TYPES,
    RATING_ORDER,
    RAROCCalculator,
    RAROCInput,
    RAROCOutput,
    Repository,
    SP_TO_MOODYS,
    normalize_rating,
)


# ── Public-surface presence ───────────────────────────────────────


def test_v1_symbols_exist_at_top_level():
    """All v1 public symbols are re-exported from the raroc_engine package."""
    import raroc_engine

    for name in (
        "RAROCCalculator", "RAROCInput", "RAROCOutput",
        "Repository", "EngineConfig",
        "normalize_rating",
        "PRODUCT_TYPES", "PRODUCT_DESCRIPTIONS",
        "RATING_ORDER", "ALL_VALID_RATINGS",
        "SP_TO_MOODYS", "MOODYS_TO_SP",
    ):
        assert hasattr(raroc_engine, name), f"missing public symbol: {name}"


def test_raroc_calculator_signature_unchanged():
    """RAROCCalculator(repository=None, config=None) — order + defaults preserved."""
    sig = inspect.signature(RAROCCalculator.__init__)
    params = list(sig.parameters.values())
    assert [p.name for p in params] == ["self", "repository", "config"]
    assert params[1].default is None
    assert params[2].default is None


def test_raroc_calculator_calculate_signature_unchanged():
    """RAROCCalculator.calculate(inp: RAROCInput) -> RAROCOutput."""
    sig = inspect.signature(RAROCCalculator.calculate)
    assert [p.name for p in sig.parameters.values()] == ["self", "inp"]


def test_raroc_input_field_set_unchanged():
    """RAROCInput preserves every v1 field name and default."""
    expected = {
        "product_type": "mlt_credit",
        "operation": "",
        "bank": "",
        "bank_group": "",
        "division": "",
        "entity": "",
        "initial_volume": 0.0,
        "initial_drawn": 0.0,
        "average_volume": 0.0,
        "average_drawn": 0.0,
        "initial_maturity": 60.0,
        "residual_maturity": 60.0,
        "spread": 0.0,
        "commitment_fee": 0.0,
        "flat_fee": 0.0,
        "participation_fee": 0.0,
        "upfront_fee": 0.0,
        "user_cost": None,
        "collateral": "",
        "collateral_face_value": 0.0,
        "collateral_stress_value": 0.0,
        "global_grr": 0.0,
        "confirmed": True,
        "rating": "Baa1",
        "exchange_rate": 1.0,
    }
    fields = RAROCInput.__dataclass_fields__
    for name, default in expected.items():
        assert name in fields, f"RAROCInput missing v1 field: {name}"
        # ``default`` may be a MISSING sentinel for fields without defaults;
        # all v1 fields had defaults, so assert that's still true.
        f = fields[name]
        assert f.default == default, (
            f"RAROCInput.{name} default changed: {f.default!r} vs {default!r}"
        )


def test_raroc_output_field_set_unchanged():
    """RAROCOutput preserves every v1 field name."""
    expected = {
        "product_type", "rating", "global_grr",
        "revenue", "cost",
        "exposure", "pd", "pd_basel2",
        "correlation", "maturity_adj_b", "risk_weight",
        "fpe", "average_loss",
        "gross_margin", "revenues_of_fpe", "net_margin", "taxes",
        "raroc",
    }
    actual = set(RAROCOutput.__dataclass_fields__.keys())
    missing = expected - actual
    assert not missing, f"RAROCOutput missing v1 fields: {missing}"


def test_engine_config_field_set_unchanged():
    """EngineConfig preserves every v1 field name + default."""
    cfg = EngineConfig()
    assert cfg.regime == "basel3"
    assert cfg.risk_free_rate == 0.0325
    assert cfg.bank_tax_rate == 0.25
    assert cfg.funding_cost_bp == 0.0
    assert cfg.output_floor_pct == 0.55
    assert cfg.pd_floor == 0.0005
    assert cfg.lgd_floor_unsecured == 0.25
    assert cfg.lgd_floor_secured == 0.10
    assert cfg.target_raroc == 0.12


# ── Behavioural pin: a known v1 deal computes to a known v1 RAROC ──


def test_v1_known_deal_numerical_pin():
    """A known v1 deal computes within tolerance to the v1 RAROC.

    The deal is the v1 demo scenario 1 (5y term loan, A2-rated, EUR 35M
    drawn / 50M committed, 150bp spread, 20bp commit fee, 50k participation
    fee, GRR 55%). The reference RAROC was the v1 output of the same
    inputs against the same Basel III config. A drift in any of the v1
    formulas (revenue, EAD, K, FPE, EL, RAROC) trips this test.
    """
    inp = RAROCInput(
        product_type="mlt_credit",
        operation="5Y Term Loan Facility",
        bank="BNP Paribas",
        average_volume=50_000_000,
        average_drawn=35_000_000,
        initial_maturity=60,
        residual_maturity=60,
        spread=0.015,
        commitment_fee=0.002,
        participation_fee=50_000,
        rating="A2",
        confirmed=True,
        global_grr=0.55,
    )
    out = RAROCCalculator(config=EngineConfig()).calculate(inp)

    # Pin to 1e-6 absolute — these are the exact v1 numbers; any change in
    # the underlying formula must explicitly update this expectation.
    # EAD = 0.25 × 35M + 0.75 × 50M = 8.75M + 37.5M = 46.25M
    assert out.exposure == pytest.approx(46_250_000.0, abs=1e-6)
    # PD floor = 5bp, A2 PD = 5bp, so output PD is 0.0005
    assert out.pd == pytest.approx(0.0005, abs=1e-9)
    assert out.pd_basel2 == pytest.approx(0.0005 * (1 - 0.55), abs=1e-9)
    # Revenue = spread × drawn + commit × undrawn + participation_fee
    #         = 0.015 × 35M + 0.002 × 15M + 50k = 525k + 30k + 50k
    assert out.revenue == pytest.approx(605_000.0, abs=1e-6)
    # Cost = revenue × 0.40 (credit cost-income ratio)
    assert out.cost == pytest.approx(605_000.0 * 0.40, abs=1e-6)
    # FPE / RAROC pinned to v1 numbers (Basel III IRB w/ output floor)
    assert out.fpe == pytest.approx(1_247_174.288149, abs=1e-3)
    assert out.raroc == pytest.approx(0.236410571, abs=1e-7)


def test_v1_rating_normalisation_unchanged():
    """normalize_rating handles every v1 supported rating format."""
    # Moody's → Moody's
    assert normalize_rating("Baa1") == "Baa1"
    assert normalize_rating("baa1") == "Baa1"  # case-insensitive
    # S&P → Moody's
    assert normalize_rating("BBB+") == "Baa1"
    assert normalize_rating("AAA") == "Aaa"
    # Fitch (same scale as S&P)
    assert normalize_rating("A-") == "A3"
    # Invalid raises
    with pytest.raises(ValueError):
        normalize_rating("ZZ")


def test_v1_product_types_unchanged():
    """v1 product type keys must remain valid."""
    for key in (
        "short_term_credit", "mlt_credit", "caution",
        "technical_guarantee", "financial_guarantee",
        "import_lc", "ir_swap", "fx_swap", "forward",
    ):
        assert key in PRODUCT_TYPES, f"v1 product type missing: {key}"


def test_v1_rating_order_unchanged():
    """RATING_ORDER preserves the v1 Aaa→C sequence."""
    assert RATING_ORDER[0] == "Aaa"
    assert RATING_ORDER[-1] == "C"
    assert "Baa1" in RATING_ORDER
    assert "B3" in RATING_ORDER


def test_v1_solve_spread_signature():
    """Reverse spread solver preserves its v1 signature."""
    calc = RAROCCalculator()
    assert hasattr(calc, "solve_spread")
    sig = inspect.signature(calc.solve_spread)
    # v1: solve_spread(inp, target_raroc=None)
    params = list(sig.parameters)
    assert params[0] == "inp"
    # target_raroc must accept None or float (default = config target_raroc)
    inp = RAROCInput(
        product_type="mlt_credit",
        average_volume=10_000_000,
        average_drawn=10_000_000,
        spread=0.0,
        rating="Baa1",
        residual_maturity=60,
        initial_maturity=60,
        confirmed=True,
    )
    result = calc.solve_spread(inp, target_raroc=0.12)
    assert "solved_spread" in result
    assert "solved_spread_bp" in result
    assert "output" in result


def test_v1_sensitivity_signature():
    """sensitivity preserves its v1 (inp, param, start, stop, step) signature."""
    calc = RAROCCalculator()
    inp = RAROCInput(
        product_type="mlt_credit",
        average_volume=10_000_000, average_drawn=10_000_000,
        spread=0.015, rating="Baa1",
        residual_maturity=60, initial_maturity=60,
    )
    results = calc.sensitivity(inp, "grr", 0.0, 0.5, 0.25)
    # Returns list[(value, RAROCOutput)]
    assert isinstance(results, list)
    for val, out in results:
        assert isinstance(out, RAROCOutput)


def test_repository_v1_surface():
    """Repository v1 methods still resolve."""
    repo = Repository()
    pd = repo.get_rating_value("Baa1")
    assert 0 < pd < 1
    coeff = repo.get_revenue_coeff("mlt_credit")
    assert 0 < coeff <= 1


# ── Version assertion ──────────────────────────────────────────────


def test_version_is_2_0():
    """Module __version__ pins to 2.0.0 for the v2 release tag."""
    import raroc_engine
    assert raroc_engine.__version__ == "2.0.0"


def test_v1_cli_calc_still_runs(tmp_path):
    """`openraroc calc` (the v1 single-deal CLI subcommand) still works."""
    from click.testing import CliRunner
    from raroc_engine.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, [
        "calc",
        "--product", "mlt_credit",
        "--avg-drawn", "35000000",
        "--avg-volume", "50000000",
        "--spread", "0.015",
        "--commit-fee", "0.002",
        "--rating", "Baa1",
        "--maturity", "60",
    ])
    assert result.exit_code == 0, result.output
    assert "RAROC" in result.output


def test_v2_cli_period_subcommand_runs(tmp_path):
    """`openraroc period <fixture.yaml>` runs and produces the aggregates panel."""
    import os
    from click.testing import CliRunner
    from raroc_engine.cli import cli

    fixture = os.path.join(
        os.path.dirname(__file__), "fixtures", "period_rcf_5y.yaml"
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["period", fixture])
    assert result.exit_code == 0, result.output
    assert "Per-Period RAROC" in result.output
    assert "Wallet Aggregates" in result.output


def test_v2_cli_schedule_shortcut_runs():
    """`openraroc --schedule <fixture.yaml>` is the top-level shortcut for period."""
    import os
    from click.testing import CliRunner
    from raroc_engine.cli import cli

    fixture = os.path.join(
        os.path.dirname(__file__), "fixtures", "period_rcf_5y.yaml"
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["--schedule", fixture])
    assert result.exit_code == 0, result.output
    assert "Per-Period RAROC" in result.output


def test_v2_cli_schedule_json_emits_parseable_payload():
    """--schedule with --json emits a JSON payload containing the v2 sections."""
    import json
    import os
    from click.testing import CliRunner
    from raroc_engine.cli import cli

    fixture = os.path.join(
        os.path.dirname(__file__), "fixtures", "period_rcf_5y.yaml"
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["--schedule", fixture, "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "per_period" in payload
    assert "aggregates" in payload
    assert "engine_meta" in payload
    assert len(payload["per_period"]) == 5
