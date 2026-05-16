"""Portfolio model — typed collection of facilities with concentration & wallet RAROC.

Wraps :mod:`raroc_engine.optimizer` (one-shot cross-bank MILP) in a stateful
:class:`Portfolio`: a typed list of :class:`Facility` rows (each carrying a
deal :class:`RAROCInput` + :class:`Schedule` + bank/product/currency
metadata) plus the aggregation surface the App's wallet view needs:

- :meth:`Portfolio.total_exposure` — Σ EAD across facilities
- :meth:`Portfolio.concentration` — % of EAD by bank, country, product, currency
- :meth:`Portfolio.wallet_raroc` — FPE-weighted RAROC + revenue / NPV / EL totals
- :meth:`Portfolio.reallocate` — runs the optimizer under user-set
  concentration caps; surfaces infeasibility cleanly when caps conflict

Country is resolved per facility in this order: (1) explicit ``country``
on the :class:`Facility`, (2) :data:`raroc_engine.banks.BANK_PROFILES`
lookup on the bank key, (3) ``"Unknown"``. Tests inject country
explicitly so they do not depend on premium bank data being loaded.

The model is persistence-agnostic — the App (Credenda) owns row storage,
loading and saving. This module only defines the in-memory shape and
the aggregation maths. Spec: PLAN Task 2.1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Sequence

from .aggregate import FacilityAggregates, aggregate_periods
from .banks import BANK_PROFILES
from .config import EngineConfig
from .models import RAROCInput
from .period_engine import DiscountSpec, PeriodEngine
from .repository import Repository
from .schedule import Schedule


DEFAULT_START = date(2026, 1, 1)


# ── Facility ────────────────────────────────────────────────────────


@dataclass
class Facility:
    """One facility in a portfolio.

    ``deal`` carries the static facets (rating, product, GRR, spread,
    commit fee). ``schedule`` carries the time-varying volumes per spec
    §3 — for back-compat callers, a length-1 :class:`Schedule` built via
    :meth:`Schedule.from_raroc_input` is the canonical bridge.

    ``bank`` is a string key — typically a :data:`BANK_PROFILES` key
    (e.g. ``"bnp_paribas"``) when the App wants to wire reallocation to
    the optimizer, but any label is accepted at the portfolio level.

    ``country`` is optional — when ``None``, :class:`Portfolio` resolves
    it from :data:`BANK_PROFILES` at aggregation time and falls back to
    ``"Unknown"`` if the bank is not in the registry.

    ``facility_id`` is the row's stable identifier; falls back to
    ``deal.operation`` when blank, else a position-based string handed
    out by :class:`Portfolio` on add.
    """

    deal: RAROCInput
    schedule: Schedule
    bank: str
    facility_id: str = ""
    product: str = ""
    country: Optional[str] = None
    currency: str = "EUR"

    def __post_init__(self) -> None:
        if not self.product:
            self.product = self.deal.product_type
        if not self.facility_id:
            self.facility_id = self.deal.operation or ""

    @property
    def maturity_years(self) -> float:
        """Total contractual life of the facility (sum of period ``dt_years``)."""
        return self.schedule.total_years

    @property
    def commitment(self) -> float:
        """Initial commitment from the schedule's first period."""
        return self.schedule.periods[0].commitment if self.schedule.periods else 0.0

    @property
    def initial_drawn(self) -> float:
        """Drawn balance at the start of the schedule."""
        return self.schedule.periods[0].avg_drawn if self.schedule.periods else 0.0

    @classmethod
    def from_deal(
        cls,
        deal: RAROCInput,
        bank: str,
        *,
        start: date = DEFAULT_START,
        country: Optional[str] = None,
        currency: str = "EUR",
        facility_id: str = "",
    ) -> "Facility":
        """Build a length-1 facility from a :class:`RAROCInput` (single-period bridge).

        Useful for callers that have only a single-period deal in hand —
        the schedule is synthesised from the input's volumes + maturity
        via :meth:`Schedule.from_raroc_input`.
        """
        return cls(
            deal=deal,
            schedule=Schedule.from_raroc_input(deal, start=start),
            bank=bank,
            facility_id=facility_id,
            country=country,
            currency=currency,
        )


