"""MCP (Model Context Protocol) server for the RAROC engine.

Exposes RAROC calculations as tools that any AI agent can call.
A CFO's AI assistant can use this to answer questions like:
  - "What's my bank's RAROC on our 5-year credit facility?"
  - "What's the minimum spread BNP Paribas would accept for a BBB+ rated loan?"
  - "Compare how 6 different banks see our credit portfolio"
  - "What's the effective spread on this 7y amortising loan?"  (v2.0+)
  - "Run the multi-period engine on my YAML schedule"           (v2.0+)

Usage:
    python -m raroc_engine.mcp_server

Or add to Claude Desktop / any MCP client config:
    {
      "mcpServers": {
        "raroc": {
          "command": "python3",
          "args": ["-m", "raroc_engine.mcp_server"],
          "cwd": "/path/to/raroc"
        }
      }
    }
"""

import json
import os
from dataclasses import asdict
from datetime import date
from mcp.server.fastmcp import FastMCP

from .config import EngineConfig
from .repository import Repository
from .calculator import RAROCCalculator
from .period_engine import DiscountSpec, PeriodEngine
from .schedule import Schedule
from .banks import BANK_PROFILES
from .models import (
    RAROCInput, PRODUCT_TYPES, PRODUCT_DESCRIPTIONS,
    RATING_ORDER, MOODYS_TO_SP, normalize_rating,
)

# ── Server setup ─────────────────────────────────────────────────

mcp = FastMCP(
    "RAROC Engine",
    instructions=(
        "Risk-Adjusted Return on Capital calculator for corporate credit facilities. "
        "Uses Basel III formulas and real bank data from Pillar 3 disclosures to show "
        "how banks evaluate credit risk and pricing. Helps corporate treasurers "
        "understand and negotiate their banking relationships."
    ),
)

_repo = Repository()
_config = EngineConfig()


def _make_calc(bank_key: str = None) -> RAROCCalculator:
    """Create a calculator, optionally with bank-specific parameters."""
    cfg = EngineConfig(
        regime=_config.regime,
        risk_free_rate=_config.risk_free_rate,
        bank_tax_rate=_config.bank_tax_rate,
        funding_cost_bp=_config.funding_cost_bp,
        output_floor_pct=_config.output_floor_pct,
        pd_floor=_config.pd_floor,
        target_raroc=_config.target_raroc,
    )
    if bank_key and bank_key in BANK_PROFILES:
        p = BANK_PROFILES[bank_key]
        cfg.bank_tax_rate = p.effective_tax_rate
        cfg.funding_cost_bp = p.funding_spread_bp
    return RAROCCalculator(_repo, cfg)


def _build_input(
    product_type: str = "mlt_credit",
    average_drawn: float = 0,
    average_volume: float = 0,
    spread_bp: float = 0,
    commitment_fee_bp: float = 0,
    flat_fee: float = 0,
    upfront_fee: float = 0,
    rating: str = "BBB+",
    maturity_months: float = 60,
    confirmed: bool = True,
    grr_pct: float = 0,
    user_cost: float = None,
) -> RAROCInput:
    return RAROCInput(
        product_type=product_type,
        average_drawn=average_drawn,
        average_volume=average_volume or average_drawn,
        initial_maturity=maturity_months,
        residual_maturity=maturity_months,
        spread=spread_bp / 10000,
        commitment_fee=commitment_fee_bp / 10000,
        flat_fee=flat_fee,
        upfront_fee=upfront_fee,
        user_cost=user_cost,
        rating=rating,
        confirmed=confirmed,
        global_grr=grr_pct / 100,
    )


def _fmt_output(out) -> dict:
    """Format output for readable display."""
    d = asdict(out)
    d["raroc_pct"] = f"{out.raroc * 100:.2f}%"
    d["risk_weight_pct"] = f"{out.risk_weight * 100:.4f}%"
    d["pd_pct"] = f"{out.pd * 100:.4f}%"
    return d


# ── Tools ─────────────────────────────────────────────────────────

