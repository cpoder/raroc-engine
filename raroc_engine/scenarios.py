"""Scenario-comparison module for the multi-period RAROC engine.

Takes a base ``(deal, schedule, discount, engine_config)`` and a list of
:class:`ScenarioMod` objects (refinance at year T, rates shift ±N bp,
drawdown pattern change, bank-profile swap, structure swap). Runs the
base + each scenario through :class:`PeriodEngine` and surfaces a
side-by-side view: per-period RAROC, NPV borrower cost / bank net
margin, effective spread — plus deltas vs the base.

Design
------

A scenario is a list of mods applied **in order** to a *base context* —
a typed container holding one or more :class:`ScenarioSegment` rows.
Most mods produce a single-segment context; :class:`RefinanceMod` is
the exception, splitting the base schedule at year T into two segments
(pre-refi keeps the original deal terms; post-refi gets the new
spread / commit fee / refi upfront fee).

Each segment runs through its own :meth:`PeriodEngine.run` call. The
per-period rows are then *stitched* — each subsequent segment's
``t_end_years`` is offset by the cumulative time of preceding segments,
and discount factors are re-attached at the stitched origin via
:func:`raroc_engine.aggregate.attach_discount_factors` so NPVs
aggregate correctly under a single discount cascade.

The output :class:`ScenarioRun` is fully reproducible — same inputs
always produce the same per-period rows + aggregates. There is no RNG.

Spec: PLAN Task 3.1. Acceptance: three canonical scenarios (refi at
year 2, rates -100 bp, bank swap) produce the expected directional
changes against the Q1.1 RCF fixture (``tests/fixtures/period_rcf_5y.yaml``).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field, replace
from datetime import date
from typing import List, Optional, Sequence

from .aggregate import FacilityAggregates, aggregate_periods, attach_discount_factors
from .config import EngineConfig
from .curves import STATUS_PRIORITY, CurveRepository
from .models import RAROCInput
from .period_engine import (
    DiscountSpec,
    PeriodEngine,
    PeriodEngineOutput,
    PeriodOutput,
)
from .repository import Repository
from .schedule import Period, Schedule


# ── Segment + context ───────────────────────────────────────────────


@dataclass
class ScenarioSegment:
    """One time-contiguous slice of a scenario context (one engine run).

    A vanilla scenario has a single segment that mirrors the base
    inputs. :class:`RefinanceMod` splits the base into two segments at
    the refi year boundary; the second segment carries the new pricing
    on its ``deal`` copy and the refi upfront fee on the first period
    of its ``schedule``.

    ``t_offset_years`` is the cumulative time of preceding segments,
    used to re-anchor per-period ``t_end_years`` on the global timeline
    after each segment's engine run finishes.
    """

    deal: RAROCInput
    schedule: Schedule
    discount: DiscountSpec
    config: EngineConfig
    t_offset_years: float = 0.0


@dataclass
class ScenarioContext:
    """Mutable container of segments, threaded through mod application.

    Mods take a context, return a (typically new) context. The runner
    builds the initial single-segment context from ``(deal, schedule,
    discount, config)`` and walks the scenario's mods in order.
    """

    segments: List[ScenarioSegment]

    @property
    def total_years(self) -> float:
        return sum(s.schedule.total_years for s in self.segments)

    def replace_first(self, **overrides) -> "ScenarioContext":
        """Return a new context with the first segment's fields replaced."""
        if not self.segments:
            return self
        new_first = replace(self.segments[0], **overrides)
        return ScenarioContext(segments=[new_first] + list(self.segments[1:]))


# ── Scenario mods ────────────────────────────────────────────────────


@dataclass
class ScenarioMod:
    """Base class. Subclasses implement :meth:`apply`.

    Mods MUST be pure: they take a context and return a context without
    mutating any of the inputs in place. The runner deepcopies before
    applying so the base inputs survive a comparison call.
    """

    def apply(self, ctx: ScenarioContext) -> ScenarioContext:  # pragma: no cover
        raise NotImplementedError

    def describe(self) -> str:  # pragma: no cover
        return self.__class__.__name__