# ── Aggregate views ─────────────────────────────────────────────────


@dataclass(frozen=True)
class FacilityResult:
    """Engine output for one facility, cached on the portfolio.

    Fields mirror :class:`FacilityAggregates` (the wallet-grade headline
    numbers) and add the portfolio-level keys: ``facility_id`` and the
    resolved ``country``. ``exposure`` is the time-weighted average EAD
    across the schedule's life — matches :meth:`FacilityAggregates.avg_exposure`.
    """

    facility_id: str
    bank: str
    country: str
    product: str
    currency: str
    exposure: float
    fpe_years: float
    avg_raroc: float
    capital_weighted_raroc: float
    npv_borrower_cost: float
    npv_bank_net_margin: float
    total_revenue_undisc: float
    total_el_undisc: float
    n_periods: int
    total_years: float


@dataclass(frozen=True)
class ConcentrationView:
    """% of total EAD per bucket.

    All four dicts share the same denominator (``total_exposure``).
    Buckets with zero exposure are omitted. When ``total_exposure`` is
    zero, every dict is empty.
    """

    total_exposure: float
    by_bank: Dict[str, float]
    by_country: Dict[str, float]
    by_product: Dict[str, float]
    by_currency: Dict[str, float]


@dataclass(frozen=True)
class WalletAggregate:
    """Portfolio-level aggregates summed/weighted across facilities.

    ``wallet_raroc`` is the FPE-years-weighted RAROC — the
    capital-team's headline number, consistent with how
    :class:`FacilityAggregates.capital_weighted_raroc` weights a single
    facility's periods.

    ``avg_raroc`` is the **exposure-weighted** RAROC — the borrower-
    side view that the App's wallet card shows next to "average cost of
    debt". Provided alongside ``wallet_raroc`` so the App can pick the
    view it needs without re-aggregating.
    """

    n_facilities: int
    total_exposure: float
    total_fpe_years: float
    wallet_raroc: float
    avg_raroc: float
    total_revenue_undisc: float
    total_npv_borrower_cost: float
    total_npv_bank_net_margin: float
    total_el_undisc: float


# ── Reallocation surface ────────────────────────────────────────────


@dataclass(frozen=True)
class ConcentrationCaps:
    """User-set caps on a portfolio reallocation.

    ``max_bank_pct`` / ``max_region_pct`` are fractions in ``[0, 1]``.
    ``min_banks`` is an integer ≥ 1. ``locked`` pins specific facilities
    to specific banks before the optimizer runs.
    """

    max_bank_pct: float = 0.30
    min_banks: int = 3
    max_region_pct: float = 0.50
    target_raroc: float = 0.12
    locked: Optional[Dict[str, str]] = None  # facility_id → bank_key


