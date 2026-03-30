"""Command-line interface for the RAROC calculator."""

import sys
import csv
import os
from typing import Optional
import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

from .models import (
    RAROCInput,
    RAROCOutput,
    PRODUCT_TYPES,
    PRODUCT_DESCRIPTIONS,
    RATING_ORDER,
    MOODYS_TO_SP,
    ALL_VALID_RATINGS,
    normalize_rating,
)
from .repository import Repository
from .config import EngineConfig
from .calculator import RAROCCalculator

console = Console()


# ── Formatting helpers ────────────────────────────────────────────

def fmt_num(value: float, decimals: int = 0) -> str:
    """Format number with thousands separator."""
    if abs(value) >= 1:
        return f"{value:,.{decimals}f}"
    return f"{value:.{max(decimals, 2)}f}"


def fmt_pct(value: float, decimals: int = 2) -> str:
    """Format as percentage."""
    return f"{value * 100:+.{decimals}f}%" if value != 0 else f"0.{'0' * decimals}%"


def fmt_bp(value: float) -> str:
    """Format as basis points."""
    return f"{value * 10000:.0f}bp"


def raroc_color(value: float) -> str:
    """Color code for RAROC value (no spaces - safe for rich markup tags)."""
    if value >= 0.15:
        return "green1"
    elif value >= 0.05:
        return "green"
    elif value >= 0:
        return "yellow"
    elif value >= -0.10:
        return "red"
    return "bright_red"


def display_result(out: RAROCOutput, inp: RAROCInput, settings, title: str = "RAROC Calculation"):
    """Display a full RAROC calculation breakdown."""
    product_desc = PRODUCT_DESCRIPTIONS.get(
        out.product_type, PRODUCT_TYPES.get(out.product_type, out.product_type)
    )

    # Header
    console.print()
    header = Table(box=box.SIMPLE_HEAD, show_header=False, padding=(0, 2))
    header.add_column(style="bold cyan", width=20)
    header.add_column(width=40)
    header.add_row("Product", product_desc)
    header.add_row("Bank", inp.bank or "(not specified)")
    sp_equiv = MOODYS_TO_SP.get(out.rating, "")
    rating_display = f"{out.rating} / {sp_equiv}" if sp_equiv else out.rating
    header.add_row("Rating", f"{rating_display} (PD = {out.pd:.4%})")
    header.add_row("GRR", f"{out.global_grr:.0%}")
    header.add_row("Maturity", f"{inp.residual_maturity:.0f} months ({inp.residual_maturity/12:.1f}y)")
    header.add_row("Confirmed", "Yes" if inp.confirmed else "No")
    console.print(Panel(header, title=f"[bold]{title}[/bold]", border_style="cyan"))

    # Deal parameters
    deal = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    deal.add_column("Parameter", style="dim")
    deal.add_column("Value", justify="right")
    deal.add_row("Average Volume (authorized)", fmt_num(inp.average_volume))
    deal.add_row("Average Drawn", fmt_num(inp.average_drawn))
    deal.add_row("Spread", fmt_bp(inp.spread))
    deal.add_row("Commitment Fee", fmt_bp(inp.commitment_fee))
    if inp.flat_fee:
        deal.add_row("Flat Fee", fmt_num(inp.flat_fee))
    if inp.participation_fee:
        deal.add_row("Participation Fee", fmt_num(inp.participation_fee))
    if inp.upfront_fee:
        deal.add_row("Upfront Fee", fmt_num(inp.upfront_fee))
    if inp.collateral_stress_value:
        deal.add_row("Collateral (stress)", fmt_num(inp.collateral_stress_value))
    console.print(Panel(deal, title="[bold]Deal Parameters[/bold]", border_style="blue"))

    # Calculation breakdown
    calc = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    calc.add_column("Metric", style="bold", width=30)
    calc.add_column("Value", justify="right", width=20)
    calc.add_column("Detail", style="dim", width=35)

    calc.add_row(
        "Revenue",
        fmt_num(out.revenue, 2),
        f"spread*drawn + fees",
    )
    calc.add_row(
        "Cost",
        fmt_num(out.cost, 2),
        "user-provided" if inp.user_cost is not None else f"revenue * {settings.risk_free_rate:.0%} coeff",
    )
    calc.add_row("", "", "")

    calc.add_row(
        "Exposure at Default (EAD)",
        fmt_num(out.exposure, 2),
        f"weighted drawn + vol - collateral",
    )
    calc.add_row(
        "Asset Correlation (R)",
        f"{out.correlation:.6f}",
        "Basel IRB corporate formula",
    )
    calc.add_row(
        "Risk Weight (K)",
        f"{out.risk_weight:.6f}  ({out.risk_weight*100:.4f}%)",
        f"b={out.maturity_adj_b:.6f}",
    )
    calc.add_row(
        "FPE (Economic Capital)",
        fmt_num(out.fpe, 2),
        "EAD * K",
    )
    calc.add_row("", "", "")

    calc.add_row(
        "PD (Basel)",
        f"{out.pd_basel2:.6f}  ({out.pd_basel2*100:.4f}%)",
        f"PD * (1 - GRR)",
    )
    calc.add_row(
        "Expected Loss",
        fmt_num(out.average_loss, 2),
        "EAD * PD_Basel",
    )
    calc.add_row("", "", "")

    calc.add_row("Gross Margin", fmt_num(out.gross_margin, 2), "Revenue - Cost")
    calc.add_row(
        "Return on FPE",
        fmt_num(out.revenues_of_fpe, 2),
        f"Rf({settings.risk_free_rate:.2%}) * FPE",
    )
    calc.add_row("Net Margin", fmt_num(out.net_margin, 2), "Gross - EL + Ret.FPE")
    calc.add_row("Taxes", fmt_num(out.taxes, 2), f"NetMargin * {settings.tax_rate:.0%}")

    console.print(Panel(calc, title="[bold]Calculation Breakdown[/bold]", border_style="green"))

    # RAROC result
    raroc_text = Text()
    raroc_text.append("  RAROC = ", style="bold")
    raroc_text.append(f"{out.raroc:.4%}", style=raroc_color(out.raroc))
    raroc_text.append(f"   ({out.raroc*100:.2f}%)", style="dim")

    formula = Text()
    formula.append("  (1-tax) * [(Rev - Cost - EL) / FPE + Rf]", style="dim italic")

    rc = raroc_color(out.raroc)
    result_panel = Panel(
        Text.from_markup(
            f"  [bold]RAROC = [{rc}]{out.raroc:.4%}[/][/bold]"
            f"   ({out.raroc*100:.2f}%)\n"
            f"  [dim italic](1-tax) * [(Rev - Cost - EL) / FPE + Rf][/dim italic]"
        ),
        title="[bold]Result[/bold]",
        border_style=rc,
    )
    console.print(result_panel)
    console.print()


