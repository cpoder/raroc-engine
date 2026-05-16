"""Floating-rate curve repository for the multi-period engine.

Loads daily-refresh forward-rate snapshots from ``raroc_engine/data/curves/``
and resolves fixings under the D-0003 quality cascade. The supported
currencies at launch are **EUR / GBP / USD**; the supported indices are
the ones the App's Term-Sheet Doctor sees most often (EURIBOR, €STR,
SONIA, SOFR, plus the three risk-free yield curves the discount layer
will draw from in Phase 1 Q2).

Files on disk follow ``<currency>_<curve>.csv`` (lowercase) with columns:

    as_of,tenor_days,rate

where ``as_of`` is ISO date, ``tenor_days`` is the curve point tenor in
days, and ``rate`` is decimal (``0.0325`` ⇒ 3.25 %). One file holds the
whole rolling history; the latest ``as_of`` row(s) are the published
snapshot the engine fixes against. The refresh script in
``scripts/refresh_curves.py`` appends new rows daily.

The D-0003 cascade lives in :meth:`CurveRepository.fix`:

==== =================================================== ==================
Tier Condition                                            Output status
==== =================================================== ==================
 1   Exact tenor + age ≤ 1 day                            ``fresh``
 2   Exact tenor + 1 < age ≤ 7 days                       ``stale``
 3   Tenor missing on latest snapshot, neighbours exist   ``interpolated``
 4   No curve points, or latest snapshot > 7 days old     ``scalar_fallback``
 5   Unknown index name                                   ``CurveDataUnavailable``
==== =================================================== ==================

The engine **never crashes on a missing curve** — Tier 4 returns the
caller-supplied ``fallback_rate`` (typically ``EngineConfig.risk_free_rate``)
and tags the output for the App to render a red badge.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)


# Cascade thresholds, in days. Match D-0003 §5.
FRESH_MAX_AGE_DAYS = 1
STALE_MAX_AGE_DAYS = 7


# Status flags surfaced on every output for the App's UI badge.
STATUS_FRESH = "fresh"
STATUS_STALE = "stale"
STATUS_INTERPOLATED = "interpolated"
STATUS_SCALAR_FALLBACK = "scalar_fallback"


# Order tiers by "best → worst" so callers can compare. The engine's
# rolled-up per-facility status is the worst tier seen across periods.
STATUS_PRIORITY: Dict[str, int] = {
    STATUS_FRESH: 0,
    STATUS_STALE: 1,
    STATUS_INTERPOLATED: 2,
    STATUS_SCALAR_FALLBACK: 3,
}


class CurveDataUnavailable(Exception):
    """The caller asked for a fixing on an index we don't ship a curve for.

    Caller error — not a data outage. D-0003 Tier 5 distinguishes this
    from Tier 4 (scalar fallback) so we can surface the right diagnostic.
    """


# Floating-rate fixing index → (curve file key, tenor in days).
#
# Currency is derived from the file key prefix ``eur_`` / ``gbp_`` / ``usd_``.
# Tenor mirrors the index's standard fixing tenor (e.g. 3M EURIBOR → 90).
# Yield-curve tenors are quoted in days too (5y = 1825, 10y = 3650).
INDEX_REGISTRY: Dict[str, Tuple[str, int]] = {
    # Overnight / risk-free
    "ESTR":             ("eur_estr", 1),
    "SONIA":            ("gbp_sonia", 1),
    "SOFR":             ("usd_sofr", 1),
    # EURIBOR family
    "EURIBOR_1W":       ("eur_euribor", 7),
    "EURIBOR_1M":       ("eur_euribor", 30),
    "EURIBOR_3M":       ("eur_euribor", 90),
    "EURIBOR_6M":       ("eur_euribor", 180),
    "EURIBOR_12M":      ("eur_euribor", 360),
    # Risk-free yield curves (for the discount layer in Phase 1 Q2)
    "EUR_YIELD_1Y":     ("eur_yield_curve", 360),
    "EUR_YIELD_5Y":     ("eur_yield_curve", 1825),
    "EUR_YIELD_10Y":    ("eur_yield_curve", 3650),
    "GBP_YIELD_1Y":     ("gbp_yield_curve", 360),
    "GBP_YIELD_5Y":     ("gbp_yield_curve", 1825),
    "GBP_YIELD_10Y":    ("gbp_yield_curve", 3650),
    "USD_TREASURY_1Y":  ("usd_treasury", 360),
    "USD_TREASURY_5Y":  ("usd_treasury", 1825),
    "USD_TREASURY_10Y": ("usd_treasury", 3650),
}


# ── Models ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CurvePoint:
    """One observation: (as_of, tenor_days, rate)."""

    as_of: date
    tenor_days: int
    rate: float


@dataclass(frozen=True)
class ForwardCurve:
    """All historical points for one curve file (one currency × one source).

    ``points`` is unsorted; the repository sorts on lookup. ``key`` is the
    file stem on disk (e.g. ``eur_euribor``); ``currency`` is the 3-letter
    code derived from the key prefix.
    """

    key: str
    currency: str
    points: Tuple[CurvePoint, ...]

    @property
    def latest_as_of(self) -> Optional[date]:
        if not self.points:
            return None
        return max(p.as_of for p in self.points)

    def points_at(self, snapshot: date) -> List[CurvePoint]:
        """Return all (tenor, rate) rows that share the given as_of date."""
        return sorted(
            (p for p in self.points if p.as_of == snapshot),
            key=lambda p: p.tenor_days,
        )


@dataclass(frozen=True)
class CurveFixingResult:
    """Outcome of one fixing lookup.

    ``status`` is the D-0003 cascade flag the App uses to render the
    green/yellow/red badge. ``source_curve`` / ``source_as_of`` /
    ``source_tenor_days`` describe *where the rate came from* — fed into
    the audit log so a banker reviewer can reproduce the number.
    """

    rate: float
    status: str
    source_curve: Optional[str] = None
    source_as_of: Optional[date] = None
    source_tenor_days: Optional[int] = None


# ── Repository ───────────────────────────────────────────────────────


def _default_data_dir() -> Path:
    return Path(__file__).resolve().parent / "data" / "curves"


class CurveRepository:
    """Reads forward-curve CSVs once at construction and serves fixings.

    Files in ``data_dir`` are discovered by their ``<key>.csv`` name; only
    files whose key is referenced by :data:`INDEX_REGISTRY` are loaded.
    A missing file is **not** an error — Tier 4 (scalar fallback) covers it.

    The cascade thresholds (fresh / stale) are knobs because the App's
    UI may want to tighten or loosen them later — and the unit tests
    rely on monkey-patching the cutoff to simulate ageing data without
    touching the system clock.
    """

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        index_registry: Optional[Dict[str, Tuple[str, int]]] = None,
        fresh_max_age_days: int = FRESH_MAX_AGE_DAYS,
        stale_max_age_days: int = STALE_MAX_AGE_DAYS,
    ):
        self.data_dir = Path(data_dir) if data_dir else _default_data_dir()
        self.index_registry: Dict[str, Tuple[str, int]] = dict(
            index_registry if index_registry is not None else INDEX_REGISTRY
        )
        self.fresh_max_age_days = int(fresh_max_age_days)
        self.stale_max_age_days = int(stale_max_age_days)
        self._curves: Dict[str, ForwardCurve] = {}
        self.reload()

    # ── Loading ───────────────────────────────────────────────────

    def reload(self) -> None:
        """Re-read all known curve files from disk.

        Called once at construction and exposed publicly so a long-lived
        process (e.g. the FastAPI app) can refresh its in-memory state
        after the daily cron rewrites the CSVs.
        """
        self._curves = {}
        unique_keys = {k for (k, _t) in self.index_registry.values()}
        for key in unique_keys:
            curve = self._load_curve_file(key)
            if curve is not None:
                self._curves[key] = curve

    def _load_curve_file(self, key: str) -> Optional[ForwardCurve]:
        path = self.data_dir / f"{key}.csv"
        if not path.exists():
            return None
        currency = key.split("_", 1)[0].upper()
        points: List[CurvePoint] = []
        with path.open("r", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    as_of = date.fromisoformat(row["as_of"].strip())
                    tenor_days = int(row["tenor_days"])
                    rate = float(row["rate"])
                except (KeyError, ValueError) as exc:
                    log.warning("curves: skipping bad row in %s: %r (%s)", path, row, exc)
                    continue
                points.append(CurvePoint(as_of=as_of, tenor_days=tenor_days, rate=rate))
        return ForwardCurve(key=key, currency=currency, points=tuple(points))

    # ── Lookup ────────────────────────────────────────────────────

    def has(self, index: str) -> bool:
        return index in self.index_registry

    def currency_of(self, index: str) -> str:
        if not self.has(index):
            raise CurveDataUnavailable(f"Unknown floating index: {index!r}")
        key, _ = self.index_registry[index]
        return key.split("_", 1)[0].upper()

    def fix(
        self,
        index: str,
        as_of: date,
        *,
        fallback_rate: float,
        tenor_days: Optional[int] = None,
    ) -> CurveFixingResult:
        """Resolve a fixing for ``index`` at ``as_of`` under the D-0003 cascade.

        ``as_of`` is the reference date the cascade ages data against —
        typically the calculation's valuation date or the period start.
        ``tenor_days`` overrides the index's registered tenor (handy when
        a 6M EURIBOR-tracked deal wants a 3M look-up at a specific period).
        ``fallback_rate`` is the scalar value returned at Tier 4.
        """
        if index not in self.index_registry:
            raise CurveDataUnavailable(
                f"Unknown floating index: {index!r}. "
                f"Known indices: {sorted(self.index_registry)}"
            )

        key, registered_tenor = self.index_registry[index]
        target_tenor = int(tenor_days) if tenor_days is not None else registered_tenor

        curve = self._curves.get(key)
        if curve is None or not curve.points:
            log.warning(
                "curves: no data for index %s (file %s) — scalar_fallback at %.4f",
                index, key, fallback_rate,
            )
            return CurveFixingResult(
                rate=float(fallback_rate),
                status=STATUS_SCALAR_FALLBACK,
                source_curve=key,
            )

        snapshot = curve.latest_as_of
        assert snapshot is not None  # non-empty checked above
        age = (as_of - snapshot).days

        # Reject snapshots older than the stale cutoff — D-0003 §5 does
        # not have an "ancient but exact" tier, so fall through to scalar.
        if age > self.stale_max_age_days:
            log.warning(
                "curves: latest snapshot for %s is %dd old (>%dd) — scalar_fallback",
                index, age, self.stale_max_age_days,
            )
            return CurveFixingResult(
                rate=float(fallback_rate),
                status=STATUS_SCALAR_FALLBACK,
                source_curve=key,
                source_as_of=snapshot,
            )

        same_day = curve.points_at(snapshot)
        exact = next((p for p in same_day if p.tenor_days == target_tenor), None)
        if exact is not None:
            status = STATUS_FRESH if age <= self.fresh_max_age_days else STATUS_STALE
            return CurveFixingResult(
                rate=exact.rate,
                status=status,
                source_curve=key,
                source_as_of=exact.as_of,
                source_tenor_days=exact.tenor_days,
            )

        interp = _interpolate(same_day, target_tenor)
        if interp is not None:
            log.info(
                "curves: %s tenor %dd missing on snapshot %s — interpolated to %.4f",
                index, target_tenor, snapshot.isoformat(), interp,
            )
            return CurveFixingResult(
                rate=interp,
                status=STATUS_INTERPOLATED,
                source_curve=key,
                source_as_of=snapshot,
                source_tenor_days=target_tenor,
            )

        log.warning(
            "curves: %s tenor %dd missing and no neighbours on %s — scalar_fallback",
            index, target_tenor, snapshot.isoformat(),
        )
        return CurveFixingResult(
            rate=float(fallback_rate),
            status=STATUS_SCALAR_FALLBACK,
            source_curve=key,
            source_as_of=snapshot,
        )

    # ── Inspection helpers (used by the App's diagnostic page) ────

    def list_indices(self) -> List[str]:
        return sorted(self.index_registry)

    def get_curve(self, key: str) -> Optional[ForwardCurve]:
        return self._curves.get(key)

    @property
    def loaded_curves(self) -> Dict[str, ForwardCurve]:
        return dict(self._curves)


# ── Internals ────────────────────────────────────────────────────────


def _interpolate(points: List[CurvePoint], target_tenor: int) -> Optional[float]:
    """Linear interpolation in tenor-space over a single-day snapshot.

    Returns ``None`` if ``target_tenor`` is outside the [min, max] range
    of the snapshot (no flat extrapolation — D-0003 §5 Tier 3 only fires
    when *neighbours* exist, which we read as bracketing tenors).
    """
    if len(points) < 2:
        return None
    points = sorted(points, key=lambda p: p.tenor_days)
    if target_tenor < points[0].tenor_days or target_tenor > points[-1].tenor_days:
        return None
    for left, right in zip(points, points[1:]):
        if left.tenor_days <= target_tenor <= right.tenor_days:
            span = right.tenor_days - left.tenor_days
            if span == 0:
                return left.rate
            w = (target_tenor - left.tenor_days) / span
            return left.rate + w * (right.rate - left.rate)
    return None


__all__ = [
    "CurveDataUnavailable",
    "CurveFixingResult",
    "CurvePoint",
    "CurveRepository",
    "ForwardCurve",
    "INDEX_REGISTRY",
    "FRESH_MAX_AGE_DAYS",
    "STALE_MAX_AGE_DAYS",
    "STATUS_FRESH",
    "STATUS_STALE",
    "STATUS_INTERPOLATED",
    "STATUS_SCALAR_FALLBACK",
    "STATUS_PRIORITY",
]
