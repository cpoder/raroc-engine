"""Wallet-grade aggregates over per-period engine output.

Consumes a sequence of :class:`raroc_engine.period_engine.PeriodOutput`
rows (or anything duck-typing the same discount-layer fields — ``df``,
``revenue_pv``, ``net_margin_pv``, ``drawn_pv`` — alongside the
per-period RAROC fields) and produces the headline numbers the App's
wallet view needs:

- **NPV** of borrower cost, bank net margin, bank costs and drawn
  balance under the discount cascade locked in D-0003;
- **Total cost** of the facility, both **bank-side**
  (operating cost + funding + EL) and **borrower-side**
  (spread + commit fee + fees), in undiscounted and PV flavours;
- **Effective spread**: the flat constant spread on a hypothetical
  bullet facility economically equivalent to the actual schedule —
  the headline number Term-Sheet Doctor (Module A) shows for
  cross-deal comparison;
- **Average RAROC** (time-weighted) and **capital-weighted RAROC**
  (FPE × dt weighted, the spec §7 ``weighted_raroc``).

Spec: ``docs/engine/multiperiod-spec.md`` §7. Tolerances live in §10:
0.1% relative on NPV totals, 0.5 bp absolute on effective spread,
0.5 bp absolute on RAROC.

The module is import-cycle-free: the type of ``PeriodOutput`` is
referenced only under ``TYPE_CHECKING`` so :mod:`period_engine` can
import :mod:`aggregate` at the top of its file without bouncing back.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import TYPE_CHECKING, Iterable, Sequence

if TYPE_CHECKING:
    from .period_engine import DiscountSpec, PeriodOutput


# ── Result type ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class FacilityAggregates:
    """Wallet-grade headline metrics for one facility's life.

    All NPVs use the period discount factors already attached to each
    row (``r.df``). Use :func:`attach_discount_factors` to refresh DFs
    on a list of rows at a different discount rate.

    ``avg_raroc`` is the **time-weighted** mean (every period's RAROC
    weighted by its ``dt_years``). ``capital_weighted_raroc`` is the
    **FPE × dt** weighted mean — the same number spec §7 calls
    ``weighted_raroc``. For a 1-period, 1y bullet facility the two
    collapse to the single-period RAROC exactly.
    """

    # NPV view (discounted)
    npv_borrower_cost: float          # Σ revenue_i × DF_i (= borrower outflow PV)
    npv_bank_net_margin: float        # Σ net_margin_i × DF_i
    npv_bank_costs: float             # Σ (cost_i + funding_i + EL_i) × DF_i
    npv_drawn_balance: float          # Σ avg_drawn_i × dt_i × DF_i

    # Undiscounted totals
    total_borrower_cost_undisc: float  # = total_revenue_undisc (same cash flow)
    total_bank_costs_undisc: float
    total_revenue_undisc: float
    total_el_undisc: float
    total_funding_cost_undisc: float

    # Capital + exposure usage
    avg_exposure: float
    fpe_years: float                  # Σ FPE_i × dt_i (capital usage proxy)

    # Effective spread
    effective_spread: float           # decimal
    effective_spread_bp: float        # basis points

    # RAROC
    avg_raroc: float
    capital_weighted_raroc: float

    # Period count
    n_periods: int
    total_years: float

    def to_dict(self) -> dict:
        """Dict view with the original engine keys retained for back-compat.

        :class:`raroc_engine.period_engine.PeriodEngine` uses this to populate
        ``PeriodEngineOutput.aggregates`` — Task 1.3 callers indexing by
        keys like ``aggregates["fpe_weighted_raroc"]`` continue to work.
        """
        d = asdict(self)
        d["fpe_weighted_raroc"] = self.capital_weighted_raroc
        return d


# ── Public API ───────────────────────────────────────────────────────


def aggregate_periods(rows: Sequence["PeriodOutput"]) -> FacilityAggregates:
    """Compute :class:`FacilityAggregates` from a sequence of period rows.

    Rows must already carry the discount-layer fields (``df``,
    ``revenue_pv``, ``net_margin_pv``, ``drawn_pv``). The default
    :class:`PeriodEngine` populates them; call
    :func:`attach_discount_factors` if you constructed rows by hand
    or want to re-discount at a different rate.

    An empty input returns an all-zero aggregate (no-op safe).
    """
    if not rows:
        return _zero_aggregates()

    revenue_pv = sum(r.revenue_pv for r in rows)
    net_margin_pv = sum(r.net_margin_pv for r in rows)
    drawn_pv = sum(r.drawn_pv for r in rows)

    # Bank costs flow line by line: cost (operating) + funding + EL.
    # The FPE return is *not* a cost — it's the bank's return on the
    # capital it has tied up, which already lives inside ``net_margin``.
    bank_costs_undisc = sum(r.cost + r.funding_cost + r.el for r in rows)
    npv_bank_costs = sum((r.cost + r.funding_cost + r.el) * r.df for r in rows)

    total_revenue = sum(r.revenue for r in rows)
    total_el = sum(r.el for r in rows)
    total_funding = sum(r.funding_cost for r in rows)
    total_dt = sum(r.dt_years for r in rows)
    exposure_dt = sum(r.exposure * r.dt_years for r in rows)
    fpe_dt = sum(r.fpe * r.dt_years for r in rows)

    avg_exposure = exposure_dt / total_dt if total_dt > 0 else 0.0
    effective_spread = revenue_pv / drawn_pv if drawn_pv > 0 else 0.0

    capital_weighted_raroc = (
        sum(r.raroc * r.fpe * r.dt_years for r in rows) / fpe_dt
        if fpe_dt > 0
        else 0.0
    )
    avg_raroc = (
        sum(r.raroc * r.dt_years for r in rows) / total_dt
        if total_dt > 0
        else 0.0
    )

    return FacilityAggregates(
        npv_borrower_cost=revenue_pv,
        npv_bank_net_margin=net_margin_pv,
        npv_bank_costs=npv_bank_costs,
        npv_drawn_balance=drawn_pv,
        total_borrower_cost_undisc=total_revenue,
        total_bank_costs_undisc=bank_costs_undisc,
        total_revenue_undisc=total_revenue,
        total_el_undisc=total_el,
        total_funding_cost_undisc=total_funding,
        avg_exposure=avg_exposure,
        fpe_years=fpe_dt,
        effective_spread=effective_spread,
        effective_spread_bp=effective_spread * 10000.0,
        avg_raroc=avg_raroc,
        capital_weighted_raroc=capital_weighted_raroc,
        n_periods=len(rows),
        total_years=total_dt,
    )


def attach_discount_factors(
    rows: Iterable["PeriodOutput"],
    discount: "DiscountSpec",
) -> None:
    """In-place: refresh DF + PV fields on ``rows`` from ``discount``.

    For each row sets ``df = (1 + r_i) ^ (-t_end_years)`` and the three
    PV columns the aggregates consume. Lets callers re-discount an
    existing engine run at a new rate (e.g. an advisor switching from
    risk-free to a borrower-WACC discount curve) without re-running
    the period engine.
    """
    for r in rows:
        rate = discount.rate_at(r.t_end_years, period_end=r.end)
        r.df = (1.0 + rate) ** (-r.t_end_years)
        r.revenue_pv = r.revenue * r.df
        r.net_margin_pv = r.net_margin * r.df
        r.drawn_pv = r.avg_drawn * r.dt_years * r.df


# ── Internals ────────────────────────────────────────────────────────


def _zero_aggregates() -> FacilityAggregates:
    return FacilityAggregates(
        npv_borrower_cost=0.0,
        npv_bank_net_margin=0.0,
        npv_bank_costs=0.0,
        npv_drawn_balance=0.0,
        total_borrower_cost_undisc=0.0,
        total_bank_costs_undisc=0.0,
        total_revenue_undisc=0.0,
        total_el_undisc=0.0,
        total_funding_cost_undisc=0.0,
        avg_exposure=0.0,
        fpe_years=0.0,
        effective_spread=0.0,
        effective_spread_bp=0.0,
        avg_raroc=0.0,
        capital_weighted_raroc=0.0,
        n_periods=0,
        total_years=0.0,
    )


__all__ = [
    "FacilityAggregates",
    "aggregate_periods",
    "attach_discount_factors",
]