@dataclass
class RefinanceMod(ScenarioMod):
    """Refinance the facility at the start of year ``at_year``.

    Pre-refi (years 0 .. at_year): unchanged. Post-refi (year at_year ..
    end): new spread / commitment fee / upfront fee, optionally
    extended maturity. Splits the base segment in two at the period
    boundary corresponding to ``at_year`` (1-based).

    Args:
        at_year: 1-based year boundary. ``at_year=2`` means the new
            terms kick in at the start of period 3 (after years 1 and 2
            keep the original pricing). Must satisfy
            ``1 <= at_year < total_years``.
        new_spread: New all-in spread (decimal). ``None`` = unchanged.
        new_commitment_fee: New undrawn commitment fee. ``None`` = unchanged.
        new_upfront_fee: Refi fee charged on period 1 of the post-refi
            segment (default 0).
        new_maturity_years: Extend the post-refi tail to this many years
            beyond ``at_year``. ``None`` = keep the original maturity.
            Currently only annual schedules are supported (the Q1
            fixtures), so the value is rounded to int periods.
    """

    at_year: int = 1
    new_spread: Optional[float] = None
    new_commitment_fee: Optional[float] = None
    new_upfront_fee: float = 0.0
    new_maturity_years: Optional[int] = None

    def apply(self, ctx: ScenarioContext) -> ScenarioContext:
        if not ctx.segments:
            return ctx
        # Refi only operates on the first base segment in v0; chained
        # refis would need the same logic walking all segments.
        seg = ctx.segments[0]
        sched = seg.schedule
        if not sched.is_annual:
            raise ValueError(
                "RefinanceMod currently only supports annual schedules "
                "(every period dt_years==1.0)."
            )
        n = len(sched.periods)
        if not (1 <= self.at_year < n):
            raise ValueError(
                f"RefinanceMod.at_year={self.at_year} must be in [1, {n - 1}] "
                f"for a {n}-period schedule."
            )

        pre_periods = sched.periods[: self.at_year]
        post_periods = sched.periods[self.at_year :]

        # Optional maturity extension: append flat-tail periods at the
        # current commitment / drawn levels until we hit the target.
        if self.new_maturity_years is not None:
            target = int(self.new_maturity_years)
            current_post_len = len(post_periods)
            if target < 1:
                raise ValueError(
                    f"RefinanceMod.new_maturity_years={self.new_maturity_years} "
                    "must be >= 1."
                )
            if target < current_post_len:
                # Truncate (early payoff)
                post_periods = post_periods[:target]
            elif target > current_post_len:
                last = post_periods[-1]
                cursor_end = last.end
                for _ in range(target - current_post_len):
                    new_start = cursor_end
                    new_end = _add_year(new_start)
                    post_periods = list(post_periods) + [Period(
                        index=0,  # re-indexed below
                        start=new_start,
                        end=new_end,
                        dt_years=1.0,
                        commitment=last.commitment,
                        avg_drawn=last.avg_drawn,
                        remaining_maturity_years=1.0,  # filled below
                        upfront_fee=0.0,
                        flat_fee=0.0,
                        participation_fee=0.0,
                        floating_index=last.floating_index,
                        fixing_rate=None,
                    )]
                    cursor_end = new_end

        pre_segment = self._build_segment(seg, list(pre_periods), is_pre=True)
        post_segment = self._build_segment(
            seg, list(post_periods), is_pre=False,
            t_offset_years=seg.t_offset_years + sum(p.dt_years for p in pre_periods),
        )

        return ScenarioContext(
            segments=[pre_segment, post_segment] + list(ctx.segments[1:]),
        )

    def _build_segment(
        self,
        base: ScenarioSegment,
        periods: List[Period],
        *,
        is_pre: bool,
        t_offset_years: float = 0.0,
    ) -> ScenarioSegment:
        n = len(periods)
        rebuilt: List[Period] = []
        for i, p in enumerate(periods):
            new_idx = i + 1
            if is_pre:
                # Pre-refi periods belong to the ORIGINAL contract — their
                # residual contractual maturity (which drives the IRB
                # maturity adjustment) is whatever the base schedule had.
                # Only re-index; do NOT recompute remaining_maturity_years
                # from the pre-segment length, otherwise the bank's
                # capital usage for years 1-2 would look like a 2y
                # facility instead of the 5y facility it actually was.
                new_remaining = p.remaining_maturity_years
                new_upfront = p.upfront_fee
            else:
                # Post-refi is a NEW contract starting here — residual
                # maturity is the post-segment's length, decreasing by 1y
                # per period. Period 1 carries the refi fee; later
                # periods get a zero upfront.
                new_remaining = float(n - i)
                new_upfront = float(self.new_upfront_fee) if i == 0 else 0.0
            rebuilt.append(replace(
                p,
                index=new_idx,
                remaining_maturity_years=new_remaining,
                upfront_fee=new_upfront,
            ))
        new_sched = Schedule(
            periods=rebuilt,
            day_count=base.schedule.day_count,
            type_=base.schedule.type_,
        )
        if is_pre:
            return replace(base, schedule=new_sched)
        # Post-refi: clone the deal with new pricing.
        new_deal = replace(
            base.deal,
            spread=self.new_spread if self.new_spread is not None else base.deal.spread,
            commitment_fee=(
                self.new_commitment_fee
                if self.new_commitment_fee is not None
                else base.deal.commitment_fee
            ),
        )
        return ScenarioSegment(
            deal=new_deal,
            schedule=new_sched,
            discount=base.discount,
            config=base.config,
            t_offset_years=t_offset_years if t_offset_years else 0.0,
        )

    def describe(self) -> str:
        bits = [f"refi at year {self.at_year}"]
        if self.new_spread is not None:
            bits.append(f"spread→{self.new_spread * 10000:.0f}bp")
        if self.new_commitment_fee is not None:
            bits.append(f"commit→{self.new_commitment_fee * 10000:.0f}bp")
        if self.new_upfront_fee:
            bits.append(f"upfront={self.new_upfront_fee:,.0f}")
        if self.new_maturity_years is not None:
            bits.append(f"maturity→{self.new_maturity_years}y")
        return ", ".join(bits)