@mcp.tool()
def calculate_raroc(
    product_type: str,
    average_drawn: float,
    spread_bp: float,
    rating: str,
    maturity_months: float = 60,
    average_volume: float = 0,
    commitment_fee_bp: float = 0,
    flat_fee: float = 0,
    upfront_fee: float = 0,
    confirmed: bool = True,
    grr_pct: float = 0,
    bank: str = "",
) -> str:
    """Calculate RAROC (Risk-Adjusted Return on Capital) for a credit facility.

    This shows how a bank evaluates the profitability of a lending deal,
    accounting for credit risk and capital allocation under Basel III.

    Args:
        product_type: Type of facility. Common values: mlt_credit (term loans),
            short_term_credit (revolving), caution (guarantees), ir_swap, forward, fx_swap
        average_drawn: Average drawn amount in EUR
        spread_bp: Credit spread in basis points (e.g. 150 for 1.50%)
        rating: Credit rating - accepts S&P (BBB+), Moody's (Baa1), or Fitch
        maturity_months: Residual maturity in months (default 60)
        average_volume: Committed/authorized amount in EUR (defaults to average_drawn)
        commitment_fee_bp: Commitment fee on undrawn portion in bp
        flat_fee: Annual flat fee in EUR
        upfront_fee: One-time upfront fee in EUR
        confirmed: Whether the facility is committed/confirmed
        grr_pct: Guarantee Recovery Rate in percent (0-100). Higher = more collateral
        bank: Optional bank profile key for bank-specific parameters
            (bnp_paribas, societe_generale, credit_agricole, hsbc, deutsche_bank, barclays)
    """
    calc = _make_calc(bank or None)
    inp = _build_input(
        product_type=product_type, average_drawn=average_drawn,
        average_volume=average_volume, spread_bp=spread_bp,
        commitment_fee_bp=commitment_fee_bp, flat_fee=flat_fee,
        upfront_fee=upfront_fee, rating=rating,
        maturity_months=maturity_months, confirmed=confirmed,
        grr_pct=grr_pct,
    )
    out = calc.calculate(inp)
    result = _fmt_output(out)
    result["bank_profile"] = bank if bank else "generic"
    return json.dumps(result, indent=2)


@mcp.tool()
def solve_minimum_spread(
    product_type: str,
    average_drawn: float,
    rating: str,
    target_raroc_pct: float = 12,
    maturity_months: float = 60,
    average_volume: float = 0,
    commitment_fee_bp: float = 0,
    confirmed: bool = True,
    grr_pct: float = 0,
    bank: str = "",
) -> str:
    """Find the minimum spread a bank needs to achieve its target RAROC.

    Answers: "What's the minimum spread my bank will accept for this deal?"
    This is the key negotiation insight for a corporate treasurer.

    Args:
        product_type: Facility type (mlt_credit, short_term_credit, etc.)
        average_drawn: Average drawn amount in EUR
        rating: Credit rating (BBB+, A-, Baa1, etc.)
        target_raroc_pct: Bank's target RAROC in percent (default 12%)
        maturity_months: Residual maturity in months
        average_volume: Committed amount in EUR (defaults to average_drawn)
        commitment_fee_bp: Commitment fee on undrawn in bp
        confirmed: Committed facility?
        grr_pct: Guarantee Recovery Rate in percent (0-100)
        bank: Bank profile key for bank-specific economics
    """
    calc = _make_calc(bank or None)
    inp = _build_input(
        product_type=product_type, average_drawn=average_drawn,
        average_volume=average_volume, spread_bp=0,
        commitment_fee_bp=commitment_fee_bp, rating=rating,
        maturity_months=maturity_months, confirmed=confirmed,
        grr_pct=grr_pct,
    )
    result = calc.solve_spread(inp, target_raroc=target_raroc_pct / 100)
    return json.dumps({
        "target_raroc": f"{target_raroc_pct}%",
        "minimum_spread_bp": round(result["solved_spread_bp"], 1),
        "achieved_raroc": f"{result['output'].raroc * 100:.2f}%",
        "bank_profile": bank if bank else "generic",
    }, indent=2)


