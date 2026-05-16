"""User-specified forward-curve shocks for what-if scenario simulation.

Task 3.1's :class:`raroc_engine.scenarios.RatesShiftMod` only does a
**parallel** level shift. Real treasury what-ifs are richer:

* *Parallel* — the whole curve moves by ±N bp.
* *Steepening* — short end down, long end up (or vice versa).
* *Flattening* — converse; short end up, long end down (mirror).
* *Curvature (butterfly)* — belly moves vs. wings.
* *Cut path* — a programme of cumulative cuts at calendar anchors
  (the natural model behind "worst case if rates fall 200 bp in the
  next 18 months").

This module ships:

* :class:`ForwardCurveShock` — abstract; subclasses implement
  ``shock_bp(t_years)`` returning a basis-point shift at that maturity.
* :class:`ParallelShock`, :class:`SteepeningShock`, :class:`FlatteningShock`,
  :class:`CurvatureShock`, :class:`CutPathShock` — the five primitives.
* :class:`CompositeShock` + :func:`compose_shocks` — pointwise sum of
  arbitrary shock components (with ``+`` operator support).
* :class:`CurveShockMod` — a :class:`raroc_engine.scenarios.ScenarioMod`
  that re-prices the per-period discount layer and pre-pinned floating
  fixings under the user's shock. Promotes the base
  :class:`DiscountSpec` to ``kind="schedule"`` with one shocked point
  per period boundary.
* :func:`simulate_curve_distribution` — fan-out helper: runs base + N
  shocks through :class:`raroc_engine.scenarios.ScenarioRunner` and
  packages the NPV distribution.

Spec: PLAN Task 4.1. Reuses :mod:`raroc_engine.scenarios` and
:mod:`raroc_engine.curves`. Acceptance criteria:
parallel ±100 bp on the Q1.1 5y RCF fixture produces directionally
correct NPV deltas; composed shocks compose correctly; regression test
pins outputs to seeded inputs.

Conventions
-----------

``t_years`` is the year-fraction *from the schedule's valuation date*
(i.e. the start of period 1 of the *original* base schedule). When
mods chain via the runner the global timeline is preserved across
segments, so a steepening shock that pivots at year 5 still pivots at
the global year 5 even when the scenario also refinances at year 2.

Shocks return basis points; the engine consumes decimals. Helpers on
the base class translate between the two so subclasses only have to
implement ``shock_bp``.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field, replace
from typing import Iterable, List, Optional, Sequence, Tuple

from .aggregate import FacilityAggregates
from .config import EngineConfig
from .models import RAROCInput
from .period_engine import DiscountSpec
from .repository import Repository
from .schedule import Period, Schedule
from .scenarios import (
    Scenario,
    ScenarioComparison,
    ScenarioContext,
    ScenarioMod,
    ScenarioRun,
    ScenarioRunner,
    ScenarioSegment,
)


# ── Shock primitives ────────────────────────────────────────────────


@dataclass(frozen=True)
class ForwardCurveShock:
    """Abstract base: maps maturity (in years) to a shift in basis points.

    Subclasses override :meth:`shock_bp`. Composition is supported via
    ``+`` (returns a :class:`CompositeShock`) and unary ``-`` (returns
    a :class:`ScaledShock` with scalar ``-1.0``). All subclasses are
    frozen dataclasses so the same shock can be reused across many
    scenarios without state leakage.
    """

    def shock_bp(self, t_years: float) -> float:  # pragma: no cover
        raise NotImplementedError

    def shock_decimal(self, t_years: float) -> float:
        """Convenience: shock in decimal units (``bp / 10_000``)."""
        return self.shock_bp(float(t_years)) / 10_000.0

    def describe(self) -> str:
        """One-line human-readable label for audit/comparison tables."""
        return self.__class__.__name__

    def __add__(self, other: "ForwardCurveShock") -> "ForwardCurveShock":
        if not isinstance(other, ForwardCurveShock):
            return NotImplemented
        return compose_shocks(self, other)

    def __neg__(self) -> "ForwardCurveShock":
        return ScaledShock(base=self, scalar=-1.0)

    def __mul__(self, scalar: float) -> "ForwardCurveShock":
        return ScaledShock(base=self, scalar=float(scalar))

    __rmul__ = __mul__


@dataclass(frozen=True)
class ParallelShock(ForwardCurveShock):
    """Flat level shift: every maturity moves by ``shift_bps``.

    ``ParallelShock(100)`` lifts the whole curve by +100 bp; pass a
    negative value for a downward parallel shift.
    """

    shift_bps: float

    def shock_bp(self, t_years: float) -> float:
        return float(self.shift_bps)

    def describe(self) -> str:
        sign = "+" if self.shift_bps >= 0 else ""
        return f"parallel {sign}{self.shift_bps:g}bp"


@dataclass(frozen=True)
class SteepeningShock(ForwardCurveShock):
    """Linear ramp from short end to long end of the curve.

    ``shock_bp(t)`` interpolates between ``short_shift_bps`` at
    ``t=0`` and ``long_shift_bps`` at ``t=long_anchor_years`` (default
    10y). Outside [0, long_anchor_years] the value clamps to the
    nearest endpoint — no extrapolation. A steepening has
    ``long_shift_bps > short_shift_bps`` (long end rises faster);
    a flattening has the inequality reversed.

    For the more common semantic of "twist around a pivot tenor"
    callers can split it into two SteepeningShocks combined with
    :func:`compose_shocks`.
    """

    short_shift_bps: float
    long_shift_bps: float
    long_anchor_years: float = 10.0

    def shock_bp(self, t_years: float) -> float:
        if self.long_anchor_years <= 0:
            return float(self.long_shift_bps)
        t = max(0.0, min(float(t_years), float(self.long_anchor_years)))
        w = t / float(self.long_anchor_years)
        return float(self.short_shift_bps) + w * (
            float(self.long_shift_bps) - float(self.short_shift_bps)
        )

    def describe(self) -> str:
        return (
            f"steepening short {self.short_shift_bps:g}bp / "
            f"long {self.long_shift_bps:g}bp at {self.long_anchor_years:g}y"
        )


@dataclass(frozen=True)
class FlatteningShock(ForwardCurveShock):
    """Linear ramp; semantically a steepening with the sign convention flipped.

    Mathematically identical to :class:`SteepeningShock`; the separate
    class exists so audit tables can label the user's intent clearly
    (a +50 short / -50 long shift reads as a flattener but is a
    steepening if you squint at the numbers). Subclass overrides only
    :meth:`describe`.
    """

    short_shift_bps: float
    long_shift_bps: float
    long_anchor_years: float = 10.0

    def shock_bp(self, t_years: float) -> float:
        if self.long_anchor_years <= 0:
            return float(self.long_shift_bps)
        t = max(0.0, min(float(t_years), float(self.long_anchor_years)))
        w = t / float(self.long_anchor_years)
        return float(self.short_shift_bps) + w * (
            float(self.long_shift_bps) - float(self.short_shift_bps)
        )

    def describe(self) -> str:
        return (
            f"flattening short {self.short_shift_bps:g}bp / "
            f"long {self.long_shift_bps:g}bp at {self.long_anchor_years:g}y"
        )


@dataclass(frozen=True)
class CurvatureShock(ForwardCurveShock):
    """Triangular bump centred at ``peak_years``, zero at the edges.

    The "butterfly" twist a treasury watches for ahead of a central
    bank pivot. ``shock_bp(t)`` is a tent function peaking at
    ``peak_shift_bps`` when ``t == peak_years`` and falling linearly
    to zero at ``peak_years ± half_width_years``. Outside the window
    the shock is zero.
    """

    peak_shift_bps: float
    peak_years: float
    half_width_years: float

    def shock_bp(self, t_years: float) -> float:
        d = abs(float(t_years) - float(self.peak_years))
        if d >= float(self.half_width_years) or self.half_width_years <= 0:
            return 0.0
        return float(self.peak_shift_bps) * (
            1.0 - d / float(self.half_width_years)
        )

    def describe(self) -> str:
        return (
            f"curvature {self.peak_shift_bps:g}bp at {self.peak_years:g}y "
            f"(±{self.half_width_years:g}y)"
        )


@dataclass(frozen=True)
class CutPathShock(ForwardCurveShock):
    """Step-function shock describing a cumulative cut/hike programme.

    ``cuts`` is a tuple of ``(t_years, cumulative_shift_bps)`` pairs.
    The shock is the **cumulative** shift active at maturity ``t`` —
    so ``[(0.5, -25), (1.0, -75), (1.5, -200)]`` reads as "no shock
    before 6 months, -25 bp from 6 months, -75 bp from 1 year, -200
    bp from 18 months onward". Models forward-rate expectations for
    the canonical Task 4.1 question — "what is the worst case if
    rates fall 200 bp in the next 18 months?".

    Anchors before the first ``t_years`` evaluate to zero (no shock).
    Anchors at or after the last ``t_years`` evaluate to the last
    cumulative shift (no further changes). Pairs may be supplied in
    any order; they are sorted internally.
    """

    cuts: Tuple[Tuple[float, float], ...] = field(default_factory=tuple)

    def shock_bp(self, t_years: float) -> float:
        cum = 0.0
        t = float(t_years)
        sorted_cuts = sorted(self.cuts, key=lambda x: float(x[0]))
        for t_cut, cum_bps in sorted_cuts:
            if t >= float(t_cut):
                cum = float(cum_bps)
            else:
                break
        return cum

    def describe(self) -> str:
        bits = ", ".join(
            f"{float(t):g}y→{float(b):g}bp" for t, b in sorted(self.cuts)
        )
        return f"cut-path [{bits}]"


@dataclass(frozen=True)
class CompositeShock(ForwardCurveShock):
    """Pointwise sum of arbitrary :class:`ForwardCurveShock` components.

    Use :func:`compose_shocks` or the ``+`` operator to build one.
    Components are flattened (no nested composites) so a chain of
    ``a + b + c`` reads as a single 3-component composite.
    """

    components: Tuple[ForwardCurveShock, ...] = field(default_factory=tuple)

    def shock_bp(self, t_years: float) -> float:
        return sum(c.shock_bp(t_years) for c in self.components)

    def describe(self) -> str:
        if not self.components:
            return "composite ()"
        return " + ".join(c.describe() for c in self.components)


@dataclass(frozen=True)
class ScaledShock(ForwardCurveShock):
    """Wraps a base shock and multiplies its output by ``scalar``.

    ``-shock`` and ``2 * shock`` both produce a ScaledShock under the
    hood. Useful for sensitivity studies that want a family of shocks
    scaled from a single template.
    """

    base: ForwardCurveShock
    scalar: float

    def shock_bp(self, t_years: float) -> float:
        return self.base.shock_bp(t_years) * float(self.scalar)

    def describe(self) -> str:
        return f"{self.scalar:g} × ({self.base.describe()})"


def compose_shocks(*shocks: ForwardCurveShock) -> ForwardCurveShock:
    """Combine N shocks into a single :class:`CompositeShock`.

    Flattens any composite inputs so the result is a single-level
    sum. ``compose_shocks()`` (no args) returns a no-op
    ``ParallelShock(0.0)`` so callers can use it as a default in
    expression chains.
    """
    flat: List[ForwardCurveShock] = []
    for s in shocks:
        if isinstance(s, CompositeShock):
            flat.extend(s.components)
        else:
            flat.append(s)
    if not flat:
        return ParallelShock(0.0)
    if len(flat) == 1:
        return flat[0]
    return CompositeShock(components=tuple(flat))


# ── Scenario mod ────────────────────────────────────────────────────


@dataclass
class CurveShockMod(ScenarioMod):
    """Apply a :class:`ForwardCurveShock` to discount + floating fixings.

    Three layers can shift under the shock:

    * **Discount** (always): every period's discount rate at
      ``t_end_years`` shifts by ``shock.shock_decimal(t_end_years)``.
      The base :class:`DiscountSpec` is promoted to ``kind="schedule"``
      with one point per period boundary (date-keyed) so the period
      engine's date-driven lookup picks up the shocked rate.
    * **Floating fixings** (``affect_floating_fixings=True``, default):
      each period whose ``floating_index`` is set AND ``fixing_rate``
      is already pinned has its fixing shifted by
      ``shock.shock_decimal(t_period_start)`` — i.e. evaluated at the
      *start* of the period since that's when the fixing would have
      been set in real time.
    * **Engine risk-free rate** (``affect_engine_rate=False``, default
      OFF): when True, shifts ``EngineConfig.risk_free_rate`` by
      ``shock.shock_decimal(engine_rate_anchor_years)`` (default 0y).
      Off by default because curve shocks describe rate scenarios,
      whereas the engine ``rfr`` term is a hurdle / opportunity-cost
      knob that conventionally does not move with rate scenarios.
      Flip on for full RAROC sensitivity to the shock.

    Compose with :class:`raroc_engine.scenarios.RatesShiftMod` (or
    another :class:`CurveShockMod` with a different shock) to stack
    effects — each mod sees the prior context and adds to it.
    """

    shock: ForwardCurveShock = field(default_factory=lambda: ParallelShock(0.0))
    affect_engine_rate: bool = False
    engine_rate_anchor_years: float = 0.0
    affect_floating_fixings: bool = True

    def apply(self, ctx: ScenarioContext) -> ScenarioContext:
        new_segments: List[ScenarioSegment] = []
        cum_t = 0.0  # global time-offset of this segment's start
        for seg in ctx.segments:
            new_segments.append(
                self._shock_segment(seg, cum_t=cum_t)
            )
            cum_t += seg.schedule.total_years
        return ScenarioContext(segments=new_segments)

    def _shock_segment(
        self,
        seg: ScenarioSegment,
        *,
        cum_t: float,
    ) -> ScenarioSegment:
        """Build one shocked segment from one base segment."""
        # 1. Shocked DiscountSpec — date-keyed schedule with one point per period end.
        shocked_points: List[Tuple] = []
        seg_local_t = 0.0
        for p in seg.schedule.periods:
            seg_local_t += p.dt_years
            global_t_end = cum_t + seg_local_t
            base_rate_here = seg.discount.rate_at(seg_local_t, period_end=p.end)
            shocked_rate = float(base_rate_here) + self.shock.shock_decimal(global_t_end)
            shocked_points.append((p.end, shocked_rate))
        new_discount = DiscountSpec(
            kind="schedule",
            rate=float(seg.discount.rate),
            name=seg.discount.name,
            points=shocked_points,
            day_count=seg.discount.day_count,
        )

        # 2. Floating fixings — shift pre-pinned fixings by shock at period start.
        if self.affect_floating_fixings:
            new_periods: List[Period] = []
            seg_local_t = 0.0
            for p in seg.schedule.periods:
                global_t_start = cum_t + seg_local_t
                seg_local_t += p.dt_years
                if p.floating_index is not None and p.fixing_rate is not None:
                    shock_dec = self.shock.shock_decimal(global_t_start)
                    new_periods.append(
                        replace(p, fixing_rate=float(p.fixing_rate) + shock_dec)
                    )
                else:
                    new_periods.append(replace(p))
            new_schedule = Schedule(
                periods=new_periods,
                day_count=seg.schedule.day_count,
                type_=seg.schedule.type_,
            )
        else:
            new_schedule = Schedule(
                periods=[replace(p) for p in seg.schedule.periods],
                day_count=seg.schedule.day_count,
                type_=seg.schedule.type_,
            )

        # 3. Engine risk-free rate — only when explicitly opted-in.
        if self.affect_engine_rate:
            shocked_cfg = copy.deepcopy(seg.config)
            shocked_cfg.risk_free_rate = float(seg.config.risk_free_rate) + (
                self.shock.shock_decimal(self.engine_rate_anchor_years)
            )
        else:
            shocked_cfg = copy.deepcopy(seg.config)

        return ScenarioSegment(
            deal=copy.deepcopy(seg.deal),
            schedule=new_schedule,
            discount=new_discount,
            config=shocked_cfg,
            t_offset_years=seg.t_offset_years,
        )

    def describe(self) -> str:
        bits = [f"curve-shock: {self.shock.describe()}"]
        if self.affect_engine_rate:
            bits.append(f"engine rfr@{self.engine_rate_anchor_years:g}y")
        if not self.affect_floating_fixings:
            bits.append("fixings-fixed")
        return ", ".join(bits)


# ── Distribution helper ─────────────────────────────────────────────


@dataclass(frozen=True)
class ScenarioDistribution:
    """NPV distribution across a set of curve-shock scenarios.

    Bundles the base run with one :class:`ScenarioRun` per shock and
    provides helpers to extract worst-case / best-case / percentile
    summaries — the "distribution of NPV" the PLAN Task 4.1 brief
    asks for.

    ``runs`` is in input order so the caller can map results back to
    the labels they passed in. The percentile / min / max helpers
    operate on ``npv_borrower_cost`` by default; pass ``metric=``
    keyword to switch metrics.
    """

    base: ScenarioRun
    runs: List[ScenarioRun]
    labels: List[str]
    shocks: List[ForwardCurveShock]

    @property
    def all_runs(self) -> List[ScenarioRun]:
        return [self.base] + list(self.runs)

    def values(self, metric: str = "npv_borrower_cost") -> List[float]:
        """Extract the named metric across every shock run (excludes base)."""
        return [float(_metric_of(r, metric)) for r in self.runs]

    def values_with_base(self, metric: str = "npv_borrower_cost") -> List[float]:
        """Same as :meth:`values` but includes the base run first."""
        return [float(_metric_of(r, metric)) for r in self.all_runs]

    def min(self, metric: str = "npv_borrower_cost") -> float:
        v = self.values(metric)
        return min(v) if v else 0.0

    def max(self, metric: str = "npv_borrower_cost") -> float:
        v = self.values(metric)
        return max(v) if v else 0.0

    def percentile(
        self,
        q: float,
        metric: str = "npv_borrower_cost",
    ) -> float:
        """Linear-interpolation percentile (q in [0, 100]) over scenario runs.

        Matches NumPy's ``np.percentile(..., method="linear")``
        without the NumPy dependency. Excludes the base run.
        """
        vals = sorted(self.values(metric))
        if not vals:
            return 0.0
        if len(vals) == 1:
            return vals[0]
        q = max(0.0, min(100.0, float(q)))
        k = (len(vals) - 1) * q / 100.0
        lo = int(k)
        hi = min(lo + 1, len(vals) - 1)
        w = k - lo
        return vals[lo] * (1.0 - w) + vals[hi] * w

    def worst_case(
        self,
        metric: str = "npv_borrower_cost",
        *,
        side: str = "high",
    ) -> Tuple[str, float]:
        """Return the (label, value) at the worst-case end of the distribution.

        ``side="high"`` returns the maximum (e.g. worst-case borrower
        cost is the highest NPV the borrower pays); ``side="low"``
        returns the minimum (e.g. worst-case bank margin is the
        lowest net margin the bank earns). Pairs the run by index so
        the label is the user's original label, not a shock describe.
        """
        if not self.runs:
            return ("", 0.0)
        idxs = list(range(len(self.runs)))
        vals = self.values(metric)
        if side == "high":
            i = max(idxs, key=lambda i: vals[i])
        elif side == "low":
            i = min(idxs, key=lambda i: vals[i])
        else:
            raise ValueError(f"worst_case side must be 'high' or 'low', got {side!r}")
        return (self.labels[i], vals[i])

    def best_case(
        self,
        metric: str = "npv_borrower_cost",
        *,
        side: str = "low",
    ) -> Tuple[str, float]:
        """Inverse of :meth:`worst_case` — by default lower NPV cost is better."""
        return self.worst_case(metric, side=side)

    def to_table(self) -> dict:
        """Dict view shaped for the App's UI / API.

        Format mirrors :meth:`ScenarioComparison.to_table` so consumers
        can render shock fan-outs and ad-hoc scenarios in the same
        widget.
        """
        rows = [_run_to_row(self.base, label="base", is_base=True, shock=None)]
        for run, label, shock in zip(self.runs, self.labels, self.shocks):
            rows.append(_run_to_row(run, label=label, is_base=False, shock=shock))
        return {
            "base_name": self.base.name,
            "rows": rows,
            "summary": {
                "npv_borrower_cost_min": self.min("npv_borrower_cost"),
                "npv_borrower_cost_max": self.max("npv_borrower_cost"),
                "npv_borrower_cost_p25": self.percentile(25.0, "npv_borrower_cost"),
                "npv_borrower_cost_p50": self.percentile(50.0, "npv_borrower_cost"),
                "npv_borrower_cost_p75": self.percentile(75.0, "npv_borrower_cost"),
                "npv_bank_net_margin_min": self.min("npv_bank_net_margin"),
                "npv_bank_net_margin_max": self.max("npv_bank_net_margin"),
            },
        }


def simulate_curve_distribution(
    deal: RAROCInput,
    schedule: Schedule,
    shocks: Sequence[Tuple[str, ForwardCurveShock]],
    *,
    discount: Optional[DiscountSpec] = None,
    runner: Optional[ScenarioRunner] = None,
    config: Optional[EngineConfig] = None,
    repository: Optional[Repository] = None,
    affect_engine_rate: bool = False,
    affect_floating_fixings: bool = True,
) -> ScenarioDistribution:
    """Run base + one scenario per shock; return the distribution.

    Each ``(label, shock)`` pair becomes a :class:`Scenario` wrapping
    a single :class:`CurveShockMod`. The whole batch runs through
    :class:`ScenarioRunner.compare` so the base is computed exactly
    once and re-used across every shock.

    Args:
        deal / schedule / discount: Base inputs (same shape as
            :meth:`ScenarioRunner.compare`).
        shocks: Sequence of ``(label, ForwardCurveShock)`` pairs. The
            label is what shows up in :class:`ScenarioDistribution`
            outputs; it is also used as the underlying
            :class:`Scenario` name.
        runner / config / repository: Optional overrides. When
            ``runner`` is ``None`` a fresh one is built from
            ``config`` and ``repository``.
        affect_engine_rate / affect_floating_fixings: Forwarded to
            every :class:`CurveShockMod` built in the batch.
    """
    runner = runner or ScenarioRunner(repository=repository, config=config)
    scenarios: List[Scenario] = []
    labels: List[str] = []
    shock_list: List[ForwardCurveShock] = []
    for label, shock in shocks:
        scenarios.append(Scenario(
            name=label,
            mods=[CurveShockMod(
                shock=shock,
                affect_engine_rate=affect_engine_rate,
                affect_floating_fixings=affect_floating_fixings,
            )],
            description=shock.describe(),
        ))
        labels.append(str(label))
        shock_list.append(shock)
    comp: ScenarioComparison = runner.compare(deal, schedule, scenarios, discount)
    return ScenarioDistribution(
        base=comp.base,
        runs=list(comp.scenarios),
        labels=labels,
        shocks=shock_list,
    )


# ── Internals ──────────────────────────────────────────────────────


_NUMERIC_METRICS = {
    "npv_borrower_cost",
    "npv_bank_net_margin",
    "npv_bank_costs",
    "npv_drawn_balance",
    "effective_spread_bp",
    "capital_weighted_raroc",
    "avg_raroc",
    "total_revenue_undisc",
    "total_el_undisc",
}


def _metric_of(run: ScenarioRun, metric: str) -> float:
    if metric not in _NUMERIC_METRICS:
        raise ValueError(
            f"Unknown metric {metric!r}. Known: {sorted(_NUMERIC_METRICS)}"
        )
    agg: FacilityAggregates = run.aggregates
    return float(getattr(agg, metric))


def _run_to_row(
    run: ScenarioRun,
    *,
    label: str,
    is_base: bool,
    shock: Optional[ForwardCurveShock],
) -> dict:
    return {
        "label": label,
        "name": run.name,
        "is_base": is_base,
        "shock": shock.describe() if shock is not None else None,
        "npv_borrower_cost": run.aggregates.npv_borrower_cost,
        "npv_bank_net_margin": run.aggregates.npv_bank_net_margin,
        "npv_drawn_balance": run.aggregates.npv_drawn_balance,
        "effective_spread_bp": run.aggregates.effective_spread_bp,
        "capital_weighted_raroc": run.aggregates.capital_weighted_raroc,
        "avg_raroc": run.aggregates.avg_raroc,
        "n_periods": run.aggregates.n_periods,
        "total_years": run.aggregates.total_years,
    }


def shock_to_curve_points(
    shock: ForwardCurveShock,
    tenors_years: Iterable[float],
) -> List[Tuple[float, float]]:
    """Sample ``shock`` at the given maturities; return ``(t_years, bp)`` rows.

    Inspection helper for the App's UI / audit log — shows the curve
    deformation the user picked at a list of pillar tenors so they
    can sanity-check before running the simulation.
    """
    out: List[Tuple[float, float]] = []
    for t in tenors_years:
        out.append((float(t), float(shock.shock_bp(float(t)))))
    return out


__all__ = [
    "ForwardCurveShock",
    "ParallelShock",
    "SteepeningShock",
    "FlatteningShock",
    "CurvatureShock",
    "CutPathShock",
    "CompositeShock",
    "ScaledShock",
    "compose_shocks",
    "CurveShockMod",
    "ScenarioDistribution",
    "simulate_curve_distribution",
    "shock_to_curve_points",
]