@dataclass
class RatesShiftMod(ScenarioMod):
    """Parallel-shift the risk-free / discount curve by ``shift_bps``.

    By default this affects three places consistently — the natural
    "the entire risk-free curve moved by N bp" interpretation:

    - **Discount rate**: shifted on every segment's :class:`DiscountSpec`
      (DFs go up when rates go down, NPVs go up).
    - **Engine config risk-free rate**: shifted on every segment's
      :class:`EngineConfig` (changes ``fpe_return`` and the RAROC
      formula's tax-adjusted ``rfr`` term).
    - **Floating-rate fixings**: any period whose ``floating_index`` is
      set and ``fixing_rate`` is already pinned has its fixing shifted.
      Unresolved floating periods are left to be re-fixed by the
      curves repository at run time (the cascade carries the shift
      implicitly when applied to the upstream data).

    Args:
        shift_bps: Shift in basis points (decimal × 10000). +50 = +50bp,
            -100 = -100bp.
        affect_engine_rate: When False, shift only the discount layer
            (useful to isolate the discount sensitivity from the RAROC
            formula's risk-free term).
        affect_floating_fixings: When False, leave per-period
            ``fixing_rate`` values untouched.
    """

    shift_bps: float = 0.0
    affect_engine_rate: bool = True
    affect_floating_fixings: bool = True

    def apply(self, ctx: ScenarioContext) -> ScenarioContext:
        shift = float(self.shift_bps) / 10000.0
        new_segments: List[ScenarioSegment] = []
        for seg in ctx.segments:
            new_discount = self._shift_discount(seg.discount, shift)
            new_config = (
                self._shift_config(seg.config, shift)
                if self.affect_engine_rate
                else seg.config
            )
            new_schedule = (
                self._shift_fixings(seg.schedule, shift)
                if self.affect_floating_fixings
                else seg.schedule
            )
            new_segments.append(replace(
                seg,
                deal=copy.deepcopy(seg.deal),
                schedule=new_schedule,
                discount=new_discount,
                config=new_config,
            ))
        return ScenarioContext(segments=new_segments)

    @staticmethod
    def _shift_discount(spec: DiscountSpec, shift: float) -> DiscountSpec:
        if spec.kind == "schedule" and spec.points:
            new_points = [(d, float(r) + shift) for (d, r) in spec.points]
            return DiscountSpec(
                kind="schedule",
                rate=spec.rate + shift,
                name=spec.name,
                points=new_points,
                day_count=spec.day_count,
            )
        return DiscountSpec(
            kind=spec.kind,
            rate=spec.rate + shift,
            name=spec.name,
            points=spec.points,
            day_count=spec.day_count,
        )

    @staticmethod
    def _shift_config(cfg: EngineConfig, shift: float) -> EngineConfig:
        new_cfg = copy.deepcopy(cfg)
        new_cfg.risk_free_rate = float(cfg.risk_free_rate) + shift
        return new_cfg

    @staticmethod
    def _shift_fixings(sched: Schedule, shift: float) -> Schedule:
        new_periods: List[Period] = []
        for p in sched.periods:
            if p.floating_index is not None and p.fixing_rate is not None:
                new_periods.append(replace(p, fixing_rate=float(p.fixing_rate) + shift))
            else:
                new_periods.append(replace(p))
        return Schedule(
            periods=new_periods,
            day_count=sched.day_count,
            type_=sched.type_,
        )

    def describe(self) -> str:
        sign = "+" if self.shift_bps >= 0 else ""
        return f"rates shift {sign}{self.shift_bps:g}bp"