@mcp.tool()
def compare_banks(
    product_type: str,
    average_drawn: float,
    spread_bp: float,
    rating: str,
    maturity_months: float = 60,
    average_volume: float = 0,
    commitment_fee_bp: float = 0,
    confirmed: bool = True,
    grr_pct: float = 0,
) -> str:
    """Compare how different banks evaluate the same credit facility.

    Shows RAROC and minimum spread across all available bank profiles.
    Each bank has different cost structures, tax rates, and funding costs
    based on their public Pillar 3 disclosures.

    Args:
        product_type: Facility type
        average_drawn: Average drawn amount in EUR
        spread_bp: Current spread in basis points
        rating: Credit rating
        maturity_months: Residual maturity in months
        average_volume: Committed amount in EUR
        commitment_fee_bp: Commitment fee on undrawn in bp
        confirmed: Committed facility?
        grr_pct: Guarantee Recovery Rate in percent
    """
    inp = _build_input(
        product_type=product_type, average_drawn=average_drawn,
        average_volume=average_volume, spread_bp=spread_bp,
        commitment_fee_bp=commitment_fee_bp, rating=rating,
        maturity_months=maturity_months, confirmed=confirmed,
        grr_pct=grr_pct,
    )

    comparisons = []
    for bank_key, profile in BANK_PROFILES.items():
        calc = _make_calc(bank_key)
        out = calc.calculate(RAROCInput(**asdict(inp)))
        solve = calc.solve_spread(RAROCInput(**asdict(inp)))
        comparisons.append({
            "bank": profile.name,
            "country": profile.country,
            "irb_approach": profile.irb_approach,
            "cost_to_income": f"{profile.cost_to_income * 100:.1f}%",
            "tax_rate": f"{profile.effective_tax_rate * 100:.1f}%",
            "raroc": f"{out.raroc * 100:.2f}%",
            "minimum_spread_bp": round(solve["solved_spread_bp"], 0),
            "economic_capital": round(out.fpe),
        })

    comparisons.sort(key=lambda x: -float(x["raroc"].replace("%", "")))
    return json.dumps({"deal_summary": f"{rating} {product_type} {average_drawn/1e6:.0f}M {maturity_months:.0f}m",
                        "comparisons": comparisons}, indent=2)


@mcp.tool()
def sensitivity_analysis(
    product_type: str,
    average_drawn: float,
    spread_bp: float,
    rating: str,
    parameter: str = "grr",
    maturity_months: float = 60,
    average_volume: float = 0,
    confirmed: bool = True,
    grr_pct: float = 0,
    bank: str = "",
) -> str:
    """Run sensitivity analysis showing how RAROC changes with one parameter.

    Args:
        product_type: Facility type
        average_drawn: Average drawn amount
        spread_bp: Spread in basis points
        rating: Credit rating
        parameter: What to vary - "grr" (collateral), "rating" (credit quality),
            "spread_delta" (spread changes), "maturity" (tenor)
        maturity_months: Residual maturity
        average_volume: Committed amount
        confirmed: Committed facility?
        grr_pct: Current GRR in percent
        bank: Bank profile key
    """
    calc = _make_calc(bank or None)
    inp = _build_input(
        product_type=product_type, average_drawn=average_drawn,
        average_volume=average_volume, spread_bp=spread_bp,
        rating=rating, maturity_months=maturity_months,
        confirmed=confirmed, grr_pct=grr_pct,
    )

    ranges = {
        "grr": (0.0, 0.9, 0.1),
        "rating": (-5, 5, 1),
        "spread_delta": (-0.005, 0.01, 0.0025),
        "maturity": (6, 120, 12),
    }
    start, stop, step = ranges.get(parameter, (0, 1, 0.1))
    results = calc.sensitivity(inp, parameter, start, stop, step)

    points = []
    for val, out in results:
        label = (f"{val:.0%}" if parameter == "grr"
                 else f"{val:+.0f}" if parameter == "rating"
                 else f"{val*10000:+.0f}bp" if parameter == "spread_delta"
                 else f"{val:.0f}m")
        rating_name = _repo.roll_rating(inp.rating, int(val)) if parameter == "rating" else None
        entry = {"value": label, "raroc": f"{out.raroc * 100:.2f}%"}
        if rating_name:
            entry["rating"] = rating_name
        points.append(entry)

    return json.dumps({"parameter": parameter, "points": points}, indent=2)


