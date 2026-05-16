"""Multi-period schedule model for the RAROC engine.

A ``Schedule`` is the time-varying companion to a ``RAROCInput``: it carries
``commitment`` / ``avg_drawn`` / ``remaining_maturity_years`` (plus floating-rate
fixings and period-allocated fees) for each row of a facility's life, while
the deal carries the static facets (rating, spread, commit fee, etc.).

Spec: ``docs/engine/multiperiod-spec.md`` §3. The period engine (Task 1.3,
``raroc_engine/period_engine.py``) consumes ``Schedule`` instances; this
module only defines the data model and the four common-shape constructors.

A length-1 schedule with ``dt_years=1.0`` is the back-compat contract for the
existing single-period calculator (spec §9). ``Schedule.from_raroc_input`` is
the canonical bridge.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional, Sequence


def _add_year(d: date) -> date:
    """Return ``d`` shifted forward by one year, clamping Feb 29 to Feb 28."""
    try:
        return d.replace(year=d.year + 1)
    except ValueError:
        return d.replace(year=d.year + 1, day=28)


@dataclass
class Period:
    """One row of a ``Schedule``.

    Fields match the period schema in ``docs/engine/multiperiod-spec.md`` §3
    and the YAML fixtures under ``tests/fixtures/period_*.yaml``.
    """

    index: int
    start: date
    end: date
    dt_years: float
    commitment: float
    avg_drawn: float
    remaining_maturity_years: float
    upfront_fee: float = 0.0
    flat_fee: float = 0.0
    participation_fee: float = 0.0
    floating_index: Optional[str] = None
    fixing_rate: Optional[float] = None

    def __post_init__(self) -> None:
        if self.dt_years <= 0:
            raise ValueError(
                f"period {self.index}: dt_years must be > 0, got {self.dt_years}"
            )
        if self.commitment < 0:
            raise ValueError(
                f"period {self.index}: commitment must be >= 0, got {self.commitment}"
            )
        if self.avg_drawn < 0:
            raise ValueError(
                f"period {self.index}: avg_drawn must be >= 0, got {self.avg_drawn}"
            )
        if self.avg_drawn > self.commitment + 1e-6:
            raise ValueError(
                f"period {self.index}: avg_drawn {self.avg_drawn} > commitment {self.commitment}"
            )
        if self.remaining_maturity_years <= 0:
            raise ValueError(
                f"period {self.index}: remaining_maturity_years must be > 0, got {self.remaining_maturity_years}"
            )
        if self.end <= self.start:
            raise ValueError(
                f"period {self.index}: end {self.end} must be after start {self.start}"
            )
        # Allow ``floating_index`` set without ``fixing_rate`` — this means
        # "floating leg not yet resolved" and the period engine will pull
        # the fixing from the curve repository at run time. The reverse
        # (``fixing_rate`` set with no ``floating_index``) is still rejected
        # because a bare rate without an index name is meaningless.
        if self.fixing_rate is not None and self.floating_index is None:
            raise ValueError(
                f"period {self.index}: fixing_rate set without a floating_index"
            )

    @property
    def avg_undrawn(self) -> float:
        """Time-weighted average undrawn balance over the period."""
        return max(0.0, self.commitment - self.avg_drawn)

    def all_in_rate(self, spread: float) -> Optional[float]:
        """Borrower's all-in rate over the period.

        Returns ``fixing_rate + spread`` for floating periods, ``None`` for
        fixed-rate periods (the caller resolves the fixed rate from the deal).
        """
        if self.fixing_rate is None:
            return None
        return self.fixing_rate + spread


@dataclass
class Schedule:
    """Ordered list of ``Period`` rows describing a facility's life.

    Construct with one of the four shape helpers (``bullet_rcf_with_cleandown``,
    ``scheduled_amortising_term_loan``, ``drawdown_ramp_with_grace``,
    ``project_finance_milestones``) or with ``single_period`` /
    ``from_raroc_input`` for the back-compat path.
    """

    periods: list[Period]
    day_count: str = "Act/365F"
    type_: str = "annual"

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """Check structural invariants the period engine relies on."""
        if not self.periods:
            raise ValueError("Schedule must contain at least one Period")
        for i, p in enumerate(self.periods, start=1):
            if p.index != i:
                raise ValueError(
                    f"period index out of order: expected {i}, got {p.index}"
                )
            if i > 1:
                prev = self.periods[i - 2]
                if p.start != prev.end:
                    raise ValueError(
                        f"period {i} start {p.start} not contiguous with "
                        f"period {i - 1} end {prev.end}"
                    )

    @property
    def is_annual(self) -> bool:
        return all(abs(p.dt_years - 1.0) < 1e-9 for p in self.periods)

    @property
    def total_years(self) -> float:
        return sum(p.dt_years for p in self.periods)

    @property
    def start(self) -> date:
        return self.periods[0].start

    @property
    def end(self) -> date:
        return self.periods[-1].end

    def principal_paydowns(self) -> list[float]:
        """Per-period reduction in commitment.

        ``[commitment[i] - commitment[i+1]]`` with a final entry of
        ``commitment[-1]`` (the residual repaid at maturity). The list has
        the same length as ``periods``.
        """
        paydowns: list[float] = []
        for i, p in enumerate(self.periods):
            if i + 1 < len(self.periods):
                paydowns.append(p.commitment - self.periods[i + 1].commitment)
            else:
                paydowns.append(p.commitment)
        return paydowns

    def to_dict(self) -> dict:
        return {
            "type": self.type_,
            "day_count": self.day_count,
            "periods": [
                {
                    "index": p.index,
                    "start": p.start.isoformat(),
                    "end": p.end.isoformat(),
                    "dt_years": p.dt_years,
                    "commitment": p.commitment,
                    "avg_drawn": p.avg_drawn,
                    "remaining_maturity_years": p.remaining_maturity_years,
                    "upfront_fee": p.upfront_fee,
                    "flat_fee": p.flat_fee,
                    "participation_fee": p.participation_fee,
                    "floating_index": p.floating_index,
                    "fixing_rate": p.fixing_rate,
                }
                for p in self.periods
            ],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Schedule":
        """Load a Schedule from a fixture-style dict (matches YAML layout)."""
        periods: list[Period] = []
        for row in d["periods"]:
            s = row["start"]
            e = row["end"]
            periods.append(Period(
                index=int(row["index"]),
                start=date.fromisoformat(s) if isinstance(s, str) else s,
                end=date.fromisoformat(e) if isinstance(e, str) else e,
                dt_years=float(row["dt_years"]),
                commitment=float(row["commitment"]),
                avg_drawn=float(row["avg_drawn"]),
                remaining_maturity_years=float(row["remaining_maturity_years"]),
                upfront_fee=float(row.get("upfront_fee", 0.0) or 0.0),
                flat_fee=float(row.get("flat_fee", 0.0) or 0.0),
                participation_fee=float(row.get("participation_fee", 0.0) or 0.0),
                floating_index=row.get("floating_index"),
                fixing_rate=(
                    float(row["fixing_rate"]) if row.get("fixing_rate") is not None else None
                ),
            ))
        return cls(
            periods=periods,
            day_count=d.get("day_count", "Act/365F"),
            type_=d.get("type", "annual"),
        )

    # ── Floating-rate fixings ──────────────────────────────────────

    def attach_fixings(
        self,
        repo,
        *,
        valuation_date: Optional[date] = None,
        fallback_rate: float = 0.0325,
        force: bool = False,
    ) -> list:
        """Resolve floating fixings on every floating period.

        Walks each ``Period`` whose ``floating_index`` is set and
        ``fixing_rate`` is None (or every floating period if ``force=True``),
        asks the ``CurveRepository`` for a fixing at ``valuation_date``
        (default: the schedule's start), and writes ``fixing_rate`` back
        onto the period. Returns a list of :class:`CurveFixingResult` —
        one per resolved period, in period-index order.

        Phase 1 fixes every period at *the same* valuation_date — there
        is no forward-curve projection yet (F-22). When forward curves
        ship, this method gets a per-period ``as_of`` so each row picks
        up the right point on the curve.
        """
        ref = valuation_date or self.start
        results = []
        for p in self.periods:
            if p.floating_index is None:
                continue
            if p.fixing_rate is not None and not force:
                continue
            fixing = repo.fix(
                p.floating_index,
                ref,
                fallback_rate=fallback_rate,
            )
            # Period is a mutable dataclass — direct attribute write is fine.
            p.fixing_rate = float(fixing.rate)
            results.append(fixing)
        return results

    # ── Backwards-compat constructors ──────────────────────────────

    @classmethod
    def single_period(
        cls,
        *,
        commitment: float,
        avg_drawn: float,
        residual_maturity_years: float,
        start: date,
        upfront_fee: float = 0.0,
        flat_fee: float = 0.0,
        participation_fee: float = 0.0,
        floating_index: Optional[str] = None,
        fixing_rate: Optional[float] = None,
    ) -> "Schedule":
        """Length-1 schedule with ``dt_years=1.0``.

        Reproduces today's single-period calculator behaviour. Spec §9 sets
        the contract: a Schedule of this shape, paired with the same
        ``RAROCInput``, must yield identical engine output to within 1e-12.
        """
        return cls(periods=[Period(
            index=1,
            start=start,
            end=_add_year(start),
            dt_years=1.0,
            commitment=commitment,
            avg_drawn=avg_drawn,
            remaining_maturity_years=residual_maturity_years,
            upfront_fee=upfront_fee,
            flat_fee=flat_fee,
            participation_fee=participation_fee,
            floating_index=floating_index,
            fixing_rate=fixing_rate,
        )])

    @classmethod
    def from_raroc_input(cls, inp, *, start: date) -> "Schedule":
        """Build the canonical single-period back-compat Schedule for a ``RAROCInput``.

        Translates the input's ``residual_maturity`` (months) to years and
        copies volumes and period-1 fees over.
        """
        return cls.single_period(
            commitment=getattr(inp, "average_volume", 0.0) or 0.0,
            avg_drawn=getattr(inp, "average_drawn", 0.0) or 0.0,
            residual_maturity_years=float(getattr(inp, "residual_maturity", 12.0) or 0.0) / 12.0,
            start=start,
            upfront_fee=getattr(inp, "upfront_fee", 0.0) or 0.0,
            flat_fee=getattr(inp, "flat_fee", 0.0) or 0.0,
            participation_fee=getattr(inp, "participation_fee", 0.0) or 0.0,
        )

    # ── Common shapes ──────────────────────────────────────────────

    @classmethod
    def bullet_rcf_with_cleandown(
        cls,
        *,
        commitment: float,
        drawn_levels: Sequence[tuple[float, int]],
        start: date,
        upfront_fee: float = 0.0,
        floating_index: Optional[str] = None,
    ) -> "Schedule":
        """Confirmed RCF with a constant commitment and stepped drawn levels.

        ``drawn_levels`` is a sequence of ``(avg_drawn, n_years)`` tuples; the
        cleandown profile is the concatenation of ``n_years`` periods at each
        level. Maturity = sum of ``n_years``.

        Example (5y, 50M facility, cleandown to 20M after year 3)::

            Schedule.bullet_rcf_with_cleandown(
                commitment=50_000_000,
                drawn_levels=[(35_000_000, 3), (20_000_000, 2)],
                start=date(2026, 6, 1),
                upfront_fee=200_000,
            )

        matches ``tests/fixtures/period_rcf_5y.yaml``.
        """
        avg_drawns: list[float] = []
        for drawn, n in drawn_levels:
            if n <= 0:
                raise ValueError(f"drawn_levels: n_years must be > 0, got {n}")
            avg_drawns.extend([float(drawn)] * int(n))
        commitments = [float(commitment)] * len(avg_drawns)
        return cls._build_annual(
            commitments, avg_drawns, start=start, upfront_fee=upfront_fee,
            floating_index=floating_index,
        )

    @classmethod
    def scheduled_amortising_term_loan(
        cls,
        *,
        initial_drawn: float,
        total_years: int,
        start: date,
        final_balance: float = 0.0,
        upfront_fee: float = 0.0,
        floating_index: Optional[str] = None,
    ) -> "Schedule":
        """Linear-amortising term loan.

        Drawn balance amortises linearly from ``initial_drawn`` to
        ``final_balance`` in ``total_years`` equal steps. ``commitment[i]`` is
        the start-of-period balance; ``avg_drawn[i]`` is the mid-period balance
        ``(start + end) / 2``.

        Example (7y, 70M day-1, 10M/yr to 0)::

            Schedule.scheduled_amortising_term_loan(
                initial_drawn=70_000_000,
                total_years=7,
                start=date(2026, 6, 1),
                upfront_fee=350_000,
            )

        matches ``tests/fixtures/period_termloan_7y_amortising.yaml``.
        """
        if total_years <= 0:
            raise ValueError(f"total_years must be > 0, got {total_years}")
        step = (float(initial_drawn) - float(final_balance)) / total_years
        commitments: list[float] = []
        avg_drawns: list[float] = []
        bal = float(initial_drawn)
        for _ in range(total_years):
            next_bal = bal - step
            commitments.append(bal)
            avg_drawns.append((bal + next_bal) / 2.0)
            bal = next_bal
        return cls._build_annual(
            commitments, avg_drawns, start=start, upfront_fee=upfront_fee,
            floating_index=floating_index,
        )

    @classmethod
    def drawdown_ramp_with_grace(
        cls,
        *,
        commitment: float,
        ramp_drawns: Sequence[float],
        grace_years: int,
        amortise_drawns: Sequence[float],
        bullet_drawn: float = 0.0,
        bullet_years: int = 0,
        start: date,
        upfront_fee: float = 0.0,
        floating_index: Optional[str] = None,
    ) -> "Schedule":
        """Project-style ramp → grace → amortise → residual bullet.

        Commitment is constant for all periods. The ``avg_drawn`` sequence is
        the concatenation of:

        - ``ramp_drawns`` (one entry per ramp year)
        - ``commitment`` repeated ``grace_years`` times (full draw during grace)
        - ``amortise_drawns`` (one entry per amortisation year)
        - ``bullet_drawn`` repeated ``bullet_years`` times (residual until maturity)

        Example (10y project finance)::

            Schedule.drawdown_ramp_with_grace(
                commitment=100_000_000,
                ramp_drawns=[30_000_000, 70_000_000, 100_000_000],
                grace_years=2,
                amortise_drawns=[90_000_000, 70_000_000, 50_000_000, 30_000_000],
                bullet_drawn=20_000_000,
                bullet_years=1,
                start=date(2026, 6, 1),
                upfront_fee=1_000_000,
            )

        matches ``tests/fixtures/period_projfin_10y_grace.yaml``.
        """
        if grace_years < 0 or bullet_years < 0:
            raise ValueError("grace_years and bullet_years must be >= 0")
        avg_drawns: list[float] = (
            [float(d) for d in ramp_drawns]
            + [float(commitment)] * int(grace_years)
            + [float(d) for d in amortise_drawns]
            + [float(bullet_drawn)] * int(bullet_years)
        )
        if not avg_drawns:
            raise ValueError("ramp + grace + amortise + bullet produced 0 periods")
        commitments = [float(commitment)] * len(avg_drawns)
        return cls._build_annual(
            commitments, avg_drawns, start=start, upfront_fee=upfront_fee,
            floating_index=floating_index,
        )

    @classmethod
    def project_finance_milestones(
        cls,
        *,
        commitment: float,
        milestones: Sequence[tuple[float, int]],
        start: date,
        upfront_fee: float = 0.0,
        floating_index: Optional[str] = None,
    ) -> "Schedule":
        """Project-finance schedule from a list of ``(avg_drawn, n_years)`` milestones.

        Commitment is constant. Each tuple is a flat segment of the drawdown
        curve: ``(avg_drawn_for_segment, number_of_years_at_this_level)``.

        Example (same 10y project-finance shape, milestone-style)::

            Schedule.project_finance_milestones(
                commitment=100_000_000,
                milestones=[
                    (30_000_000, 1), (70_000_000, 1),
                    (100_000_000, 3),
                    (90_000_000, 1), (70_000_000, 1),
                    (50_000_000, 1), (30_000_000, 1),
                    (20_000_000, 1),
                ],
                start=date(2026, 6, 1),
                upfront_fee=1_000_000,
            )
        """
        avg_drawns: list[float] = []
        for drawn, n in milestones:
            if n <= 0:
                raise ValueError(f"milestones: n_years must be > 0, got {n}")
            avg_drawns.extend([float(drawn)] * int(n))
        if not avg_drawns:
            raise ValueError("milestones must produce at least one period")
        commitments = [float(commitment)] * len(avg_drawns)
        return cls._build_annual(
            commitments, avg_drawns, start=start, upfront_fee=upfront_fee,
            floating_index=floating_index,
        )

    # ── Internal builder ───────────────────────────────────────────

    @classmethod
    def _build_annual(
        cls,
        commitments: Sequence[float],
        avg_drawns: Sequence[float],
        *,
        start: date,
        upfront_fee: float = 0.0,
        floating_index: Optional[str] = None,
    ) -> "Schedule":
        """Assemble annual periods (dt=1.0) from parallel commitment/drawn lists.

        ``remaining_maturity_years`` is the residual contractual maturity at the
        start of each period; for an annual schedule this is ``n - i + 1`` where
        ``n`` is total periods and ``i`` is the 1-based period index.
        ``upfront_fee`` is allocated to period 1.
        """
        n = len(commitments)
        if len(avg_drawns) != n:
            raise ValueError(
                f"commitments and avg_drawns must have the same length, "
                f"got {n} vs {len(avg_drawns)}"
            )
        periods: list[Period] = []
        cursor = start
        for i in range(n):
            nxt = _add_year(cursor)
            periods.append(Period(
                index=i + 1,
                start=cursor,
                end=nxt,
                dt_years=1.0,
                commitment=float(commitments[i]),
                avg_drawn=float(avg_drawns[i]),
                remaining_maturity_years=float(n - i),
                upfront_fee=upfront_fee if i == 0 else 0.0,
                floating_index=floating_index,
            ))
            cursor = nxt
        return cls(periods=periods, day_count="Act/365F", type_="annual")


__all__ = ["Period", "Schedule"]