@dataclass
class DrawdownPatternMod(ScenarioMod):
    """Replace the schedule's ``avg_drawn`` profile.

    Useful for "what if we draw less / draw later / hold a lower
    cleandown" what-if questions on a confirmed RCF. Commitment and
    period boundaries are preserved; only ``avg_drawn`` per period is
    replaced (and clamped to the period's commitment).

    The replacement is provided as a sequence of ``(avg_drawn, n_years)``
    tuples, mirroring :meth:`Schedule.bullet_rcf_with_cleandown` —
    e.g. ``[(50_000_000, 2), (35_000_000, 3)]`` for a 5y RCF with 50M
    drawn for 2 years then cleanedown to 35M for 3 years.
    """

    new_drawn_levels: Sequence[tuple[float, int]] = field(default_factory=list)

    def apply(self, ctx: ScenarioContext) -> ScenarioContext:
        if not ctx.segments:
            return ctx
        seg = ctx.segments[0]
        sched = seg.schedule
        if not sched.is_annual:
            raise ValueError(
                "DrawdownPatternMod currently only supports annual schedules."
            )
        flat: List[float] = []
        for drawn, n in self.new_drawn_levels:
            if n <= 0:
                raise ValueError(f"DrawdownPatternMod: n_years must be > 0, got {n}")
            flat.extend([float(drawn)] * int(n))
        if len(flat) != len(sched.periods):
            raise ValueError(
                f"DrawdownPatternMod profile has {len(flat)} years but "
                f"schedule has {len(sched.periods)} periods."
            )
        new_periods: List[Period] = []
        for p, new_drawn in zip(sched.periods, flat):
            clamped = min(float(new_drawn), p.commitment)
            new_periods.append(replace(p, avg_drawn=clamped))
        new_sched = Schedule(
            periods=new_periods,
            day_count=sched.day_count,
            type_=sched.type_,
        )
        new_seg = replace(seg, schedule=new_sched)
        return ScenarioContext(segments=[new_seg] + list(ctx.segments[1:]))

    def describe(self) -> str:
        bits = ", ".join(f"{d:,.0f}×{n}y" for d, n in self.new_drawn_levels)
        return f"drawdown→[{bits}]"