@mcp.tool()
def list_available_banks() -> str:
    """List all available bank profiles with their key parameters.

    Bank profiles are built from public Pillar 3 disclosures and annual reports.
    Use the bank key in other tools to get bank-specific RAROC calculations.
    """
    banks = []
    for key, p in BANK_PROFILES.items():
        banks.append({
            "key": key,
            "name": p.name,
            "country": p.country,
            "irb_approach": p.irb_approach,
            "cost_to_income": f"{p.cost_to_income * 100:.1f}%",
            "effective_tax_rate": f"{p.effective_tax_rate * 100:.1f}%",
            "avg_lgd_unsecured": f"{p.avg_lgd_unsecured * 100:.0f}%",
            "source": p.source,
            "confidence": p.confidence,
        })
    return json.dumps({"banks": banks}, indent=2)


@mcp.tool()
def list_credit_ratings() -> str:
    """List the credit rating scale with probability of default for each rating.

    Shows Moody's and S&P/Fitch equivalents with PD values.
    Based on S&P Global long-run average corporate default rates.
    """
    ratings = []
    for name in RATING_ORDER:
        pd = _repo.ratings.get(name, 0)
        sp = MOODYS_TO_SP.get(name, "")
        ratings.append({
            "moodys": name,
            "sp_fitch": sp,
            "pd": f"{pd * 100:.4f}%",
        })
    return json.dumps({"ratings": ratings}, indent=2)


@mcp.tool()
def list_product_types() -> str:
    """List available banking product types for RAROC calculations."""
    products = []
    for key, desc in PRODUCT_DESCRIPTIONS.items():
        coeff = _repo.get_revenue_coeff(key)
        products.append({
            "key": key,
            "description": desc,
            "cost_coefficient": f"{coeff * 100:.0f}%",
        })
    return json.dumps({"products": products}, indent=2)


# ── Multi-period tools (v2.0) ─────────────────────────────────────

def _serialize_period_output(out) -> dict:
    """Compact JSON-friendly view of a :class:`PeriodEngineOutput`."""
    return {
        "engine_meta": out.engine_meta,
        "discount_meta": out.discount_meta,
        "aggregates": {
            **out.aggregates,
            "fpe_weighted_raroc_pct": f"{out.aggregates['fpe_weighted_raroc'] * 100:.2f}%",
            "effective_spread_bp_fmt": f"{out.aggregates['effective_spread_bp']:.1f}bp",
        },
        "per_period": [
            {
                "index": r.index,
                "start": r.start.isoformat(),
                "end": r.end.isoformat(),
                "dt_years": r.dt_years,
                "commitment": r.commitment,
                "avg_drawn": r.avg_drawn,
                "remaining_maturity_years": r.remaining_maturity_years,
                "revenue": r.revenue,
                "cost": r.cost,
                "funding_cost": r.funding_cost,
                "exposure": r.exposure,
                "fpe": r.fpe,
                "el": r.el,
                "K": r.K,
                "net_margin": r.net_margin,
                "raroc": r.raroc,
                "raroc_pct": f"{r.raroc * 100:.2f}%",
                "principal_repayment": r.principal_repayment,
                "t_end_years": r.t_end_years,
                "df": r.df,
                "revenue_pv": r.revenue_pv,
                "net_margin_pv": r.net_margin_pv,
                "drawn_pv": r.drawn_pv,
                "floating_index": r.floating_index,
                "fixing_rate": r.fixing_rate,
                "all_in_rate": r.all_in_rate,
                "curve_status": r.curve_status,
            }
            for r in out.per_period
        ],
    }


def _build_period_deal(
    product_type: str,
    rating: str,
    spread_bp: float,
    commitment_fee_bp: float,
    grr_pct: float,
    confirmed: bool,
) -> RAROCInput:
    """RAROCInput carrying only the static facets — volumes come from the Schedule."""
    return RAROCInput(
        product_type=product_type,
        rating=rating,
        spread=spread_bp / 10000.0,
        commitment_fee=commitment_fee_bp / 10000.0,
        global_grr=grr_pct / 100.0,
        confirmed=confirmed,
    )