def display_sensitivity(
    results: list,
    parameter: str,
    base_raroc: float,
    inp: RAROCInput,
):
    """Display sensitivity analysis as a table with visual bars."""
    table = Table(
        title=f"Sensitivity: {parameter.upper()}",
        box=box.ROUNDED,
        padding=(0, 1),
    )
    table.add_column(parameter.upper(), justify="right", style="cyan", width=12)
    if parameter == "rating":
        table.add_column("Rating", width=6)
    table.add_column("RAROC", justify="right", width=10)
    table.add_column("Delta", justify="right", width=10)
    table.add_column("", width=40)

    # Find range for bar scaling
    rarocs = [out.raroc for _, out in results]
    r_min = min(rarocs + [0])
    r_max = max(rarocs + [0])
    r_range = r_max - r_min if r_max != r_min else 1.0

    repo = Repository()

    for val, out in results:
        delta = out.raroc - base_raroc
        # Bar
        bar_width = int(abs(out.raroc - r_min) / r_range * 30)
        bar = "\u2588" * max(bar_width, 1)
        bar_color = raroc_color(out.raroc)

        delta_str = f"{delta:+.2%}" if delta != 0 else "base"
        delta_style = "green" if delta > 0 else ("red" if delta < 0 else "dim")

        if parameter == "grr":
            param_str = f"{val:.0%}"
        elif parameter == "rating":
            param_str = f"{val:+.0f}"
            rating_name = repo.roll_rating(inp.rating, int(val))
            table.add_row(
                param_str,
                rating_name,
                f"{out.raroc:.2%}",
                f"[{delta_style}]{delta_str}[/]",
                f"[{bar_color}]{bar}[/]",
            )
            continue
        elif parameter == "spread_delta":
            param_str = f"{val*10000:+.0f}bp"
        elif parameter == "maturity":
            param_str = f"{val:.0f}m"
        elif parameter in ("cost_pct", "revenue_pct"):
            param_str = f"{val:+.0%}"
        else:
            param_str = f"{val:,.0f}"

        table.add_row(
            param_str,
            f"{out.raroc:.2%}",
            f"[{delta_style}]{delta_str}[/]",
            f"[{bar_color}]{bar}[/]",
        )

    console.print()
    console.print(table)
    console.print()


# ── CLI Commands ──────────────────────────────────────────────────