@dataclass
class BankProfileSwapMod(ScenarioMod):
    """Swap the engine config to a different bank's parameters.

    Two ways to specify the swap:

    1. **Profile key** — looks up :data:`raroc_engine.banks.BANK_PROFILES`
       and applies the profile's ``effective_tax_rate`` and
       ``funding_spread_bp`` via :meth:`EngineConfig.apply_bank_profile`.
       When the key is unknown (e.g. premium data not loaded), the
       config is left unchanged.
    2. **Explicit overrides** — pass any subset of ``funding_cost_bp`` /
       ``bank_tax_rate`` / ``cost_income_ratio`` directly. Tests use
       this path for determinism (no dependency on premium data).

    A bank swap affects the *whole* facility — every segment gets the
    same new config. This matches the natural counterfactual ("what if
    we'd taken this with bank X instead?"). Mid-life bank swaps are not
    in scope for v0.
    """

    profile_key: Optional[str] = None
    funding_cost_bp: Optional[float] = None
    bank_tax_rate: Optional[float] = None
    cost_income_ratio: Optional[float] = None

    def apply(self, ctx: ScenarioContext) -> ScenarioContext:
        new_segments: List[ScenarioSegment] = []
        for seg in ctx.segments:
            new_cfg = copy.deepcopy(seg.config)
            if self.profile_key:
                new_cfg.apply_bank_profile(self.profile_key)
            if self.funding_cost_bp is not None:
                new_cfg.funding_cost_bp = float(self.funding_cost_bp)
            if self.bank_tax_rate is not None:
                new_cfg.bank_tax_rate = float(self.bank_tax_rate)
            if self.cost_income_ratio is not None:
                new_cfg.default_cost_income_ratio = float(self.cost_income_ratio)
            new_segments.append(replace(
                seg,
                deal=copy.deepcopy(seg.deal),
                config=new_cfg,
            ))
        return ScenarioContext(segments=new_segments)

    def describe(self) -> str:
        if self.profile_key:
            return f"bank swap → {self.profile_key}"
        bits = []
        if self.funding_cost_bp is not None:
            bits.append(f"funding={self.funding_cost_bp * 10000:.0f}bp")
        if self.bank_tax_rate is not None:
            bits.append(f"tax={self.bank_tax_rate:.1%}")
        if self.cost_income_ratio is not None:
            bits.append(f"cost-ratio={self.cost_income_ratio:.0%}")
        return "bank swap (" + ", ".join(bits) + ")"


@dataclass
class StructureSwapMod(ScenarioMod):
    """Wholesale-replace the schedule (e.g. RCF → amortising term loan).

    Optionally also overrides selected deal fields via
    ``deal_overrides`` (``{"product_type": "...", "spread": 0.012, ...}``)
    so structural swaps that come with new pricing can be expressed in
    a single mod. Replaces every segment with a single new segment
    using the new schedule.
    """

    new_schedule: Schedule = field(default=None)  # type: ignore
    deal_overrides: Optional[dict] = None
    new_upfront_fee: Optional[float] = None

    def apply(self, ctx: ScenarioContext) -> ScenarioContext:
        if self.new_schedule is None:
            raise ValueError("StructureSwapMod.new_schedule is required.")
        if not ctx.segments:
            return ctx
        base = ctx.segments[0]
        new_deal = copy.deepcopy(base.deal)
        if self.deal_overrides:
            new_deal = replace(new_deal, **{
                k: v for k, v in self.deal_overrides.items()
                if k in new_deal.__dataclass_fields__
            })
        sched = self.new_schedule
        if self.new_upfront_fee is not None and sched.periods:
            new_periods = [replace(sched.periods[0], upfront_fee=float(self.new_upfront_fee))]
            new_periods.extend(replace(p) for p in sched.periods[1:])
            sched = Schedule(
                periods=new_periods,
                day_count=sched.day_count,
                type_=sched.type_,
            )
        new_seg = ScenarioSegment(
            deal=new_deal,
            schedule=sched,
            discount=base.discount,
            config=copy.deepcopy(base.config),
            t_offset_years=0.0,
        )
        return ScenarioContext(segments=[new_seg])

    def describe(self) -> str:
        n = len(self.new_schedule.periods) if self.new_schedule else 0
        return f"structure swap → schedule({n} periods)"