@mcp.tool()
def run_multi_period(
    schedule_yaml_path: str,
    bank: str = "",
) -> str:
    """Run the multi-period engine on a YAML schedule fixture (v2.0+).

    Walks a facility's life period by period through the per-period RAROC
    loop and emits the wallet-grade aggregates: NPV borrower cost, NPV
    bank net margin, effective spread, FPE-weighted RAROC, total revenue
    and EL. The fixture file must match the layout of
    tests/fixtures/period_*.yaml: engine_config, deal, schedule, discount.

    Args:
        schedule_yaml_path: Absolute or relative path to a schedule YAML.
        bank: Optional bank profile key (overrides funding/tax in fixture).
    """
    try:
        import yaml
    except ImportError:
        return json.dumps({"error": "PyYAML not installed"})

    if not os.path.exists(schedule_yaml_path):
        return json.dumps({"error": f"File not found: {schedule_yaml_path}"})

    with open(schedule_yaml_path) as f:
        fx = yaml.safe_load(f)

    cfg = EngineConfig.from_dict(fx.get("engine_config") or {})
    if bank and bank in BANK_PROFILES:
        cfg.apply_bank_profile(bank)

    deal_block = fx.get("deal") or {}
    deal = RAROCInput(
        product_type=deal_block.get("product_type", "mlt_credit"),
        rating=deal_block.get("rating", "Baa1"),
        global_grr=float(deal_block.get("global_grr", 0.0)),
        confirmed=bool(deal_block.get("confirmed", True)),
        spread=float(deal_block.get("spread", 0.0)),
        commitment_fee=float(deal_block.get("commitment_fee", 0.0)),
        flat_fee=float(deal_block.get("flat_fee", 0.0)),
        participation_fee=float(deal_block.get("participation_fee", 0.0)),
        upfront_fee=float(deal_block.get("upfront_fee", 0.0)),
    )
    schedule = Schedule.from_dict(fx["schedule"])
    disc_block = fx.get("discount") or {"kind": "scalar", "rate": cfg.risk_free_rate}
    discount = DiscountSpec(
        kind=disc_block.get("kind", "scalar"),
        rate=float(disc_block.get("rate", cfg.risk_free_rate)),
        day_count=disc_block.get("day_count", "Act/365F"),
    )

    engine = PeriodEngine(config=cfg)
    out = engine.run(deal, schedule, discount)
    result = _serialize_period_output(out)
    result["fixture_id"] = fx.get("fixture_id", os.path.basename(schedule_yaml_path))
    result["bank_profile"] = bank if bank else "generic"
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def calculate_amortising_term_loan(
    initial_drawn: float,
    total_years: int,
    rating: str,
    spread_bp: float,
    commitment_fee_bp: float = 0,
    final_balance: float = 0,
    upfront_fee: float = 0,
    product_type: str = "mlt_credit",
    confirmed: bool = True,
    grr_pct: float = 0,
    discount_rate_pct: float = 3.25,
    start_year: int = 2026,
    bank: str = "",
) -> str:
    """Multi-period RAROC for a linear-amortising term loan (v2.0+).

    Builds a Schedule.scheduled_amortising_term_loan and walks it through
    the per-period engine. Returns per-period rows + wallet aggregates
    (NPV, effective spread, FPE-weighted RAROC).

    Args:
        initial_drawn: Day-1 drawn balance (EUR).
        total_years: Tenor in years; drawn amortises linearly to final_balance.
        rating: Borrower's credit rating (BBB+, Baa1, etc.).
        spread_bp: Credit spread in basis points.
        commitment_fee_bp: Commitment fee on undrawn (bp).
        final_balance: Terminal balance after the last period (default 0 = fully amortised).
        upfront_fee: One-time fee booked in year 1.
        product_type: Product type (default mlt_credit).
        confirmed: Committed facility?
        grr_pct: Guarantee/collateral recovery rate (0-100).
        discount_rate_pct: Discount rate for the NPV layer (default 3.25%).
        start_year: First period start year (default 2026).
        bank: Optional bank profile key.
    """
    cfg = EngineConfig()
    if bank and bank in BANK_PROFILES:
        cfg.apply_bank_profile(bank)
    deal = _build_period_deal(
        product_type, rating, spread_bp, commitment_fee_bp, grr_pct, confirmed,
    )
    schedule = Schedule.scheduled_amortising_term_loan(
        initial_drawn=initial_drawn,
        total_years=total_years,
        start=date(start_year, 1, 1),
        final_balance=final_balance,
        upfront_fee=upfront_fee,
    )
    discount = DiscountSpec(kind="scalar", rate=discount_rate_pct / 100.0)
    engine = PeriodEngine(config=cfg)
    out = engine.run(deal, schedule, discount)
    result = _serialize_period_output(out)
    result["shape"] = "scheduled_amortising_term_loan"
    result["bank_profile"] = bank if bank else "generic"
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def calculate_bullet_rcf(
    commitment: float,
    drawn_levels: list,
    rating: str,
    spread_bp: float,
    commitment_fee_bp: float = 25,
    upfront_fee: float = 0,
    product_type: str = "mlt_credit",
    confirmed: bool = True,
    grr_pct: float = 0,
    discount_rate_pct: float = 3.25,
    start_year: int = 2026,
    bank: str = "",
) -> str:
    """Multi-period RAROC for a bullet RCF with stepped drawn levels (v2.0+).

    Builds a Schedule.bullet_rcf_with_cleandown and walks it through
    the per-period engine. Use this for facilities whose commitment
    stays flat but whose drawn balance steps down (cleandown) over time.

    Args:
        commitment: Committed amount (constant across the schedule).
        drawn_levels: List of [avg_drawn, n_years] pairs describing the
            drawn-balance profile. E.g. [[35e6, 3], [20e6, 2]] for a
            5y RCF that cleans down from 35M to 20M after year 3.
        rating: Borrower's credit rating.
        spread_bp: Credit spread (bp).
        commitment_fee_bp: Commitment fee on undrawn (bp).
        upfront_fee: One-time fee booked in year 1.
        product_type: Product type (default mlt_credit).
        confirmed: Committed facility?
        grr_pct: Guarantee/collateral recovery rate (0-100).
        discount_rate_pct: Discount rate for the NPV layer (default 3.25%).
        start_year: First period start year (default 2026).
        bank: Optional bank profile key.
    """
    cfg = EngineConfig()
    if bank and bank in BANK_PROFILES:
        cfg.apply_bank_profile(bank)
    deal = _build_period_deal(
        product_type, rating, spread_bp, commitment_fee_bp, grr_pct, confirmed,
    )
    levels = [(float(lvl[0]), int(lvl[1])) for lvl in drawn_levels]
    schedule = Schedule.bullet_rcf_with_cleandown(
        commitment=commitment,
        drawn_levels=levels,
        start=date(start_year, 1, 1),
        upfront_fee=upfront_fee,
    )
    discount = DiscountSpec(kind="scalar", rate=discount_rate_pct / 100.0)
    engine = PeriodEngine(config=cfg)
    out = engine.run(deal, schedule, discount)
    result = _serialize_period_output(out)
    result["shape"] = "bullet_rcf_with_cleandown"
    result["bank_profile"] = bank if bank else "generic"
    return json.dumps(result, indent=2, default=str)


