# Forward curves — seed data

This directory ships **starter snapshots** of the published forward curves
the engine fixes floating rates against. The daily refresh script
(`scripts/refresh_curves.py`) is what keeps these files current in
production; the rows shipped in source are a deterministic seed so the
engine works out-of-the-box after `pip install openraroc`.

## Files

| File | Source | Tenors |
|---|---|---|
| `eur_estr.csv` | ECB €STR | 1d |
| `eur_euribor.csv` | EMMI EURIBOR (free EOD via ECB) | 7 / 30 / 90 / 180 / 360 |
| `eur_yield_curve.csv` | ECB euro-area yield curve | 360 / 730 / 1095 / 1825 / 2555 / 3650 |
| `gbp_sonia.csv` | Bank of England | 1d |
| `gbp_yield_curve.csv` | Bank of England gilt yield curve | 360 / 730 / 1095 / 1825 / 2555 / 3650 |
| `usd_sofr.csv` | NY Fed SOFR | 1d |
| `usd_treasury.csv` | Fed H.15 Treasury yields | 360 / 730 / 1095 / 1825 / 2555 / 3650 |

## Schema

Every file is plain CSV with header:

```
as_of,tenor_days,rate
```

* `as_of` — ISO date of the published snapshot (one row per
  `(as_of, tenor)` cell).
* `tenor_days` — tenor of the curve point in days. Overnight indices use
  `1`; multi-tenor curves use the calendar-day count
  (1Y ≈ 360, 5Y ≈ 1825, 10Y ≈ 3650).
* `rate` — decimal (e.g. `0.0325` = 3.25 %).

The refresh script overwrites each file with a rolling **30-day**
history; the seed shipped in source has only the last 3 days so the
package stays small.

## Lookup behaviour

Cascade summary:

1. **Fresh** — exact tenor match, ≤ 24h old.
2. **Stale** — exact tenor match, 24h < age ≤ 7d.
3. **Interpolated** — neighbouring tenors exist on the latest snapshot.
4. **Scalar fallback** — no curve data at all (or latest snapshot > 7d
   old). The engine substitutes the caller-supplied scalar
   (`EngineConfig.risk_free_rate` by default, currently 3.25 %).
5. **CurveDataUnavailable** — caller asked for an unknown index.
   Raised; not silently substituted.

The cascade is implemented in `raroc_engine.curves.CurveRepository.fix`.
