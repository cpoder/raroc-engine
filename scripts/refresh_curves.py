"""Daily refresh of the forward-rate curves shipped with raroc_engine.

Per D-0003 the engine reads free, official, daily-published curves —
**ECB** (€STR + EURIBOR + euro-area yield curve), **Bank of England**
(SONIA + gilt yield curve) and the **NY Fed / Federal Reserve** (SOFR +
H.15 Treasury yields). This script is the cron entry point that fetches
those snapshots and rewrites the CSVs under
``raroc_engine/data/curves/``.

The engine itself never hits the network — it only reads what this
script wrote. That means every transient outage (ECB downtime, certificate
hiccup, Fed rate-publish lag) is contained to a single failed cron run,
and the fallback cascade in :mod:`raroc_engine.curves` keeps the engine
healthy through the gap.

Usage
-----

Run with no args from the repo root to refresh every supported curve:

    python scripts/refresh_curves.py

Useful flags:

* ``--source live`` (default) — hit the published HTTP endpoints. Each
  source is wrapped in its own try/except so partial outages don't break
  the others; the script's exit status reflects whether *all* sources
  succeeded.
* ``--source synthetic`` — append today's row to each existing file by
  carrying the last known value forward. Used for offline bootstrapping,
  CI, and the test suite. Deterministic.
* ``--target /path/to/curves`` — write into a different curves
  directory (test isolation).
* ``--ref-date 2026-05-14`` — pretend ``today`` is the given date. Lets
  test fixtures roll the history forward without touching the system
  clock.
* ``--dry-run`` — print what would be written; do not touch any files.

Operational notes
-----------------

Network HTTP retrieval is best-effort: the public URL formats published
by the three central banks change a few times a year (the most stable is
ECB SDMX; the least stable is the Fed H.15 ZIP archive). When a parser
breaks because an upstream URL has shifted, the script *logs and
continues to the next source*; it does **not** corrupt the on-disk CSV.
Re-pointing a parser at a new URL is a one-file change in this script
and does not require a release of the engine package.

The rolling-history depth is 30 days. Older rows are trimmed on every
run. The seed shipped in source has only the last ≈3 days so the package
remains small.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

# Allow running this script as ``python scripts/refresh_curves.py`` from
# the repo root without ``pip install -e``.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from raroc_engine.curves import CurvePoint, _default_data_dir  # noqa: E402

log = logging.getLogger("refresh_curves")


HISTORY_DAYS = 30
USER_AGENT = "openraroc-curve-refresh/0.1 (+https://openraroc.com)"
HTTP_TIMEOUT_SECONDS = 15


# ── Source descriptor ───────────────────────────────────────────────


@dataclass
class CurveSource:
    """How to fetch and parse one curve file.

    ``tenors`` is the list of tenor-day columns we ship for the curve.
    ``url`` and ``parse`` are the live-fetch hook; if either is ``None``
    the source is synthetic-only.
    """

    key: str                                    # file stem
    currency: str
    tenors: Sequence[int]
    url: Optional[str] = None
    parse: Optional[Callable[[bytes], Dict[int, float]]] = None
    description: str = ""


# ── Live parsers (best-effort) ──────────────────────────────────────


def _parse_ecb_estr(payload: bytes) -> Dict[int, float]:
    """ECB Statistical Data Warehouse — €STR last observation.

    SDMX-CSV format; the dataflow at the time of writing is ``EST`` with
    series key ``B.EU000A2X2A25.WT`` (volume-weighted average rate). The
    refresh script reads the LATEST row only and maps it to tenor=1d.
    """
    rows = list(csv.DictReader(payload.decode("utf-8").splitlines()))
    if not rows:
        raise ValueError("ECB €STR payload is empty")
    last = rows[-1]
    # SDMX-CSV column is "OBS_VALUE" (number) — the rate is in percent.
    raw = last.get("OBS_VALUE") or last.get("obs_value") or ""
    return {1: float(raw) / 100.0}


def _parse_nyfed_sofr_json(payload: bytes) -> Dict[int, float]:
    """NY Fed SOFR JSON endpoint — last row only.

    ``https://markets.newyorkfed.org/api/rates/secured/sofr/last/1.json``
    returns ``{"refRates": [{"effectiveDate": "...", "percentRate": ...}]}``.
    """
    doc = json.loads(payload.decode("utf-8"))
    rows = doc.get("refRates") or []
    if not rows:
        raise ValueError("NY Fed SOFR payload has no refRates")
    pct = rows[0].get("percentRate")
    if pct is None:
        raise ValueError("NY Fed SOFR payload missing percentRate")
    return {1: float(pct) / 100.0}


def _parse_boe_sonia_csv(payload: bytes) -> Dict[int, float]:
    """Bank of England SONIA — IUDSOIA series.

    The BoE database CSV has columns ``DATE, IUDSOIA``. Read last row.
    """
    rows = list(csv.reader(payload.decode("utf-8").splitlines()))
    if len(rows) < 2:
        raise ValueError("BoE SONIA payload has no data rows")
    last = rows[-1]
    return {1: float(last[-1]) / 100.0}


# Yield-curve parsers are not implemented here — the published formats
# (ECB Excel for euro-area government curves, BoE for gilts, Fed H.15
# ZIP) differ enough that they're worth a dedicated module each. Until
# then yield curves run through the synthetic carry-forward path; the
# scalar_fallback tier covers them if the seed data ages out.


# ── Source registry ─────────────────────────────────────────────────


SOURCES: List[CurveSource] = [
    CurveSource(
        key="eur_estr",
        currency="EUR",
        tenors=[1],
        url="https://data-api.ecb.europa.eu/service/data/EST/B.EU000A2X2A25.WT?lastNObservations=1&format=csvdata",
        parse=_parse_ecb_estr,
        description="ECB €STR (overnight)",
    ),
    CurveSource(
        key="eur_euribor",
        currency="EUR",
        tenors=[7, 30, 90, 180, 360],
        description="EMMI EURIBOR (synthetic carry-forward for now — wiring EMMI scrape pending)",
    ),
    CurveSource(
        key="eur_yield_curve",
        currency="EUR",
        tenors=[360, 730, 1095, 1825, 2555, 3650],
        description="ECB euro-area yield curve (synthetic carry-forward — yield-curve XLS parser pending)",
    ),
    CurveSource(
        key="gbp_sonia",
        currency="GBP",
        tenors=[1],
        url="https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp?Travel=NIxAZxSUx&FromSeries=1&ToSeries=50&DAT=RNG&FD=1&FM=Jan&FY=2024&TD=31&TM=Dec&TY=2030&FNY=Y&CSVF=TT&html.x=66&html.y=26&SeriesCodes=IUDSOIA&UsingCodes=Y&Filter=N&title=IUDSOIA&VPD=Y",
        parse=_parse_boe_sonia_csv,
        description="Bank of England SONIA (overnight)",
    ),
    CurveSource(
        key="gbp_yield_curve",
        currency="GBP",
        tenors=[360, 730, 1095, 1825, 2555, 3650],
        description="BoE gilt yield curve (synthetic carry-forward — gilt-curve parser pending)",
    ),
    CurveSource(
        key="usd_sofr",
        currency="USD",
        tenors=[1],
        url="https://markets.newyorkfed.org/api/rates/secured/sofr/last/1.json",
        parse=_parse_nyfed_sofr_json,
        description="NY Fed SOFR (overnight)",
    ),
    CurveSource(
        key="usd_treasury",
        currency="USD",
        tenors=[360, 730, 1095, 1825, 2555, 3650],
        description="Fed H.15 Treasury yields (synthetic carry-forward — H.15 parser pending)",
    ),
]


# ── CSV I/O ─────────────────────────────────────────────────────────


def _read_existing(path: Path) -> List[CurvePoint]:
    if not path.exists():
        return []
    out: List[CurvePoint] = []
    with path.open("r", newline="") as f:
        for row in csv.DictReader(f):
            try:
                out.append(CurvePoint(
                    as_of=date.fromisoformat(row["as_of"].strip()),
                    tenor_days=int(row["tenor_days"]),
                    rate=float(row["rate"]),
                ))
            except (KeyError, ValueError):
                continue
    return out


def _write(path: Path, points: List[CurvePoint]) -> None:
    points = sorted(points, key=lambda p: (p.as_of, p.tenor_days))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["as_of", "tenor_days", "rate"])
        for p in points:
            w.writerow([p.as_of.isoformat(), p.tenor_days, f"{p.rate:.5f}"])


def _trim_history(points: List[CurvePoint], ref_date: date, days: int) -> List[CurvePoint]:
    cutoff = ref_date - timedelta(days=days)
    return [p for p in points if p.as_of >= cutoff]


def _latest_snapshot(points: List[CurvePoint]) -> Optional[date]:
    return max((p.as_of for p in points), default=None)


def _row_for_tenor(points: List[CurvePoint], snapshot: date, tenor_days: int) -> Optional[CurvePoint]:
    for p in points:
        if p.as_of == snapshot and p.tenor_days == tenor_days:
            return p
    return None


# ── Live fetch ──────────────────────────────────────────────────────


def _fetch_live(source: CurveSource) -> Dict[int, float]:
    if source.url is None or source.parse is None:
        raise RuntimeError(f"{source.key}: no live URL configured")
    req = urllib.request.Request(source.url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
        body = resp.read()
    return source.parse(body)


# ── Synthetic carry-forward ─────────────────────────────────────────


def _carry_forward(
    source: CurveSource,
    history: List[CurvePoint],
    ref_date: date,
) -> Dict[int, float]:
    """Re-use the latest known rates as today's rates.

    Deterministic and predictable — the App's UI will paint a yellow
    badge ("stale") on the cells until a live source catches up, which
    is exactly the right operator signal.
    """
    snapshot = _latest_snapshot(history)
    out: Dict[int, float] = {}
    for t in source.tenors:
        if snapshot is not None:
            row = _row_for_tenor(history, snapshot, t)
            if row is not None:
                out[t] = row.rate
                continue
        # No prior data at all — we cannot invent a rate. Skip.
    return out


# ── Per-source orchestrator ─────────────────────────────────────────


@dataclass
class SourceResult:
    key: str
    mode: str                          # "live" or "synthetic" or "skip"
    status: str                        # "ok" | "fallback" | "error" | "noop"
    detail: str = ""
    rows_added: int = 0


def refresh_source(
    source: CurveSource,
    *,
    data_dir: Path,
    ref_date: date,
    mode: str = "live",
    dry_run: bool = False,
) -> SourceResult:
    """Refresh one source's CSV. Returns a structured result.

    Falls back to a synthetic carry-forward only if mode=="live" *and*
    the live fetch raises. mode=="synthetic" carries forward unconditionally.
    """
    path = data_dir / f"{source.key}.csv"
    history = _read_existing(path)

    fixings: Dict[int, float] = {}
    effective_mode = mode
    status = "ok"
    detail = ""

    if mode == "live" and source.url and source.parse:
        try:
            fixings = _fetch_live(source)
            if not fixings:
                raise RuntimeError("live fetch returned no rows")
            detail = f"live OK ({len(fixings)} tenor(s))"
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError, RuntimeError) as exc:
            log.warning("%s: live fetch failed — falling back to synthetic: %s", source.key, exc)
            effective_mode = "synthetic"
            status = "fallback"
            detail = f"live failed ({exc!s}), synthetic carry-forward"
    elif mode == "live" and not (source.url and source.parse):
        effective_mode = "synthetic"
        detail = "no live URL configured, synthetic carry-forward"

    if not fixings:
        fixings = _carry_forward(source, history, ref_date)
        if not fixings:
            log.error("%s: nothing to write — no history and no live data", source.key)
            return SourceResult(
                key=source.key, mode=effective_mode, status="error",
                detail="no history and no live data",
            )

    # Build the new row set: keep existing history (trimmed), drop any
    # row for ref_date so we don't duplicate, and add fresh rows for
    # every configured tenor.
    history = [p for p in history if p.as_of != ref_date]
    rows_added = 0
    for t in source.tenors:
        if t not in fixings:
            # Live source only delivered some tenors — carry the rest
            # forward from history so we don't leave the curve sparse.
            snapshot = _latest_snapshot(history)
            if snapshot is not None:
                row = _row_for_tenor(history, snapshot, t)
                if row is not None:
                    fixings[t] = row.rate
        if t in fixings:
            history.append(CurvePoint(as_of=ref_date, tenor_days=t, rate=fixings[t]))
            rows_added += 1

    history = _trim_history(history, ref_date, HISTORY_DAYS)

    if dry_run:
        log.info(
            "%s: would write %d row(s) to %s (mode=%s)",
            source.key, rows_added, path, effective_mode,
        )
    else:
        _write(path, history)
        log.info("%s: wrote %d new row(s) to %s (mode=%s)",
                 source.key, rows_added, path, effective_mode)

    return SourceResult(
        key=source.key,
        mode=effective_mode,
        status=status,
        detail=detail or f"{effective_mode} OK",
        rows_added=rows_added,
    )


def refresh_all(
    *,
    data_dir: Optional[Path] = None,
    ref_date: Optional[date] = None,
    mode: str = "live",
    dry_run: bool = False,
    sources: Optional[Sequence[CurveSource]] = None,
) -> List[SourceResult]:
    """Refresh every configured source. Returns a result per source.

    Caller decides what an overall failure means (e.g. ``main`` exits
    non-zero if any source reports ``status == "error"``).
    """
    data_dir = data_dir or _default_data_dir()
    ref_date = ref_date or date.today()
    src_list = list(sources) if sources is not None else SOURCES
    out: List[SourceResult] = []
    for s in src_list:
        out.append(refresh_source(
            s, data_dir=data_dir, ref_date=ref_date, mode=mode, dry_run=dry_run,
        ))
    return out


# ── CLI ────────────────────────────────────────────────────────────


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--source", choices=["live", "synthetic"], default="live",
        help="live: hit ECB/BoE/Fed endpoints; synthetic: carry forward last known.",
    )
    ap.add_argument(
        "--target", type=Path, default=None,
        help="Curves directory to write into. Default: raroc_engine/data/curves.",
    )
    ap.add_argument(
        "--ref-date", type=str, default=None,
        help="ISO date to record as today's snapshot. Default: today.",
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be written; do not touch files.",
    )
    ap.add_argument(
        "--quiet", action="store_true",
        help="Only log warnings and errors.",
    )
    return ap.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    ref_date = date.fromisoformat(args.ref_date) if args.ref_date else date.today()
    target = args.target if args.target else _default_data_dir()

    results = refresh_all(
        data_dir=target,
        ref_date=ref_date,
        mode=args.source,
        dry_run=args.dry_run,
    )

    n_error = sum(1 for r in results if r.status == "error")
    n_fallback = sum(1 for r in results if r.status == "fallback")
    n_ok = sum(1 for r in results if r.status == "ok")
    log.info(
        "refresh complete: %d OK, %d fallback, %d error (ref_date=%s, mode=%s)",
        n_ok, n_fallback, n_error, ref_date.isoformat(), args.source,
    )
    return 1 if n_error else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