# ── Scenario + result types ──────────────────────────────────────────


@dataclass
class Scenario:
    """A named bundle of mods applied to the base in order.

    ``description`` is free-form text the App displays alongside the
    scenario name in the comparison table.
    """

    name: str
    mods: Sequence[ScenarioMod]
    description: str = ""


@dataclass(frozen=True)
class ScenarioRun:
    """Engine output for one base or one scenario.

    ``per_period`` rows are stitched across segments — each row's
    ``t_end_years`` reflects the global timeline anchored at year 0 of
    the original base, and discount factors are re-attached at that
    origin. ``aggregates`` is the :class:`FacilityAggregates` over the
    stitched rows.

    ``mods_applied`` is the human-readable rendering of each mod
    (``mod.describe()``) for the App's audit table. Empty list for
    the base run.
    """

    name: str
    description: str
    per_period: List[PeriodOutput]
    aggregates: FacilityAggregates
    discount_meta: dict
    engine_meta: dict
    mods_applied: List[str] = field(default_factory=list)

    @property
    def npv_borrower_cost(self) -> float:
        return self.aggregates.npv_borrower_cost

    @property
    def npv_bank_net_margin(self) -> float:
        return self.aggregates.npv_bank_net_margin

    @property
    def effective_spread_bp(self) -> float:
        return self.aggregates.effective_spread_bp

    @property
    def capital_weighted_raroc(self) -> float:
        return self.aggregates.capital_weighted_raroc

    @property
    def avg_raroc(self) -> float:
        return self.aggregates.avg_raroc


@dataclass(frozen=True)
class ScenarioDelta:
    """Headline differences vs the base for one scenario.

    Absolute (currency / bp) and relative (%) deltas are both surfaced
    so the App can render whichever the user asks for. ``%`` deltas
    fall back to ``0.0`` when the base value is exactly zero.
    """

    name: str
    npv_borrower_cost_delta: float
    npv_borrower_cost_pct: float
    npv_bank_net_margin_delta: float
    npv_bank_net_margin_pct: float
    npv_drawn_balance_delta: float
    effective_spread_bp_delta: float
    capital_weighted_raroc_bp_delta: float
    avg_raroc_bp_delta: float


@dataclass(frozen=True)
class ScenarioComparison:
    """Side-by-side comparison: base + N scenarios.

    :meth:`deltas` returns the headline deltas vs base for each
    scenario. :meth:`to_table` produces a dict shaped for the App's
    UI (one row per scenario including the base).
    """

    base: ScenarioRun
    scenarios: List[ScenarioRun]

    def deltas(self) -> List[ScenarioDelta]:
        return [_make_delta(self.base, s) for s in self.scenarios]

    def to_table(self) -> dict:
        rows = [_run_to_row(self.base, is_base=True)]
        for s in self.scenarios:
            rows.append(_run_to_row(s, is_base=False))
        return {
            "base_name": self.base.name,
            "rows": rows,
            "deltas": [d.__dict__ for d in self.deltas()],
        }

    @property
    def all_runs(self) -> List[ScenarioRun]:
        return [self.base] + list(self.scenarios)


# ── Runner ───────────────────────────────────────────────────────────


