"""Multi-period RAROC engine — per-period loop with discount aggregates.

Walks a :class:`Schedule` row by row, building a synthetic
:class:`RAROCInput` for each period (period-specific commitment, drawn,
residual maturity, allocated fees) and running it through the existing
single-period :class:`RAROCCalculator`. dt-dependent fields (revenue,
funding cost, EL, FPE return) are post-scaled by ``period.dt_years``
for sub-annual periods; for the Q1 fixtures every period has dt=1.0
so the calculator output flows through unchanged.

Spec: ``docs/engine/multiperiod-spec.md``. Tolerances live in §10:
0.5 bp absolute on per-period RAROC, 0.1% relative on NPV totals,
1e-12 absolute on the single-period parity contract (§9).

The output additionally surfaces ``principal_repayment`` per period —
the capital flowing back to the bank between periods (and the full
residual at maturity). The NPV / equity-cash-flow layer (Task 1.4)
consumes this to discount the bank's capital releases correctly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Sequence

from scipy.stats import norm

from .aggregate import aggregate_periods
from .calculator import RAROCCalculator
from .config import EngineConfig
from .curves import (
    STATUS_FRESH,
    STATUS_PRIORITY,
    STATUS_SCALAR_FALLBACK,
    CurveRepository,
)
from .models import RAROCInput, RAROCOutput, normalize_rating
from .repository import Repository
from .schedule import Period, Schedule


# ── Discount spec ────────────────────────────────────────────────────


@dataclass
class DiscountSpec:
    """Per-calc discount rate specification (spec §5, D-0003).

    Three shapes:

    - ``kind="scalar"`` → use ``rate`` for every period. The Q1 fixture
      path; also the fallback when the curve cascade returns no data.
    - ``kind="curve"`` → look up ``name`` against the curve repository.
      Not exercised in Q1; the F-09 / F-13 internal follow-ups
      cover the curve table and refresh job.
    - ``kind="schedule"`` → linearly interpolate between ``points``,
      a sorted list of ``(date, rate)`` tuples. Used by advisors who
      want their borrower's WACC as the discount curve.
    """

    kind: str = "scalar"
    rate: float = 0.0325
    name: Optional[str] = None
    points: Optional[Sequence[tuple[date, float]]] = None
    day_count: str = "Act/365F"

    def rate_at(self, t_years: float, period_end: Optional[date] = None) -> float:
        """Resolve the discount rate at year offset ``t_years`` from period-1 start.

        For ``schedule`` shapes ``period_end`` (the calendar date of the
        period end) is used to interpolate; ``t_years`` carries the same
        information once a reference date is known.
        """
        if self.kind == "scalar":
            return float(self.rate)
        if self.kind == "curve":
            # F-09 / F-13: curve lookup lands with the multi-period engine in
            # Phase 1 Q2. Until then, falling back to the scalar keeps the
            # engine honest with the D-0003 cascade ("never crash on missing
            # curve") and produces a deterministic answer.
            return float(self.rate)
        if self.kind == "schedule":
            if not self.points:
                return float(self.rate)
            if period_end is None:
                # Without a calendar date we can't interpolate by date;
                # treat ``t_years`` as the x-axis.
                xs = [(p[0], float(p[1])) for p in self.points]
                # When the schedule is keyed by date, sort by date and pick
                # the right neighbour by linear interpolation in time-delta.
                ref = xs[0][0]
                pts = [((x[0] - ref).days / 365.0, x[1]) for x in xs]
                pts.sort()
                if t_years <= pts[0][0]:
                    return pts[0][1]
                if t_years >= pts[-1][0]:
                    return pts[-1][1]
                for (t0, r0), (t1, r1) in zip(pts, pts[1:]):
                    if t0 <= t_years <= t1 and t1 > t0:
                        w = (t_years - t0) / (t1 - t0)
                        return r0 + w * (r1 - r0)
            else:
                pts = sorted(self.points, key=lambda p: p[0])
                if period_end <= pts[0][0]:
                    return float(pts[0][1])
                if period_end >= pts[-1][0]:
                    return float(pts[-1][1])
                for (d0, r0), (d1, r1) in zip(pts, pts[1:]):
                    if d0 <= period_end <= d1 and d1 > d0:
                        span = (d1 - d0).days
                        w = (period_end - d0).days / span if span else 0.0
                        return float(r0) + w * (float(r1) - float(r0))
        return float(self.rate)

    def curve_status(self) -> str:
        """Match the D-0003 cascade flags surfaced on every output."""
        if self.kind == "scalar":
            return "scalar"
        if self.kind == "schedule":
            return "schedule"
        return "scalar_fallback"


# ── Per-period output row ────────────────────────────────────────────


@dataclass
class PeriodOutput:
    """One row of the period engine's per-period output.

    Field names track ``docs/engine/multiperiod-spec.md`` §6 / §3 and the
    column headers in the YAML fixtures' ``expected.per_period`` blocks.
    The cumulative RAROC fields (``revenue``, ``cost``, ``fpe``, ``raroc``…)
    are computed against the period's commitment / drawn / residual
    maturity; the discount layer fields (``t_end_years``, ``df``,
    ``revenue_pv``…) attach the end-of-period DF and the corresponding
    PVs for the §7 aggregates.
    """

    # Period metadata
    index: int
    start: date
    end: date
    dt_years: float
    commitment: float
    avg_drawn: float
    remaining_maturity_years: float

    # Revenue / cost / funding
    revenue: float = 0.0
    cost: float = 0.0
    funding_cost: float = 0.0

    # Risk inputs / capital
    exposure: float = 0.0
    pd: float = 0.0
    pd_basel2: float = 0.0
    lgd: float = 0.0
    correlation: float = 0.0          # R
    maturity_adj_b: float = 0.0       # b
    z: float = 0.0
    K_irb: float = 0.0
    sa_rw: float = 0.0
    K_floor: float = 0.0
    K: float = 0.0
    fpe: float = 0.0
    el: float = 0.0

    # Margins
    gross_margin: float = 0.0
    fpe_return: float = 0.0
    net_margin: float = 0.0
    raroc: float = 0.0

    # Capital release (principal repayment at end of period; full residual
    # on the last row). Feeds the equity-cash-flow / NPV layer downstream.
    principal_repayment: float = 0.0

    # Discount layer
    t_end_years: float = 0.0
    df: float = 0.0
    revenue_pv: float = 0.0
    net_margin_pv: float = 0.0
    drawn_pv: float = 0.0

    # Floating-rate fixing (D-0003, Task 1.5). ``floating_index`` /
    # ``fixing_rate`` echo the period's resolved fixing. ``all_in_rate``
    # is ``fixing_rate + spread`` for floating periods and ``None`` for
    # fixed-rate periods. ``curve_status`` carries the D-0003 cascade
    # flag (``fresh`` / ``stale`` / ``interpolated`` / ``scalar_fallback``)
    # for the App's UI badge.
    floating_index: Optional[str] = None
    fixing_rate: Optional[float] = None
    all_in_rate: Optional[float] = None
    curve_status: Optional[str] = None

    @property
    def raroc_bp(self) -> float:
        return self.raroc * 10000.0


# ── Engine I/O ───────────────────────────────────────────────────────


@dataclass
class PeriodEngineInput:
    """All inputs the period engine needs to compute a facility's life.

    ``deal`` carries the static facets (rating, product, GRR, spread,
    commit fee, confirmed/uncommitted). ``schedule`` carries the
    time-varying facets per spec §3. ``discount`` is the D-0003 spec.
    ``engine_config`` is optional; the default ``EngineConfig`` matches
    today's calculator and the Q1 fixtures.

    ``curves`` is an optional :class:`CurveRepository`. When supplied,
    any period whose ``floating_index`` is set but ``fixing_rate`` is
    ``None`` is resolved against the curve at run time. ``valuation_date``
    is the cascade's reference date (defaults to ``schedule.start``).
    """

    deal: RAROCInput
    schedule: Schedule
    discount: DiscountSpec = field(default_factory=DiscountSpec)
    engine_config: Optional[EngineConfig] = None
    curves: Optional[CurveRepository] = None
    valuation_date: Optional[date] = None


@dataclass
class PeriodEngineOutput:
    """Engine output: per-period rows, §7 aggregates, discount + engine meta."""

    per_period: List[PeriodOutput]
    aggregates: dict
    discount_meta: dict
    engine_meta: dict


# ── Engine ───────────────────────────────────────────────────────────


class PeriodEngine:
    """Per-period RAROC loop.

    Reuses :class:`raroc_engine.calculator.RAROCCalculator` for the
    single-period math at each period — guaranteeing the §9
    back-compat contract by construction. Builds the §7 aggregates
    (NPV borrower cost, NPV bank net margin, effective spread,
    FPE-weighted RAROC, total revenue / EL / drawn) on top.
    """

    def __init__(
        self,
        repository: Optional[Repository] = None,
        config: Optional[EngineConfig] = None,
    ):
        self.repo = repository or Repository()
        self.cfg = config or EngineConfig()
        self.calc = RAROCCalculator(self.repo, self.cfg)

    # ── Public API ────────────────────────────────────────────────

    def run(
        self,
        deal: RAROCInput,
        schedule: Schedule,
        discount: Optional[DiscountSpec] = None,
        *,
        curves: Optional[CurveRepository] = None,
        valuation_date: Optional[date] = None,
    ) -> PeriodEngineOutput:
        """Compute the per-period P&L + aggregates for ``deal`` on ``schedule``.

        ``curves`` is an optional :class:`CurveRepository`. When set, any
        floating period without a resolved ``fixing_rate`` is fixed via
        the D-0003 cascade at ``valuation_date`` (default: schedule.start)
        before the per-period loop runs. The resulting per-period
        ``curve_status`` and the worst-tier facility-level rollup are
        surfaced in :class:`PeriodEngineOutput`.
        """
        discount = discount or DiscountSpec(kind="scalar", rate=self.cfg.risk_free_rate)
        # Normalise rating once; the calculator does this too but we want a
        # stable canonical value when echoing back in engine_meta.
        deal.rating = normalize_rating(deal.rating)

        fixing_status_by_index = self._resolve_fixings(
            schedule, curves=curves, valuation_date=valuation_date,
        )

        paydowns = schedule.principal_paydowns()
        cumulative_t = 0.0
        per_period: List[PeriodOutput] = []
        for i, period in enumerate(schedule.periods):
            t_end = cumulative_t + period.dt_years
            row = self._compute_period(
                deal,
                period,
                discount=discount,
                t_end=t_end,
                principal_repayment=paydowns[i],
                fixing_status=fixing_status_by_index.get(period.index),
            )
            per_period.append(row)
            cumulative_t = t_end

        aggregates = self._aggregates(per_period)
        discount_meta = {
            "curve_status": discount.curve_status(),
            "rate_used": float(discount.rate),
            "day_count": discount.day_count,
        }
        engine_meta = {
            "engine_version": "period_engine/0.1",
            "regime": self.cfg.regime,
            "n_periods": len(per_period),
            "total_years": schedule.total_years,
            "rating": deal.rating,
            "product_type": deal.product_type,
        }
        engine_meta.update(_fixing_meta(per_period))
        return PeriodEngineOutput(
            per_period=per_period,
            aggregates=aggregates,
            discount_meta=discount_meta,
            engine_meta=engine_meta,
        )

    def run_from_input(self, inp: PeriodEngineInput) -> PeriodEngineOutput:
        """Variant that takes a :class:`PeriodEngineInput` bundle."""
        engine = self
        if inp.engine_config is not None and inp.engine_config is not self.cfg:
            engine = PeriodEngine(repository=self.repo, config=inp.engine_config)
        return engine.run(
            inp.deal, inp.schedule, inp.discount,
            curves=inp.curves, valuation_date=inp.valuation_date,
        )

    # ── Fixings (D-0003 cascade) ─────────────────────────────────

    def _resolve_fixings(
        self,
        schedule: Schedule,
        *,
        curves: Optional[CurveRepository],
        valuation_date: Optional[date],
    ) -> dict:
        """Attach curve fixings to floating periods. Returns per-period status.

        Returns a ``{period.index: status_str}`` mapping populated for
        every floating period the engine resolved (or that already came
        pre-fixed by the caller). Periods that needed a fixing but had
        no repo to consult are flagged ``scalar_fallback`` and their
        ``fixing_rate`` defaults to the engine's risk-free scalar.
        """
        status_by_index: dict = {}
        unresolved = [p for p in schedule.periods
                      if p.floating_index is not None and p.fixing_rate is None]

        if curves is not None and unresolved:
            results = schedule.attach_fixings(
                curves,
                valuation_date=valuation_date,
                fallback_rate=self.cfg.risk_free_rate,
            )
            # ``attach_fixings`` returns one result per resolved period
            # in period-index order over the unresolved set.
            for p, fixing in zip(unresolved, results):
                status_by_index[p.index] = fixing.status

        # Periods already carrying a ``fixing_rate`` get a ``fresh`` flag —
        # the caller supplied it directly, so we trust it.
        for p in schedule.periods:
            if p.floating_index is None:
                continue
            if p.index in status_by_index:
                continue
            if p.fixing_rate is not None:
                status_by_index[p.index] = STATUS_FRESH
            else:
                # No repo and no caller-supplied fixing: degrade gracefully
                # to the scalar fallback so the engine never crashes on a
                # missing curve (D-0003 §5).
                p.fixing_rate = float(self.cfg.risk_free_rate)
                status_by_index[p.index] = STATUS_SCALAR_FALLBACK

        return status_by_index

    # ── Per-period worker ─────────────────────────────────────────

    def _compute_period(
        self,
        deal: RAROCInput,
        period: Period,
        *,
        discount: DiscountSpec,
        t_end: float,
        principal_repayment: float,
        fixing_status: Optional[str] = None,
    ) -> PeriodOutput:
        """Single period: synthetic RAROCInput → calculator → dt-scaled fields."""
        per_inp = self._period_input(deal, period)
        base: RAROCOutput = self.calc.calculate(per_inp)

        dt = period.dt_years

        # Revenue: dt-scale interest + commit; period-allocated fees aren't
        # dt-scaled (term-sheet convention — fees are bookings, not accruals).
        interest = (per_inp.spread or 0.0) * (per_inp.average_drawn or 0.0)
        commit_pf = (per_inp.commitment_fee or 0.0) * (
            (per_inp.average_volume or 0.0) - (per_inp.average_drawn or 0.0)
        )
        fees = per_inp.flat_fee + per_inp.participation_fee + per_inp.upfront_fee
        revenue = (interest + commit_pf) * dt + fees

        # Cost: preserve the calculator's resolved cost-income ratio. For
        # dt=1.0 this collapses to ``base.cost`` (cost_ratio = base.cost /
        # base.revenue → revenue × ratio == base.cost). For dt!=1.0 the
        # rescaling carries through cleanly.
        if base.revenue > 0:
            cost = revenue * (base.cost / base.revenue)
        else:
            cost = 0.0

        funding_cost = self.cfg.funding_cost_bp * base.exposure * dt
        el = base.exposure * base.pd_basel2 * dt
        fpe_return = self.cfg.risk_free_rate * base.fpe * dt
        gross_margin = revenue - cost - funding_cost
        net_margin = gross_margin - el + fpe_return

        if base.fpe > 0:
            tax = self.cfg.bank_tax_rate
            raroc = (1.0 - tax) * (
                (revenue - cost - funding_cost - el) / base.fpe
                + self.cfg.risk_free_rate
            )
        else:
            raroc = 0.0

        # Risk decomposition for transparency: calculator returns the
        # post-floor K only. Recompute the IRB and SA-floor branches so
        # callers can see which one bound.
        lgd = self._lgd_for_deal(deal)
        z = (
            math.sqrt(1.0 / (1.0 - base.correlation)) * norm.ppf(base.pd)
            + math.sqrt(base.correlation / (1.0 - base.correlation)) * norm.ppf(0.999)
        )
        K_irb = (
            lgd
            * (norm.cdf(z) - base.pd)
            * (1.0 + (period.remaining_maturity_years - 2.5) * base.maturity_adj_b)
            / (1.0 - 1.5 * base.maturity_adj_b)
        )
        if self.cfg.regime == "basel3":
            sa_rw = self.calc._standardised_risk_weight(base.pd)
            K_floor = self.cfg.output_floor_pct * sa_rw / 12.5
        else:
            sa_rw = 0.0
            K_floor = 0.0

        # Discount layer (spec §5: DF = (1 + r) ^ (-t_end))
        rate = discount.rate_at(t_end, period_end=period.end)
        df = (1.0 + rate) ** (-t_end)

        all_in_rate = (
            (period.fixing_rate or 0.0) + (deal.spread or 0.0)
            if period.floating_index is not None and period.fixing_rate is not None
            else None
        )

        return PeriodOutput(
            index=period.index,
            start=period.start,
            end=period.end,
            dt_years=dt,
            commitment=period.commitment,
            avg_drawn=period.avg_drawn,
            remaining_maturity_years=period.remaining_maturity_years,
            revenue=revenue,
            cost=cost,
            funding_cost=funding_cost,
            exposure=base.exposure,
            pd=base.pd,
            pd_basel2=base.pd_basel2,
            lgd=lgd,
            correlation=base.correlation,
            maturity_adj_b=base.maturity_adj_b,
            z=z,
            K_irb=K_irb,
            sa_rw=sa_rw,
            K_floor=K_floor,
            K=base.risk_weight,
            fpe=base.fpe,
            el=el,
            gross_margin=gross_margin,
            fpe_return=fpe_return,
            net_margin=net_margin,
            raroc=raroc,
            principal_repayment=principal_repayment,
            t_end_years=t_end,
            df=df,
            revenue_pv=revenue * df,
            net_margin_pv=net_margin * df,
            drawn_pv=period.avg_drawn * dt * df,
            floating_index=period.floating_index,
            fixing_rate=period.fixing_rate,
            all_in_rate=all_in_rate,
            curve_status=fixing_status,
        )

    def _period_input(self, deal: RAROCInput, period: Period) -> RAROCInput:
        """Synthetic single-period :class:`RAROCInput` for this period.

        Carries the period's volumes (commitment / drawn) and residual
        maturity in months (the existing calculator uses months
        internally); copies deal-level static fields (rating, GRR,
        spread, commit fee, confirmed, product type) verbatim.
        """
        maturity_months = period.remaining_maturity_years * 12.0
        return RAROCInput(
            product_type=deal.product_type,
            average_volume=period.commitment,
            average_drawn=period.avg_drawn,
            initial_volume=deal.initial_volume or period.commitment,
            initial_drawn=deal.initial_drawn or period.avg_drawn,
            initial_maturity=maturity_months,
            residual_maturity=maturity_months,
            spread=deal.spread or 0.0,
            commitment_fee=deal.commitment_fee or 0.0,
            flat_fee=period.flat_fee,
            participation_fee=period.participation_fee,
            upfront_fee=period.upfront_fee,
            user_cost=None,
            collateral=deal.collateral,
            collateral_face_value=deal.collateral_face_value,
            collateral_stress_value=deal.collateral_stress_value,
            global_grr=deal.global_grr,
            confirmed=deal.confirmed,
            rating=deal.rating,
            exchange_rate=deal.exchange_rate,
        )

    def _lgd_for_deal(self, deal: RAROCInput) -> float:
        """Match the calculator's LGD-floor logic (calculator._risk_weight)."""
        lgd = 1.0 - deal.global_grr
        if self.cfg.regime == "basel3":
            coll_type = "none" if deal.global_grr == 0 else self.cfg.default_collateral_type
            lgd = max(lgd, self.cfg.get_lgd_floor(coll_type))
        return lgd

    # ── Aggregates (spec §7) ──────────────────────────────────────

    @staticmethod
    def _aggregates(rows: Sequence[PeriodOutput]) -> dict:
        """Thin wrapper over :func:`aggregate.aggregate_periods`.

        Task 1.4 promoted the §7 aggregates into a dedicated module so
        downstream callers (the wallet view, the Term-Sheet Doctor
        re-pricing flow, future portfolio aggregation) can reuse them
        without going through the period engine. The dict layout is
        preserved so existing keys keep working.
        """
        return aggregate_periods(rows).to_dict()


def _fixing_meta(rows: Sequence[PeriodOutput]) -> dict:
    """Roll up per-period ``curve_status`` into facility-level meta.

    ``curve_status`` is the worst (numerically highest priority) tier
    seen across rows. ``fixing_breakdown`` counts each status — drives
    the App's per-facility audit table. Returns an empty dict when no
    row carries a floating fixing, so fixed-rate facilities don't see
    spurious curve_status keys in engine_meta.
    """
    statuses = [r.curve_status for r in rows if r.curve_status is not None]
    if not statuses:
        return {}
    rolled = max(statuses, key=lambda s: STATUS_PRIORITY.get(s, 99))
    breakdown: dict = {}
    for s in statuses:
        breakdown[s] = breakdown.get(s, 0) + 1
    indices_seen = {r.floating_index for r in rows if r.floating_index}
    return {
        "curve_status": rolled,
        "fixing_breakdown": breakdown,
        "floating_indices": sorted(i for i in indices_seen if i is not None),
    }


__all__ = [
    "DiscountSpec",
    "PeriodOutput",
    "PeriodEngineInput",
    "PeriodEngineOutput",
    "PeriodEngine",
]