# ── Resources ─────────────────────────────────────────────────────

@mcp.resource("raroc://config")
def get_engine_config() -> str:
    """Current RAROC engine configuration parameters."""
    return json.dumps(_config.to_dict(), indent=2)


@mcp.resource("raroc://methodology")
def get_methodology() -> str:
    """RAROC calculation methodology and formula documentation."""
    return """# RAROC Calculation Methodology

## Single-period formula (v1)
RAROC = (1 - TaxRate) × [(Revenue - Cost - FundingCost - ExpectedLoss) / EconomicCapital + RiskFreeRate]

## Components
- **Revenue** = Spread × AvgDrawn + CommitFee × (Volume - Drawn) + Fees
- **Cost** = Revenue × CostCoefficient (40% credit, 75% derivatives)
- **Exposure at Default (EAD)** = Weighted sum of drawn, authorized, and collateral
- **Risk Weight (K)** = Basel III IRB formula using PD, LGD, correlation, maturity adjustment
- **Economic Capital (FPE)** = EAD × K
- **Expected Loss** = EAD × PD × (1 - GRR)

## Basel III features
- PD floor: 5bp
- LGD floor: 25% unsecured, 10% secured
- Output floor: 55% of SA risk weight (2026 phase-in)

## Multi-period engine (v2.0)
- Schedule = ordered list of Periods, each carrying commitment / avg_drawn /
  remaining_maturity_years (+ optional period-allocated fees and floating
  fixings).
- Per period, the single-period math runs against a synthetic RAROCInput
  (period volumes + residual maturity); dt-dependent fields (revenue, EL,
  funding cost, FPE return) scale by ``dt_years``, period-allocated fees
  do not (they are bookings, not accruals).
- Aggregates: NPV borrower cost (Σ revenue × DF), NPV bank net margin,
  effective spread (revenue_pv / drawn_pv), FPE-weighted RAROC,
  time-weighted RAROC, FPE-years.

## Discount-rate convention (D-0003)
- Per-calc configurable: scalar | curve name | (date, rate) schedule.
- Default = 10y risk-free curve in deal currency, Act/365F discrete annual.
- Floating-rate fallback cascade: fresh (≤24h) → stale (≤7d) →
  interpolated → scalar_fallback (engine cfg) → CurveDataUnavailable.

## Data sources
- PD values: S&P Global long-run average corporate default rates
- Bank profiles: Public Pillar 3 disclosures (BNP Paribas, SocGen, Credit Agricole, HSBC, Deutsche Bank, Barclays)
- Floating-rate curves: ECB (ESTR), Bank of England (SONIA), New York Fed (SOFR)

See METHODOLOGY.md in the repo for the full derivation.
"""