class ScenarioRunner:
    """Run base + scenarios through :class:`PeriodEngine`, surface a comparison.

    The runner owns no engine state itself — each scenario is run with
    its own :class:`EngineConfig` (mods may swap the config) so the
    base run is never contaminated by scenario-specific settings.
    """

    def __init__(
        self,
        repository: Optional[Repository] = None,
        config: Optional[EngineConfig] = None,
        *,
        curves: Optional[CurveRepository] = None,
        valuation_date: Optional[date] = None,
    ):
        self.repo = repository or Repository()
        self.cfg = config or EngineConfig()
        self.curves = curves
        self.valuation_date = valuation_date

    # ── Public API ────────────────────────────────────────────────

    def run_base(
        self,
        deal: RAROCInput,
        schedule: Schedule,
        discount: Optional[DiscountSpec] = None,
    ) -> ScenarioRun:
        """Run the base case (no mods)."""
        ctx = self._initial_context(deal, schedule, discount)
        return self._run(ctx, name="base", description="", mods_applied=[])

    def run_scenario(
        self,
        deal: RAROCInput,
        schedule: Schedule,
        scenario: Scenario,
        discount: Optional[DiscountSpec] = None,
    ) -> ScenarioRun:
        """Run one scenario (apply its mods to the base, then engine-run)."""
        ctx = self._initial_context(deal, schedule, discount)
        mods_applied: List[str] = []
        for mod in scenario.mods:
            ctx = mod.apply(ctx)
            mods_applied.append(mod.describe())
        return self._run(
            ctx,
            name=scenario.name,
            description=scenario.description,
            mods_applied=mods_applied,
        )

    def compare(
        self,
        deal: RAROCInput,
        schedule: Schedule,
        scenarios: Sequence[Scenario],
        discount: Optional[DiscountSpec] = None,
    ) -> ScenarioComparison:
        """Run base + each scenario and return a :class:`ScenarioComparison`."""
        base = self.run_base(deal, schedule, discount)
        runs = [self.run_scenario(deal, schedule, s, discount) for s in scenarios]
        return ScenarioComparison(base=base, scenarios=runs)

    # ── Internals ─────────────────────────────────────────────────

    def _initial_context(
        self,
        deal: RAROCInput,
        schedule: Schedule,
        discount: Optional[DiscountSpec],
    ) -> ScenarioContext:
        # Deepcopy guards the caller's inputs from in-place mutation by mods.
        spec = discount or DiscountSpec(kind="scalar", rate=self.cfg.risk_free_rate)
        seg = ScenarioSegment(
            deal=copy.deepcopy(deal),
            schedule=_clone_schedule(schedule),
            discount=copy.deepcopy(spec),
            config=copy.deepcopy(self.cfg),
            t_offset_years=0.0,
        )
        return ScenarioContext(segments=[seg])

    def _run(
        self,
        ctx: ScenarioContext,
        *,
        name: str,
        description: str,
        mods_applied: List[str],
    ) -> ScenarioRun:
        per_period: List[PeriodOutput] = []
        cumulative_t = 0.0
        last_engine_meta: dict = {}
        last_discount_meta: dict = {}
        rolled_curve_status: Optional[str] = None
        seg_segment_meta: List[dict] = []

        for seg in ctx.segments:
            engine = PeriodEngine(repository=self.repo, config=seg.config)
            out: PeriodEngineOutput = engine.run(
                seg.deal,
                seg.schedule,
                seg.discount,
                curves=self.curves,
                valuation_date=self.valuation_date,
            )
            # Stitch: re-anchor ``t_end_years`` on the global timeline
            # and re-attach DFs / PVs at the stitched origin.
            for row in out.per_period:
                row.t_end_years = float(row.t_end_years) + cumulative_t
            attach_discount_factors(out.per_period, seg.discount)
            per_period.extend(out.per_period)
            cumulative_t += seg.schedule.total_years
            last_engine_meta = out.engine_meta
            last_discount_meta = out.discount_meta
            seg_segment_meta.append({
                "n_periods": len(out.per_period),
                "total_years": seg.schedule.total_years,
                "discount_curve_status": out.discount_meta.get("curve_status"),
                "engine_curve_status": out.engine_meta.get("curve_status"),
            })
            cs = out.engine_meta.get("curve_status")
            if cs is not None:
                if (
                    rolled_curve_status is None
                    or STATUS_PRIORITY.get(cs, 99)
                    > STATUS_PRIORITY.get(rolled_curve_status, 99)
                ):
                    rolled_curve_status = cs

        # Re-index per-period rows on the global timeline so the
        # downstream UI can render a single contiguous schedule even
        # for multi-segment scenarios.
        for i, row in enumerate(per_period, start=1):
            row.index = i

        aggregates = aggregate_periods(per_period)

        engine_meta = dict(last_engine_meta)
        engine_meta["n_periods"] = len(per_period)
        engine_meta["total_years"] = cumulative_t
        engine_meta["n_segments"] = len(ctx.segments)
        engine_meta["segments"] = seg_segment_meta
        if rolled_curve_status is not None:
            engine_meta["curve_status"] = rolled_curve_status

        return ScenarioRun(
            name=name,
            description=description,
            per_period=per_period,
            aggregates=aggregates,
            discount_meta=last_discount_meta,
            engine_meta=engine_meta,
            mods_applied=mods_applied,
        )