@click.group()
@click.option("--regime", type=click.Choice(["basel2", "basel3"]), default="basel3",
              help="Regulatory regime (default: basel3)")
@click.pass_context
def cli(ctx, regime):
    """RAROC Engine - Risk-Adjusted Return on Capital Calculator.

    Modern Python implementation with Basel II and Basel III/IV support.
    Rebuilt from the BFinance Java application (2007).
    """
    ctx.ensure_object(dict)
    ctx.obj["regime"] = regime


@cli.command()
@click.pass_context
def demo(ctx):
    """Run demo scenarios with realistic banking deals."""
    regime = ctx.obj["regime"]
    repo = Repository()
    calc = RAROCCalculator(repo, EngineConfig(regime=regime))

    console.print(
        Panel(
            f"[bold cyan]RAROC Engine v1.0[/bold cyan]\n"
            f"Regulatory regime: [bold]{regime.upper()}[/bold]\n"
            f"Risk-free rate: {repo.settings.risk_free_rate:.2%}  |  "
            f"Tax rate: {repo.settings.tax_rate:.0%}",
            title="[bold]Demo Mode[/bold]",
            border_style="cyan",
        )
    )

    # Scenario 1: MLT Credit Facility
    deal1 = RAROCInput(
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
    out1 = calc.calculate(deal1)
    display_result(out1, deal1, repo.settings, "Scenario 1: MLT Credit Facility")

    # Scenario 2: Short-Term Revolving Credit
    deal2 = RAROCInput(
        product_type="short_term_credit",
        operation="Revolving Credit Facility",
        bank="HSBC",
        average_volume=20_000_000,
        average_drawn=15_000_000,
        initial_maturity=12,
        residual_maturity=12,
        spread=0.008,
        commitment_fee=0.001,
        rating="A3",
        confirmed=True,
        global_grr=0.0,
    )
    out2 = calc.calculate(deal2)
    display_result(out2, deal2, repo.settings, "Scenario 2: Short-Term RCF")

    # Scenario 3: Bank Guarantee
    deal3 = RAROCInput(
        product_type="caution",
        operation="Performance Bond",
        bank="Societe Generale",
        average_volume=10_000_000,
        average_drawn=10_000_000,
        initial_maturity=36,
        residual_maturity=36,
        spread=0.005,
        flat_fee=50_000,
        rating="Baa1",
        confirmed=False,
        global_grr=0.65,
    )
    out3 = calc.calculate(deal3)
    display_result(out3, deal3, repo.settings, "Scenario 3: Bank Guarantee")

    # Scenario 4: IR Swap
    deal4 = RAROCInput(
        product_type="ir_swap",
        operation="5Y Interest Rate Swap",
        bank="Deutsche Bank",
        average_volume=100_000_000,
        average_drawn=2_500_000,  # MTM exposure
        initial_maturity=60,
        residual_maturity=60,
        flat_fee=25_000,
        rating="A1",
        confirmed=False,
        global_grr=0.0,
    )
    out4 = calc.calculate(deal4)
    display_result(out4, deal4, repo.settings, "Scenario 4: Interest Rate Swap")

    # Summary table
    summary = Table(
        title="Portfolio RAROC Summary",
        box=box.ROUNDED,
        padding=(0, 2),
    )
    summary.add_column("Scenario", style="bold")
    summary.add_column("Product")
    summary.add_column("EAD", justify="right")
    summary.add_column("FPE", justify="right")
    summary.add_column("Revenue", justify="right")
    summary.add_column("RAROC", justify="right")

    for i, (deal, out, name) in enumerate([
        (deal1, out1, "MLT Credit"),
        (deal2, out2, "RCF"),
        (deal3, out3, "Guarantee"),
        (deal4, out4, "IR Swap"),
    ], 1):
        summary.add_row(
            f"{i}",
            name,
            fmt_num(out.exposure),
            fmt_num(out.fpe),
            fmt_num(out.revenue),
            f"[{raroc_color(out.raroc)}]{out.raroc:.2%}[/]",
        )

    # Portfolio aggregate
    total_fpe = sum(o.fpe for o in [out1, out2, out3, out4])
    total_rev = sum(o.revenue for o in [out1, out2, out3, out4])
    total_cost = sum(o.cost for o in [out1, out2, out3, out4])
    total_el = sum(o.average_loss for o in [out1, out2, out3, out4])
    if total_fpe > 0:
        tax = repo.settings.tax_rate
        rfr = repo.settings.risk_free_rate
        portfolio_raroc = (1 - tax) * ((total_rev - total_cost - total_el) / total_fpe + rfr)
    else:
        portfolio_raroc = 0
    summary.add_section()
    summary.add_row(
        "",
        "[bold]PORTFOLIO[/bold]",
        fmt_num(sum(o.exposure for o in [out1, out2, out3, out4])),
        fmt_num(total_fpe),
        fmt_num(total_rev),
        f"[bold {raroc_color(portfolio_raroc)}]{portfolio_raroc:.2%}[/]",
    )

    console.print(summary)
    console.print()

    # GRR Sensitivity on deal 1
    console.print("[bold]Sensitivity Analysis: GRR impact on MLT Credit[/bold]")
    grr_results = calc.sensitivity(deal1, "grr", 0.0, 0.8, 0.1)
    display_sensitivity(grr_results, "grr", out1.raroc, deal1)

    # Rating sensitivity on deal 1
    console.print("[bold]Sensitivity Analysis: Rating shifts on MLT Credit[/bold]")
    rating_results = calc.sensitivity(deal1, "rating", -4, 4, 1)
    display_sensitivity(rating_results, "rating", out1.raroc, deal1)


@cli.command()
@click.option("--product", "-p", type=click.Choice(list(PRODUCT_TYPES.keys())),
              required=True, help="Product type")
@click.option("--avg-drawn", "-d", type=float, required=True, help="Average drawn amount")
@click.option("--avg-volume", "-v", type=float, default=None, help="Average volume (authorized). Defaults to avg-drawn")
@click.option("--spread", "-s", type=float, default=0.0, help="Spread as decimal (0.015 = 150bp)")
@click.option("--commit-fee", type=float, default=0.0, help="Commitment fee as decimal on undrawn")
@click.option("--flat-fee", type=float, default=0.0, help="Flat fee (absolute amount)")
@click.option("--participation-fee", type=float, default=0.0, help="Participation fee (absolute)")
@click.option("--upfront-fee", type=float, default=0.0, help="Upfront fee (absolute)")
@click.option("--user-cost", type=float, default=None, help="User-provided cost (overrides theoretical)")
@click.option("--rating", "-r", type=str, default="BBB+",
              help="Rating: Moody's (Baa1), S&P (BBB+), or Fitch (BBB+)")
@click.option("--maturity", "-m", type=float, default=60, help="Residual maturity in months")
@click.option("--grr", "-g", type=float, default=0.0, help="Global Guarantee Recovery Rate (0-1)")
@click.option("--confirmed/--not-confirmed", default=True, help="Confirmed facility")
@click.option("--collateral-stress", type=float, default=0.0, help="Collateral stress value")
@click.option("--bank", type=str, default="", help="Bank name")
@click.pass_context
def calc(ctx, product, avg_drawn, avg_volume, spread, commit_fee, flat_fee,
         participation_fee, upfront_fee, user_cost, rating, maturity, grr,
         confirmed, collateral_stress, bank):
    """Calculate RAROC for a single deal. Accepts any rating format."""
    regime = ctx.obj["regime"]
    repo = Repository()
    calculator = RAROCCalculator(repo, EngineConfig(regime=regime))

    if avg_volume is None:
        avg_volume = avg_drawn

    inp = RAROCInput(
        product_type=product,
        bank=bank,
        average_drawn=avg_drawn,
        average_volume=avg_volume,
        initial_maturity=maturity,
        residual_maturity=maturity,
        spread=spread,
        commitment_fee=commit_fee,
        flat_fee=flat_fee,
        participation_fee=participation_fee,
        upfront_fee=upfront_fee,
        user_cost=user_cost,
        rating=rating,
        confirmed=confirmed,
        global_grr=grr,
        collateral_stress_value=collateral_stress,
    )

    out = calculator.calculate(inp)

    console.print(f"\n[dim]Regime: {regime.upper()}[/dim]")
    display_result(out, inp, repo.settings)


@cli.command()
@click.argument("input_file", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Output file (.xlsx or .csv). Default: stdout")
@click.pass_context
def batch(ctx, input_file, output):
    """Process multiple deals from a CSV file.

    CSV columns: product_type, average_drawn, average_volume, spread,
    commitment_fee, flat_fee, rating, residual_maturity, confirmed, global_grr,
    collateral_stress_value, user_cost, bank, operation
    """
    regime = ctx.obj["regime"]
    repo = Repository()
    calculator = RAROCCalculator(repo, EngineConfig(regime=regime))

    def _f(val, default=0.0):
        """Parse float from CSV, treating empty strings as default."""
        if val is None or val == "":
            return default
        return float(val)

    deals = []
    with open(input_file, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            avg_drawn = _f(row.get("average_drawn"))
            inp = RAROCInput(
                product_type=row.get("product_type", "mlt_credit").strip(),
                operation=row.get("operation", "").strip(),
                bank=row.get("bank", "").strip(),
                average_drawn=avg_drawn,
                average_volume=_f(row.get("average_volume")) or avg_drawn,
                spread=_f(row.get("spread")),
                commitment_fee=_f(row.get("commitment_fee")),
                flat_fee=_f(row.get("flat_fee")),
                participation_fee=_f(row.get("participation_fee")),
                upfront_fee=_f(row.get("upfront_fee")),
                user_cost=_f(row.get("user_cost"), None) if row.get("user_cost", "").strip() else None,
                rating=row.get("rating", "Baa1").strip(),
                residual_maturity=_f(row.get("residual_maturity"), 60),
                initial_maturity=_f(row.get("residual_maturity"), 60),
                confirmed=row.get("confirmed", "true").strip().lower() in ("true", "1", "yes"),
                global_grr=_f(row.get("global_grr")),
                collateral_stress_value=_f(row.get("collateral_stress_value")),
            )
            out = calculator.calculate(inp)
            deals.append((inp, out))

    if output and output.endswith(".xlsx"):
        _write_excel(deals, output, repo.settings, regime)
        console.print(f"[green]Results written to {output}[/green]")
    elif output:
        _write_csv_output(deals, output)
        console.print(f"[green]Results written to {output}[/green]")
    else:
        # Display summary table
        table = Table(title=f"Batch Results ({regime.upper()})", box=box.ROUNDED)
        table.add_column("#", style="dim", width=4)
        table.add_column("Operation", width=25)
        table.add_column("Product", width=15)
        table.add_column("Bank", width=15)
        table.add_column("Rating", width=6)
        table.add_column("EAD", justify="right", width=14)
        table.add_column("FPE", justify="right", width=14)
        table.add_column("Revenue", justify="right", width=12)
        table.add_column("RAROC", justify="right", width=10)

        for i, (inp, out) in enumerate(deals, 1):
            table.add_row(
                str(i),
                inp.operation or "-",
                inp.product_type,
                inp.bank or "-",
                out.rating,
                fmt_num(out.exposure),
                fmt_num(out.fpe),
                fmt_num(out.revenue),
                f"[{raroc_color(out.raroc)}]{out.raroc:.2%}[/]",
            )

        console.print(table)
        console.print(f"\n[dim]{len(deals)} deals processed[/dim]")


@cli.command("sensitivity")
@click.option("--product", "-p", type=click.Choice(list(PRODUCT_TYPES.keys())),
              default="mlt_credit", help="Product type")
@click.option("--avg-drawn", "-d", type=float, default=35_000_000)
@click.option("--avg-volume", "-v", type=float, default=50_000_000)
@click.option("--spread", "-s", type=float, default=0.015)
@click.option("--commit-fee", type=float, default=0.002)
@click.option("--rating", "-r", type=str, default="A",
              help="Rating (any agency: A, A2, A-, etc.)")
@click.option("--maturity", "-m", type=float, default=60)
@click.option("--grr", "-g", type=float, default=0.55)
@click.option("--confirmed/--not-confirmed", default=True)
@click.option("--parameter", "param", type=click.Choice(
    ["grr", "rating", "spread_delta", "maturity"]),
    default="grr", help="Parameter to vary")
@click.pass_context
def sensitivity_cmd(ctx, product, avg_drawn, avg_volume, spread, commit_fee,
                    rating, maturity, grr, confirmed, param):
    """Run sensitivity analysis on a deal parameter."""
    regime = ctx.obj["regime"]
    repo = Repository()
    calculator = RAROCCalculator(repo, EngineConfig(regime=regime))

    rating = normalize_rating(rating)

    inp = RAROCInput(
        product_type=product,
        average_drawn=avg_drawn,
        average_volume=avg_volume,
        spread=spread,
        commitment_fee=commit_fee,
        rating=rating,
        residual_maturity=maturity,
        initial_maturity=maturity,
        confirmed=confirmed,
        global_grr=grr,
    )

    base_out = calculator.calculate(inp)

    # Define ranges per parameter
    ranges = {
        "grr":          (0.0, 0.9, 0.1),
        "rating":       (-5, 5, 1),
        "spread_delta": (-0.005, 0.01, 0.0025),
        "maturity":     (6, 120, 12),
    }

    start, stop, step = ranges[param]
    results = calculator.sensitivity(inp, param, start, stop, step)

    console.print(f"\n[dim]Regime: {regime.upper()} | Base RAROC: {base_out.raroc:.2%}[/dim]")
    display_result(base_out, inp, repo.settings, "Base Deal")
    display_sensitivity(results, param, base_out.raroc, inp)


@cli.command()
def ratings():
    """Display the rating scale with Moody's / S&P / Fitch equivalences."""
    repo = Repository()

    table = Table(title="Credit Rating Scale (all agencies accepted)", box=box.ROUNDED)
    table.add_column("#", style="dim", width=4)
    table.add_column("Moody's", style="bold cyan", width=8)
    table.add_column("S&P / Fitch", style="bold", width=12)
    table.add_column("PD", justify="right", width=10)
    table.add_column("Grade", width=18)
    table.add_column("", width=25)

    grades = {
        "Aaa": "Prime", "Aa1": "High Grade", "Aa2": "High Grade", "Aa3": "High Grade",
        "A1": "Upper Medium", "A2": "Upper Medium", "A3": "Upper Medium",
        "Baa1": "Lower Medium", "Baa2": "Lower Medium", "Baa3": "Lower Medium",
        "Ba1": "Speculative", "Ba2": "Speculative", "Ba3": "Speculative",
        "B1": "Highly Spec.", "B2": "Highly Spec.", "B3": "Highly Spec.",
        "Caa1": "Subst. Risk", "Caa2": "Subst. Risk", "Caa3": "Subst. Risk",
        "Ca": "Extremely Spec.", "C": "Default",
    }

    for i, name in enumerate(RATING_ORDER, 1):
        pd = repo.ratings.get(name, 0)
        sp = MOODYS_TO_SP.get(name, "")
        bar_width = min(int(pd * 100), 25)
        bar = "\u2588" * max(bar_width, 1)
        color = "green" if pd < 0.002 else ("yellow" if pd < 0.02 else ("red" if pd < 0.1 else "bright_red"))
        table.add_row(
            str(i),
            name,
            sp,
            f"{pd:.4%}",
            grades.get(name, ""),
            f"[{color}]{bar}[/]",
        )

    console.print(table)
    console.print(f"\n[dim]Input any format: Moody's (Baa1), S&P (BBB+), or Fitch (BBB+)[/dim]")
    console.print(f"[dim]Source: repository/ratings.csv | PDs based on Moody's/S&P historical default studies[/dim]")


@cli.command()
def products():
    """Display available banking product types."""
    repo = Repository()

    table = Table(title="Banking Product Types", box=box.ROUNDED)
    table.add_column("Key", style="cyan", width=22)
    table.add_column("Description", width=45)
    table.add_column("Cost Coeff", justify="right", width=10)
    table.add_column("Type", width=12)

    for key, desc in PRODUCT_DESCRIPTIONS.items():
        coeff = repo.get_revenue_coeff(key)
        ptype = "Credit" if coeff <= 0.5 else ("Derivative" if coeff >= 0.7 else "Other")
        table.add_row(key, desc, f"{coeff:.0%}", ptype)

    console.print(table)
    console.print(f"\n[dim]Use these keys with --product / -p flag[/dim]")


@cli.command()
def settings():
    """Display current study settings."""
    repo = Repository()
    s = repo.settings

    table = Table(title="Study Settings", box=box.ROUNDED, show_header=False)
    table.add_column("Parameter", style="bold cyan", width=20)
    table.add_column("Value", width=30)

    table.add_row("Study Name", s.study_name or "(not set)")
    table.add_row("Date", s.date)
    table.add_row("Period", f"{s.start_year} - {s.end_year}")
    table.add_row("Risk-Free Rate", f"{s.risk_free_rate:.2%}")
    table.add_row("Tax Rate", f"{s.tax_rate:.0%}")
    table.add_row("Spot Swap Rate", f"{s.spot_swap_rate:.4%}")

    console.print(table)
    console.print(f"\n[dim]Edit repository/settings.csv to change[/dim]")


@cli.command("solve")
@click.option("--product", "-p", type=click.Choice(list(PRODUCT_TYPES.keys())),
              default="mlt_credit", help="Product type")
@click.option("--avg-drawn", "-d", type=float, required=True, help="Average drawn amount")
@click.option("--avg-volume", "-v", type=float, default=None, help="Average volume (defaults to avg-drawn)")
@click.option("--spread", "-s", type=float, default=0.0, help="Current spread (for comparison)")
@click.option("--commit-fee", type=float, default=0.0, help="Commitment fee (decimal)")
@click.option("--flat-fee", type=float, default=0.0, help="Flat fee (absolute)")
@click.option("--rating", "-r", type=str, default="BBB+", help="Rating (any agency: BBB+, Baa1, etc.)")
@click.option("--maturity", "-m", type=float, default=60, help="Residual maturity (months)")
@click.option("--grr", "-g", type=float, default=0.0, help="GRR (0-1)")
@click.option("--confirmed/--not-confirmed", default=True)
@click.option("--target", "-t", type=float, default=0.12,
              help="Target RAROC the bank wants to achieve (default: 12%)")
@click.option("--solve-for", type=click.Choice(["spread", "grr"]), default="spread",
              help="What to solve for (default: spread)")
@click.pass_context
def solve_cmd(ctx, product, avg_drawn, avg_volume, spread, commit_fee, flat_fee,
              rating, maturity, grr, confirmed, target, solve_for):
    """Reverse RAROC: find the minimum spread or GRR for a target RAROC.

    \b
    Answer questions like:
      "My bank targets 12% RAROC -- what's the minimum spread they'll accept?"
      "At my current spread, how much collateral do I need to pledge?"
    """
    regime = ctx.obj["regime"]
    repo = Repository()
    calculator = RAROCCalculator(repo, EngineConfig(regime=regime))

    if avg_volume is None:
        avg_volume = avg_drawn

    # Normalize rating upfront for display
    moodys_rating = normalize_rating(rating)

    inp = RAROCInput(
        product_type=product,
        average_drawn=avg_drawn,
        average_volume=avg_volume,
        spread=spread,
        commitment_fee=commit_fee,
        flat_fee=flat_fee,
        rating=moodys_rating,
        residual_maturity=maturity,
        initial_maturity=maturity,
        confirmed=confirmed,
        global_grr=grr,
    )

    sp_equiv = MOODYS_TO_SP.get(moodys_rating, moodys_rating)

    if solve_for == "spread":
        result = calculator.solve_spread(inp, target_raroc=target)
        solved_spread = result["solved_spread"]
        solved_bp = result["solved_spread_bp"]
        out = result["output"]

        console.print()
        console.print(Panel(
            f"[bold]Target RAROC:[/bold] {target:.0%}\n"
            f"[bold]Rating:[/bold] {moodys_rating} / {sp_equiv} (PD = {out.pd:.4%})\n"
            f"[bold]Maturity:[/bold] {maturity:.0f}m | [bold]GRR:[/bold] {grr:.0%} | "
            f"[bold]Confirmed:[/bold] {'Yes' if confirmed else 'No'}\n"
            f"[bold]Drawn:[/bold] {fmt_num(avg_drawn)} | [bold]Volume:[/bold] {fmt_num(avg_volume)}",
            title="[bold cyan]Reverse RAROC: Solve for Spread[/bold cyan]",
            border_style="cyan",
        ))

        console.print()
        answer = Table(box=box.HEAVY, show_header=False, padding=(0, 3))
        answer.add_column(width=30)
        answer.add_column(width=30)
        answer.add_row(
            "[bold]Minimum Spread[/bold]",
            f"[bold green1]{solved_bp:.1f} bp[/]  ({solved_spread:.4%})"
        )
        answer.add_row(
            "[bold]Achieved RAROC[/bold]",
            f"[bold]{out.raroc:.2%}[/bold]"
        )
        if spread > 0:
            delta = solved_spread - spread
            current_out = calculator.calculate(inp)
            color = "green" if delta <= 0 else "red"
            answer.add_row("", "")
            answer.add_row(
                "[dim]Your current spread[/dim]",
                f"[dim]{spread*10000:.1f} bp  (RAROC = {current_out.raroc:.2%})[/dim]"
            )
            answer.add_row(
                "[dim]Gap to bank's hurdle[/dim]",
                f"[{color}]{delta*10000:+.1f} bp[/]"
            )
        console.print(answer)
        console.print()
        display_result(out, result["input"], repo.settings, f"Deal at {solved_bp:.0f}bp Solved Spread")

    else:  # solve for GRR
        result = calculator.solve_grr(inp, target_raroc=target)
        solved_grr = result["solved_grr"]
        out = result["output"]

        console.print()
        console.print(Panel(
            f"[bold]Target RAROC:[/bold] {target:.0%}\n"
            f"[bold]Rating:[/bold] {moodys_rating} / {sp_equiv} (PD = {out.pd:.4%})\n"
            f"[bold]Spread:[/bold] {spread*10000:.0f}bp | [bold]Maturity:[/bold] {maturity:.0f}m\n"
            f"[bold]Drawn:[/bold] {fmt_num(avg_drawn)} | [bold]Volume:[/bold] {fmt_num(avg_volume)}",
            title="[bold cyan]Reverse RAROC: Solve for GRR (Collateral)[/bold cyan]",
            border_style="cyan",
        ))

        console.print()
        answer = Table(box=box.HEAVY, show_header=False, padding=(0, 3))
        answer.add_column(width=30)
        answer.add_column(width=30)
        answer.add_row(
            "[bold]Minimum GRR[/bold]",
            f"[bold green1]{solved_grr:.1%}[/]"
        )
        answer.add_row(
            "[bold]Achieved RAROC[/bold]",
            f"[bold]{out.raroc:.2%}[/bold]"
        )
        if grr > 0:
            current_out = calculator.calculate(inp)
            answer.add_row("", "")
            answer.add_row(
                "[dim]Your current GRR[/dim]",
                f"[dim]{grr:.0%}  (RAROC = {current_out.raroc:.2%})[/dim]"
            )
        console.print(answer)
        console.print()
        display_result(out, result["input"], repo.settings, f"Deal at {solved_grr:.0%} GRR")


# ── Output writers ────────────────────────────────────────────────

def _write_excel(deals, output_path, settings, regime):
    """Write results to Excel using xlsxwriter."""
    import xlsxwriter

    wb = xlsxwriter.Workbook(output_path)

    # Formats
    header_fmt = wb.add_format({"bold": True, "bg_color": "#1a237e", "font_color": "white", "border": 1})
    num_fmt = wb.add_format({"num_format": "#,##0", "border": 1})
    pct_fmt = wb.add_format({"num_format": "0.00%", "border": 1})
    bp_fmt = wb.add_format({"num_format": "0.0000", "border": 1})
    text_fmt = wb.add_format({"border": 1})

    # Summary sheet
    ws = wb.add_worksheet("RAROC Summary")
    headers = [
        "Operation", "Product", "Bank", "Rating", "GRR",
        "Avg Drawn", "Avg Volume", "Spread (bp)", "EAD", "Risk Weight",
        "FPE", "Revenue", "Cost", "Expected Loss",
        "Gross Margin", "Net Margin", "RAROC",
    ]
    for c, h in enumerate(headers):
        ws.write(0, c, h, header_fmt)

    for r, (inp, out) in enumerate(deals, 1):
        ws.write(r, 0, inp.operation, text_fmt)
        ws.write(r, 1, inp.product_type, text_fmt)
        ws.write(r, 2, inp.bank, text_fmt)
        ws.write(r, 3, out.rating, text_fmt)
        ws.write(r, 4, out.global_grr, pct_fmt)
        ws.write(r, 5, inp.average_drawn, num_fmt)
        ws.write(r, 6, inp.average_volume, num_fmt)
        ws.write(r, 7, inp.spread * 10000, num_fmt)
        ws.write(r, 8, out.exposure, num_fmt)
        ws.write(r, 9, out.risk_weight, bp_fmt)
        ws.write(r, 10, out.fpe, num_fmt)
        ws.write(r, 11, out.revenue, num_fmt)
        ws.write(r, 12, out.cost, num_fmt)
        ws.write(r, 13, out.average_loss, num_fmt)
        ws.write(r, 14, out.gross_margin, num_fmt)
        ws.write(r, 15, out.net_margin, num_fmt)
        ws.write(r, 16, out.raroc, pct_fmt)

    ws.set_column(0, 0, 25)
    ws.set_column(1, 4, 15)
    ws.set_column(5, 15, 18)
    ws.set_column(16, 16, 12)

    # Metadata
    ws2 = wb.add_worksheet("Settings")
    ws2.write(0, 0, "Regime", header_fmt)
    ws2.write(0, 1, regime.upper(), text_fmt)
    ws2.write(1, 0, "Risk-Free Rate", header_fmt)
    ws2.write(1, 1, settings.risk_free_rate, pct_fmt)
    ws2.write(2, 0, "Tax Rate", header_fmt)
    ws2.write(2, 1, settings.tax_rate, pct_fmt)

    wb.close()


def _write_csv_output(deals, output_path):
    """Write results to CSV."""
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "operation", "product_type", "bank", "rating", "grr",
            "average_drawn", "average_volume", "spread",
            "exposure", "risk_weight", "fpe",
            "revenue", "cost", "expected_loss",
            "gross_margin", "net_margin", "raroc",
        ])
        for inp, out in deals:
            writer.writerow([
                inp.operation, inp.product_type, inp.bank, out.rating, out.global_grr,
                inp.average_drawn, inp.average_volume, inp.spread,
                out.exposure, out.risk_weight, out.fpe,
                out.revenue, out.cost, out.average_loss,
                out.gross_margin, out.net_margin, out.raroc,
            ])


def main():
    cli()