@mcp.resource("raroc://multiperiod-spec")
def get_multiperiod_spec() -> str:
    """Multi-period engine spec: schedule shapes + aggregates."""
    return """# Multi-Period RAROC Engine (v2.0)

## Schedule shapes
- ``single_period``                            — back-compat (length-1, dt=1.0)
- ``bullet_rcf_with_cleandown``                — flat commitment + stepped drawn
- ``scheduled_amortising_term_loan``           — linear amortisation
- ``drawdown_ramp_with_grace``                 — ramp → grace → amortise → bullet
- ``project_finance_milestones``               — generic [(avg_drawn, n_years)…]

## Per-period output fields
index, start, end, dt_years, commitment, avg_drawn, remaining_maturity_years,
revenue, cost, funding_cost, exposure, pd, pd_basel2, lgd, correlation,
maturity_adj_b, z, K_irb, sa_rw, K_floor, K, fpe, el, gross_margin, fpe_return,
net_margin, raroc, principal_repayment, t_end_years, df, revenue_pv,
net_margin_pv, drawn_pv, floating_index, fixing_rate, all_in_rate, curve_status

## Aggregates
- npv_borrower_cost, npv_bank_net_margin, npv_bank_costs, npv_drawn_balance
- total_revenue_undisc, total_el_undisc, total_funding_cost_undisc,
  total_borrower_cost_undisc, total_bank_costs_undisc
- avg_exposure, fpe_years (Σ FPE × dt)
- effective_spread, effective_spread_bp
- avg_raroc (time-weighted), capital_weighted_raroc (= fpe_weighted_raroc)
- n_periods, total_years

## Tolerances
- 0.5 bp absolute on per-period RAROC
- 0.1% relative on NPV totals
- 0.5 bp absolute on effective spread
- 1e-12 absolute on single-period parity (length-1 dt=1.0 schedule)

See docs/engine/multiperiod-spec.md in the repo for the full math.
"""


# ── Entry point ───────────────────────────────────────────────────

def main():
    mcp.run()


if __name__ == "__main__":
    main()