# ── Helpers ──────────────────────────────────────────────────────────


def _clone_schedule(sched: Schedule) -> Schedule:
    """Shallow-copy a Schedule with cloned Period rows.

    Periods are mutable dataclasses; cloning them prevents mods (or the
    engine's per-period fixing fill-in) from leaking back into the
    caller's input.
    """
    return Schedule(
        periods=[replace(p) for p in sched.periods],
        day_count=sched.day_count,
        type_=sched.type_,
    )


def _add_year(d: date) -> date:
    """Match :func:`raroc_engine.schedule._add_year` semantics."""
    try:
        return d.replace(year=d.year + 1)
    except ValueError:
        return d.replace(year=d.year + 1, day=28)


def _safe_pct(num: float, denom: float) -> float:
    if denom == 0:
        return 0.0
    return (num / denom) * 100.0


def _make_delta(base: ScenarioRun, scenario: ScenarioRun) -> ScenarioDelta:
    base_agg = base.aggregates
    s_agg = scenario.aggregates
    npv_b_delta = s_agg.npv_borrower_cost - base_agg.npv_borrower_cost
    npv_m_delta = s_agg.npv_bank_net_margin - base_agg.npv_bank_net_margin
    drawn_delta = s_agg.npv_drawn_balance - base_agg.npv_drawn_balance
    return ScenarioDelta(
        name=scenario.name,
        npv_borrower_cost_delta=npv_b_delta,
        npv_borrower_cost_pct=_safe_pct(npv_b_delta, base_agg.npv_borrower_cost),
        npv_bank_net_margin_delta=npv_m_delta,
        npv_bank_net_margin_pct=_safe_pct(npv_m_delta, base_agg.npv_bank_net_margin),
        npv_drawn_balance_delta=drawn_delta,
        effective_spread_bp_delta=(
            s_agg.effective_spread_bp - base_agg.effective_spread_bp
        ),
        capital_weighted_raroc_bp_delta=(
            (s_agg.capital_weighted_raroc - base_agg.capital_weighted_raroc) * 10000.0
        ),
        avg_raroc_bp_delta=(
            (s_agg.avg_raroc - base_agg.avg_raroc) * 10000.0
        ),
    )


def _run_to_row(run: ScenarioRun, *, is_base: bool) -> dict:
    return {
        "name": run.name,
        "description": run.description,
        "is_base": is_base,
        "mods_applied": list(run.mods_applied),
        "npv_borrower_cost": run.aggregates.npv_borrower_cost,
        "npv_bank_net_margin": run.aggregates.npv_bank_net_margin,
        "npv_drawn_balance": run.aggregates.npv_drawn_balance,
        "effective_spread_bp": run.aggregates.effective_spread_bp,
        "capital_weighted_raroc": run.aggregates.capital_weighted_raroc,
        "avg_raroc": run.aggregates.avg_raroc,
        "total_revenue_undisc": run.aggregates.total_revenue_undisc,
        "total_el_undisc": run.aggregates.total_el_undisc,
        "n_periods": run.aggregates.n_periods,
        "total_years": run.aggregates.total_years,
        "per_period_raroc_bp": [r.raroc_bp for r in run.per_period],
    }


__all__ = [
    "ScenarioMod",
    "RefinanceMod",
    "RatesShiftMod",
    "DrawdownPatternMod",
    "BankProfileSwapMod",
    "StructureSwapMod",
    "Scenario",
    "ScenarioContext",
    "ScenarioSegment",
    "ScenarioRun",
    "ScenarioDelta",
    "ScenarioComparison",
    "ScenarioRunner",
]