@dataclass(frozen=True)
class ReallocationResult:
    """Structured result of :meth:`Portfolio.reallocate`.

    ``status`` is ``"optimal"`` when the MILP found a feasible
    assignment, ``"infeasible"`` otherwise. The ``error`` field is
    populated on infeasibility with a human-readable explanation —
    pre-validation reasons are surfaced verbatim, optimizer-side
    reasons get a relaxation hint.

    ``assignments`` / ``bank_allocations`` / ``summary`` carry the
    optimizer's optimal solution (the underlying optimizer dict shape
    is preserved so the App can render today's tables unchanged).
    """

    status: str
    error: Optional[str] = None
    assignments: List[dict] = field(default_factory=list)
    bank_allocations: List[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    caps: Optional[ConcentrationCaps] = None

    @property
    def is_feasible(self) -> bool:
        return self.status == "optimal"


# ── Portfolio ───────────────────────────────────────────────────────


class Portfolio:
    """Stateful collection of facilities + aggregation surface.

    Engine results are computed once per facility (via
    :class:`PeriodEngine` + :func:`aggregate_periods`) and cached on the
    portfolio. The cache is keyed by the facility's id and invalidates
    when :meth:`add_facility` / :meth:`remove_facility` mutate the row
    set, or when :meth:`invalidate` is called by a caller that mutated
    a facility's ``deal`` or ``schedule`` in place.

    The portfolio is persistence-agnostic: callers (Credenda's wallet
    module) own the row storage and pass facilities in via the
    constructor or :meth:`add_facility`. Engine config + repository +
    discount spec live on the portfolio so the App can configure them
    once and let aggregation work without re-supplying them per call.
    """

    def __init__(
        self,
        facilities: Optional[Sequence[Facility]] = None,
        *,
        repository: Optional[Repository] = None,
        config: Optional[EngineConfig] = None,
        discount: Optional[DiscountSpec] = None,
        name: str = "",
    ):
        self.name = name
        self.repo = repository or Repository()
        self.cfg = config or EngineConfig()
        self.discount = discount or DiscountSpec(
            kind="scalar", rate=self.cfg.risk_free_rate,
        )
        self._engine = PeriodEngine(repository=self.repo, config=self.cfg)
        self._facilities: List[Facility] = []
        self._results_cache: Dict[str, FacilityResult] = {}
        for f in facilities or ():
            self.add_facility(f)

    # ── Row management ───────────────────────────────────────────

    @property
    def facilities(self) -> List[Facility]:
        """Read-only view over the current facility list."""
        return list(self._facilities)

    def __len__(self) -> int:
        return len(self._facilities)

    def __iter__(self):
        return iter(self._facilities)

    def add_facility(self, facility: Facility) -> str:
        """Append a facility, assigning a position-based id if missing.

        Returns the assigned ``facility_id``.
        """
        if not facility.facility_id:
            facility.facility_id = f"facility-{len(self._facilities) + 1}"
        if any(f.facility_id == facility.facility_id for f in self._facilities):
            raise ValueError(
                f"duplicate facility_id: {facility.facility_id!r}"
            )
        self._facilities.append(facility)
        self._results_cache.pop(facility.facility_id, None)
        return facility.facility_id

    def remove_facility(self, facility_id: str) -> Facility:
        """Remove a facility by id and drop its cached engine result.

        Raises :class:`KeyError` if no facility matches.
        """
        for i, f in enumerate(self._facilities):
            if f.facility_id == facility_id:
                self._results_cache.pop(facility_id, None)
                return self._facilities.pop(i)
        raise KeyError(f"facility_id not found: {facility_id!r}")

    def get_facility(self, facility_id: str) -> Facility:
        for f in self._facilities:
            if f.facility_id == facility_id:
                return f
        raise KeyError(f"facility_id not found: {facility_id!r}")

    def invalidate(self, facility_id: Optional[str] = None) -> None:
        """Drop cached engine results.

        With ``facility_id`` set, drops only that row's cache. Otherwise
        clears every cache entry — call after mutating multiple
        facilities in place.
        """
        if facility_id is None:
            self._results_cache.clear()
        else:
            self._results_cache.pop(facility_id, None)

    # ── Engine integration ──────────────────────────────────────

    def result_for(self, facility_id: str) -> FacilityResult:
        """Engine output for one facility (cached on the portfolio)."""
        if facility_id in self._results_cache:
            return self._results_cache[facility_id]
        f = self.get_facility(facility_id)
        result = self._compute_result(f)
        self._results_cache[facility_id] = result
        return result

    def results(self) -> List[FacilityResult]:
        """All facility results, in portfolio order."""
        return [self.result_for(f.facility_id) for f in self._facilities]

    def _compute_result(self, f: Facility) -> FacilityResult:
        """Run the period engine on one facility and project to FacilityResult."""
        out = self._engine.run(f.deal, f.schedule, self.discount)
        agg: FacilityAggregates = aggregate_periods(out.per_period)
        country = self._resolve_country(f)
        return FacilityResult(
            facility_id=f.facility_id,
            bank=f.bank,
            country=country,
            product=f.product or f.deal.product_type,
            currency=f.currency,
            exposure=agg.avg_exposure,
            fpe_years=agg.fpe_years,
            avg_raroc=agg.avg_raroc,
            capital_weighted_raroc=agg.capital_weighted_raroc,
            npv_borrower_cost=agg.npv_borrower_cost,
            npv_bank_net_margin=agg.npv_bank_net_margin,
            total_revenue_undisc=agg.total_revenue_undisc,
            total_el_undisc=agg.total_el_undisc,
            n_periods=agg.n_periods,
            total_years=agg.total_years,
        )

    @staticmethod
    def _resolve_country(f: Facility) -> str:
        """Country lookup: explicit override → BANK_PROFILES → 'Unknown'."""
        if f.country:
            return f.country
        prof = BANK_PROFILES.get(f.bank)
        return prof.country if prof else "Unknown"

    # ── Concentration ───────────────────────────────────────────

    @property
    def total_exposure(self) -> float:
        """Σ EAD across the portfolio (time-weighted avg per facility)."""
        return sum(r.exposure for r in self.results())

    def concentration(self) -> ConcentrationView:
        """% of EAD per bank / country / product / currency.

        Buckets with zero exposure are omitted. With an empty portfolio
        (or total exposure 0) every dict is empty and ``total_exposure``
        is 0.
        """
        rows = self.results()
        total = sum(r.exposure for r in rows)
        if total <= 0:
            return ConcentrationView(
                total_exposure=0.0,
                by_bank={}, by_country={}, by_product={}, by_currency={},
            )

        def bucket(key_fn):
            agg: Dict[str, float] = {}
            for r in rows:
                k = key_fn(r)
                agg[k] = agg.get(k, 0.0) + r.exposure
            return {k: v / total for k, v in agg.items()}

        return ConcentrationView(
            total_exposure=total,
            by_bank=bucket(lambda r: r.bank),
            by_country=bucket(lambda r: r.country),
            by_product=bucket(lambda r: r.product),
            by_currency=bucket(lambda r: r.currency),
        )

    # ── Wallet RAROC ────────────────────────────────────────────

    def wallet_raroc(self) -> WalletAggregate:
        """Portfolio-level aggregates summed / weighted across facilities.

        ``wallet_raroc`` weights each facility's ``capital_weighted_raroc``
        by its ``fpe_years`` (= Σ FPE × dt) — when every facility is a
        single 1y period with the same FPE, this collapses to a simple
        mean; for a multi-facility wallet it favours the larger /
        longer-lived capital usage.

        ``avg_raroc`` weights by ``exposure × total_years`` — the
        exposure-side equivalent. For a portfolio of identical
        facilities the two coincide; under non-uniform sizes the two
        diverge in the same way :class:`FacilityAggregates` does.
        """
        rows = self.results()
        if not rows:
            return WalletAggregate(
                n_facilities=0,
                total_exposure=0.0,
                total_fpe_years=0.0,
                wallet_raroc=0.0,
                avg_raroc=0.0,
                total_revenue_undisc=0.0,
                total_npv_borrower_cost=0.0,
                total_npv_bank_net_margin=0.0,
                total_el_undisc=0.0,
            )

        total_exp = sum(r.exposure for r in rows)
        total_fpe_yrs = sum(r.fpe_years for r in rows)
        # Wallet RAROC = FPE-years-weighted mean of each facility's
        # capital-weighted RAROC. Falls back to simple mean when FPE
        # is uniformly zero (no risk-weighted assets — pathological
        # but should not divide-by-zero).
        if total_fpe_yrs > 0:
            wallet_r = sum(r.capital_weighted_raroc * r.fpe_years for r in rows) / total_fpe_yrs
        else:
            wallet_r = sum(r.capital_weighted_raroc for r in rows) / len(rows)

        # Exposure-weighted RAROC: weight by exposure × years so a 5y
        # facility counts more than a 1y facility of the same EAD.
        exp_yr_weights = [r.exposure * r.total_years for r in rows]
        total_w = sum(exp_yr_weights)
        if total_w > 0:
            avg_r = sum(
                r.avg_raroc * w for r, w in zip(rows, exp_yr_weights)
            ) / total_w
        else:
            avg_r = sum(r.avg_raroc for r in rows) / len(rows)

        return WalletAggregate(
            n_facilities=len(rows),
            total_exposure=total_exp,
            total_fpe_years=total_fpe_yrs,
            wallet_raroc=wallet_r,
            avg_raroc=avg_r,
            total_revenue_undisc=sum(r.total_revenue_undisc for r in rows),
            total_npv_borrower_cost=sum(r.npv_borrower_cost for r in rows),
            total_npv_bank_net_margin=sum(r.npv_bank_net_margin for r in rows),
            total_el_undisc=sum(r.total_el_undisc for r in rows),
        )

    # ── Reallocation ─────────────────────────────────────────────

    def reallocate(
        self,
        caps: Optional[ConcentrationCaps] = None,
        *,
        bank_universe: Optional[Sequence[str]] = None,
    ) -> ReallocationResult:
        """Find a feasible facility-to-bank assignment under ``caps``.

        Pre-validates the caps for arithmetic infeasibility (caps that
        cannot be satisfied by any assignment regardless of facility
        size / spreads) before delegating to the underlying MILP. Both
        pre-validation and optimizer rejection produce a
        ``ReallocationResult`` with ``status="infeasible"`` and a
        populated ``error`` — the App renders both identically.

        Args:
            caps: User-set concentration caps. Defaults to
                ``ConcentrationCaps()`` (30% bank cap, 3 banks min,
                50% region cap, 12% target RAROC).
            bank_universe: Bank keys eligible for assignment. When
                ``None``, falls back to the distinct banks currently
                held in the portfolio — this is the natural
                "reallocate among my current banks" call.
        """
        caps = caps or ConcentrationCaps()
        from .optimizer import optimize_portfolio  # local import to dodge cycles

        if not self._facilities:
            return ReallocationResult(
                status="infeasible",
                error="Portfolio is empty — no facilities to allocate.",
                caps=caps,
            )

        if bank_universe is None:
            bank_universe = self._distinct_banks_in_profiles()

        universe = list(bank_universe)
        if not universe:
            return ReallocationResult(
                status="infeasible",
                error=(
                    "No banks in universe. Pass ``bank_universe=`` explicitly "
                    "or use facilities whose ``bank`` is a key in BANK_PROFILES."
                ),
                caps=caps,
            )

        # Translate locked facility_ids → optimizer-style {index: bank_key}.
        # Validated before arithmetic prechecks so a typo'd lock surfaces as
        # a config error rather than masquerading as a cap mismatch.
        locked_by_index: Dict[int, str] = {}
        if caps.locked:
            id_to_idx = {f.facility_id: i for i, f in enumerate(self._facilities)}
            for fid, bank in caps.locked.items():
                if fid not in id_to_idx:
                    return ReallocationResult(
                        status="infeasible",
                        error=f"Locked facility_id not in portfolio: {fid!r}",
                        caps=caps,
                    )
                if bank not in universe:
                    return ReallocationResult(
                        status="infeasible",
                        error=(
                            f"Locked bank {bank!r} (facility {fid!r}) "
                            "not in bank_universe"
                        ),
                        caps=caps,
                    )
                locked_by_index[id_to_idx[fid]] = bank

        # Pre-validate arithmetic feasibility of the caps themselves.
        feasibility_error = self._precheck_caps(caps, universe)
        if feasibility_error:
            return ReallocationResult(
                status="infeasible", error=feasibility_error, caps=caps,
            )

        # The optimizer reads volumes off ``deal.average_volume`` / ``deal.average_drawn``.
        # When a caller built the facility from a multi-period Schedule but
        # left those fields at the dataclass defaults (= 0), the optimizer
        # produces zero EAD and bails as "Total exposure is zero". Fill in
        # the schedule's period-1 commitment/drawn before handing over.
        deals = [self._optimizer_deal(f) for f in self._facilities]
        result = optimize_portfolio(
            deals,
            universe,
            self.repo,
            self.cfg,
            target_raroc=caps.target_raroc,
            max_bank_pct=caps.max_bank_pct,
            min_banks=caps.min_banks,
            max_region_pct=caps.max_region_pct,
            locked=locked_by_index or None,
        )

        if result.get("status") != "optimal":
            return ReallocationResult(
                status="infeasible",
                error=result.get("error", "Optimizer returned no solution."),
                caps=caps,
            )

        # Annotate assignments with the portfolio's facility_id (the
        # optimizer only knows positions). Keep the optimizer's dict
        # shape on each row so the App's existing renderers keep working.
        for row in result.get("assignments", []):
            idx = row.get("facility_index")
            if isinstance(idx, int) and 0 <= idx < len(self._facilities):
                row["facility_id"] = self._facilities[idx].facility_id

        return ReallocationResult(
            status="optimal",
            error=None,
            assignments=result.get("assignments", []),
            bank_allocations=result.get("summary", {}).get("bank_allocations", []),
            summary=result.get("summary", {}),
            caps=caps,
        )

    def _distinct_banks_in_profiles(self) -> List[str]:
        """Distinct banks held in the portfolio, restricted to BANK_PROFILES keys.

        Optimizer expects keys it can resolve in :data:`BANK_PROFILES`;
        a facility whose ``bank`` is a free-form label (e.g. an unmapped
        local bank) is silently dropped from the default universe.
        Callers can always pass ``bank_universe=`` explicitly.
        """
        seen: List[str] = []
        for f in self._facilities:
            if f.bank in BANK_PROFILES and f.bank not in seen:
                seen.append(f.bank)
        return seen

    def _precheck_caps(
        self,
        caps: ConcentrationCaps,
        universe: Sequence[str],
    ) -> Optional[str]:
        """Return a human-readable error if ``caps`` can't be satisfied.

        Two arithmetic checks the MILP would also catch but more
        explicitly — and more cheaply, since we want to fail fast
        before scipy.optimize.milp is invoked:

        1. ``max_bank_pct × len(universe) < 1`` → can't cover 100% of
           exposure under the per-bank cap (e.g. 5 banks × 15% < 1).
        2. Any facility's EAD > ``max_bank_pct × total EAD`` → that
           facility alone exceeds any bank's cap, so no assignment can
           fit it.
        3. ``min_banks > len(universe)`` → trivially infeasible.
        """
        m = len(universe)
        if caps.min_banks > m:
            return (
                f"min_banks={caps.min_banks} exceeds bank universe size {m}. "
                "Lower min_banks or pass a larger bank_universe."
            )
        if caps.max_bank_pct * m + 1e-9 < 1.0:
            return (
                f"max_bank_pct={caps.max_bank_pct:.2%} × {m} banks = "
                f"{caps.max_bank_pct * m:.2%} < 100% — caps cannot cover "
                "total exposure. Raise max_bank_pct or expand bank_universe."
            )

        results = self.results()
        total = sum(r.exposure for r in results)
        if total <= 0:
            return "Total exposure is zero — every facility's EAD computes to 0."

        cap_per_bank = caps.max_bank_pct * total
        for f, r in zip(self._facilities, results):
            if r.exposure - 1e-6 > cap_per_bank:
                return (
                    f"Facility {f.facility_id!r} EAD={r.exposure:,.0f} exceeds "
                    f"per-bank cap {cap_per_bank:,.0f} "
                    f"({caps.max_bank_pct:.2%} of total {total:,.0f}). "
                    "Split the facility, raise max_bank_pct, or add banks."
                )
        return None

    def _optimizer_deal(self, f: Facility) -> RAROCInput:
        """RAROCInput for the optimizer, with volumes/maturity from the schedule.

        Mutates a copy of ``f.deal`` rather than ``f.deal`` itself so we
        do not silently change the caller's facility. The optimizer
        only reads the deal's static fields + volumes; it does not
        consume the schedule.
        """
        from dataclasses import replace

        period = f.schedule.periods[0] if f.schedule.periods else None
        volume = period.commitment if period else (f.deal.average_volume or 0.0)
        drawn = period.avg_drawn if period else (f.deal.average_drawn or 0.0)
        maturity_months = (
            f.schedule.total_years * 12.0 if f.schedule.periods
            else f.deal.residual_maturity
        )
        return replace(
            f.deal,
            operation=f.deal.operation or f.facility_id,
            average_volume=f.deal.average_volume or volume,
            average_drawn=f.deal.average_drawn or drawn,
            initial_volume=f.deal.initial_volume or volume,
            initial_drawn=f.deal.initial_drawn or drawn,
            initial_maturity=f.deal.initial_maturity or maturity_months,
            residual_maturity=f.deal.residual_maturity or maturity_months,
        )


__all__ = [
    "Facility",
    "FacilityResult",
    "ConcentrationView",
    "WalletAggregate",
    "ConcentrationCaps",
    "ReallocationResult",
    "Portfolio",
]
