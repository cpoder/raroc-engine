# Multi-period RAROC engine — specification

*Version 0.1 — 2026-05-14. Scope: Phase 1 Q1 (M0–M3), Task 1.1
of the Credenda plan (Credenda plan).*

## 1. Why this exists

`raroc_engine/calculator.py` collapses a facility into a single
annualised P&L. That works for OpenRAROC's "score this deal at
a snapshot" framing. It does not work for the App: corporate
facilities run 3 months to 10 years with drawdown ramps,
cleandowns, scheduled amortisation, floating-rate fixings, and
upfront/flat fees. Sabine (the CFO) needs to see *total cost over
the life of the facility*; Marc (the advisor) needs *per-period
RAROC* to argue for re-pricing.

This document specifies the period engine that fills that gap.
The engine code itself ships in Task 1.2 (`raroc_engine/period_engine.py`)
and Task 1.3 (`raroc_engine/aggregate.py`). Task 1.1 — this task —
locks the data model, the per-period math, the aggregates, and
the three reference fixtures the engine must reproduce within
the tolerances stated in §10.

## 2. Goals and non-goals

**Goals.**
- Deterministic per-period P&L for a single facility across a
  user-supplied schedule.
- Aggregates that map to the buyer's vocabulary: total cost,
  effective spread, weighted RAROC.
- Backwards compatibility with today's single-period calculator
  (a missing or 1-period schedule reproduces today's number to
  the cent).
- Drop-in support for the discount-rate cascade locked in D-0003.

**Non-goals (deferred to later tasks).**
- Forward-rate curve simulation / scenario shifts (Phase 2 per
  the broader Credenda roadmap).
- Multi-facility portfolio aggregation (Extension 2 — Task 1.5).
- Workflow events / renewal triggers (Extension 3 — Phase 2).
- Term-sheet PDF parsing (Phase 1 Q2, advisor pilot).

## 3. Period schema

A `Schedule` is an ordered list of `Period` rows. Each period
declares:

| Field | Type | Notes |
|---|---|---|
| `index` | int (1-based) | monotonic |
| `start` | ISO date | inclusive |
| `end` | ISO date | exclusive on the next period (and inclusive on the last) |
| `dt_years` | float | year-fraction under Act/365F (see D-0003 §3) |
| `commitment` | currency units | facility size *at the start of the period* |
| `avg_drawn` | currency units | time-weighted average drawn balance over the period |
| `remaining_maturity_years` | float | residual contractual maturity at period start, used in the Basel `b` term |
| `floating_index` | string \| null | e.g. `"3M_EURIBOR"`. `null` ⇒ fixed-rate period |
| `fixing_rate` | decimal \| null | observed/forecast rate (decimal). Forward curve fed from `curve_points` once F-09 lands |

A `Schedule` is **annual** if every `dt_years ≈ 1.0`. The Q1
fixtures are all annual; sub-annual periods are spec-compliant
but not exercised until the floating-rate engine (Phase 1 Q2).

### Drawdown schedule shapes

The engine takes whatever drawdown sequence the caller hands it.
Three common shapes the App will codify:

1. **Bullet drawdown.** `avg_drawn = commitment` for all periods.
2. **Cleandown.** `avg_drawn` steps down at one or more cleanup
   dates (e.g. RCF: 35M years 1–3, 20M years 4–5).
3. **Ramp + bullet (project finance).** `avg_drawn` increases
   period over period until fully drawn, then sits flat through
   the grace period, then amortises (linearly or per a custom
   step sequence) toward a bullet.

The engine does **not** infer drawdown from amortisation type —
the caller supplies `avg_drawn` per period explicitly. This
keeps the spec from over-fitting to one product family and
makes the test fixtures auditable.

### Amortisation types (caller convention)

The engine doesn't model amortisation type as an enum. The
caller derives `avg_drawn` and `commitment` per period from
whatever amortisation logic the term sheet uses:

- **Bullet** — commitment and drawn constant; principal repaid at
  maturity.
- **Scheduled (linear or custom)** — drawn decreases each period;
  `avg_drawn` is the time-weighted mid-period balance.
- **Revolver with cleandown** — commitment constant; `avg_drawn`
  steps down at cleandown dates.
- **Grace + amortising + bullet** — commitment constant; drawn
  ramps up, sits at peak during grace, amortises, ends on a
  residual bullet at maturity.

Future advisors will want a helper (e.g.
`Schedule.from_termsheet(...)`) that takes a structured term
sheet and produces the period rows. That helper is out of scope
for Task 1.1 — the fixtures here are written long-form.

### Floating-rate fixings

Today's calculator treats `spread` as a scalar on the drawn
balance. The period engine needs the **all-in rate** the borrower
actually pays per period:

```
all_in_rate_i = fixing_rate_i + spread          # if floating
all_in_rate_i = fixed_rate                       # if fixed
```

For the **bank revenue** calculation, only `spread × drawn`
matters (the `fixing_rate` is the bank's funding pass-through —
zero net P&L impact under matched funding). The fixing therefore
flows into:

- the **borrower-cost NPV** aggregate (§7) — the borrower sees
  the all-in rate;
- the **effective spread** aggregate (§7) — derived from spread
  cash flows, not all-in;
- nowhere in the per-period bank P&L (§6) — that uses `spread`
  only.

For Q1 fixtures we set `floating_index=null` and `fixing_rate=null`
on every period: the math reduces to the fixed-rate case and the
fixtures stay portable across the future curve cascade work.

## 4. Inputs the engine consumes

```python
PeriodEngineInput:
    deal: RAROCInput            # existing model from raroc_engine/models.py
    schedule: Schedule          # §3
    discount: DiscountSpec      # §5
    engine_config: EngineConfig # existing
```

The deal carries the static facets (rating, GRR, product type,
fees, confirmed/uncomitted flag). The schedule carries the
time-varying facets (commitment, drawn, remaining maturity,
fixings).

A `Schedule` of length 1 with `dt_years=1.0` and
`remaining_maturity_years = deal.residual_maturity / 12`
reproduces today's single-period calculator output to the cent.
This is the backwards-compatibility hinge in §9.

## 5. Discount conventions

Per D-0003 the discount rate is **configurable per calc** with
the cascade documented there. The engine consumes a
`DiscountSpec` of one of three shapes:

1. **Named curve** — e.g. `{kind: "curve", name: "eur-rfr"}`.
   Resolves through Tiers 1–5 of D-0003.
2. **Scalar** — e.g. `{kind: "scalar", rate: 0.0325}`. Useful
   for offline reproductions and for the Q1 fixtures.
3. **Schedule** — `{kind: "schedule", points: [(date, rate)]}`.
   The advisor's "use my borrower's WACC" path.

Compounding is **discrete annual** under Act/365F regardless of
currency (D-0003 §3). Period discount factor:

```
DF_i = (1 + r_i) ** (-t_i)
```

where `t_i` is years from the discount reference date (period
1 start) to the **end** of period i (end-of-period cash
convention), and `r_i` is the rate read from the discount spec
at that point.

For Q1 fixtures `r_i` is the scalar `0.0325` — i.e. the engine's
default `EngineConfig.risk_free_rate`.

## 6. Per-period P&L outputs

For each period the engine produces a `RAROCOutput`-shaped row.
The math is the existing single-period math evaluated with the
period's `avg_drawn`, `commitment`, and `remaining_maturity_years`.

### Revenue (bank)

```
revenue_i = spread × avg_drawn_i × dt_years_i
          + commit_fee × (commitment_i − avg_drawn_i) × dt_years_i
          + flat_fee_i + participation_fee_i + upfront_fee_i
```

Upfront / flat / participation fees are allocated to specific
periods via the schedule. The Q1 fixtures put the **upfront fee
entirely in period 1**, which matches the most common term-sheet
accounting and is the simplest to validate by hand.

### Cost (bank operating cost)

```
cost_i = revenue_i × cost_income_ratio
```

(`cost_income_ratio` defaults to 0.40 — see
`EngineConfig.default_cost_income_ratio`.)

### Exposure at Default

The Basel CCF rule lives in the existing repository
(`repository/exposure_calculation_coeffs.csv`). For confirmed
MLT facilities:

```
exposure_i = 0.25 × avg_drawn_i + 0.75 × commitment_i
```

(The two coefficients are CCF-on-drawn and CCF-on-undrawn
combined — the algebra in `calculator._exposure` is identical.)

### Capital requirement K (Basel III IRB)

PD comes from rating (unchanged across periods). The maturity
adjustment `b` is constant across periods (depends on PD only).
The **maturity** input to K is `remaining_maturity_years_i`:

```
R         = 0.12 × (1 + e^(−50·PD) − 2·e^(−50)) / (1 − e^(−50))
b         = (0.11852 − 0.05478 · ln(PD))²
LGD       = max(1 − GRR, LGD_floor(coll_type))
z         = √(1/(1−R)) · Φ⁻¹(PD)
          + √(R/(1−R)) · Φ⁻¹(0.999)
K_irb_i   = LGD × (Φ(z) − PD)
          × (1 + (M_i − 2.5) · b) / (1 − 1.5 · b)
K_floor_i = output_floor_pct × SA_RW(PD) / 12.5
K_i       = max(K_irb_i, K_floor_i)
```

`SA_RW(PD)` is the Basel III SA risk-weight step function in
`calculator._standardised_risk_weight`.

### Capital, expected loss, margins

```
FPE_i              = exposure_i × K_i
EL_i               = exposure_i × PD × (1 − GRR) × dt_years_i
funding_cost_i     = funding_cost_bp × exposure_i × dt_years_i
gross_margin_i     = revenue_i − cost_i − funding_cost_i
fpe_return_i       = risk_free_rate × FPE_i × dt_years_i
net_margin_i       = gross_margin_i − EL_i + fpe_return_i
```

### RAROC

```
raroc_i = (1 − tax) × (
            (revenue_i − cost_i − funding_cost_i − EL_i) / FPE_i
            + risk_free_rate
          )
```

(Matches `RAROCCalculator.calculate` step 11.)

## 7. Aggregates

### NPV of borrower cost

```
npv_borrower_cost = Σ revenue_i × DF_i
```

(The borrower's outflow per period is `revenue_i` from the bank's
POV — spread interest + commit fee + fees. The all-in rate
component, where the fixing pays through, washes out across the
borrower↔bank equality and so does not appear here. It does
appear in the all-in total-cost view we'll surface later in the
UI.)

### NPV of bank net margin

```
npv_bank_net_margin = Σ net_margin_i × DF_i
```

Tied to bank's economic capital. The wallet view (Task 1.5) sums
this across facilities.

### Effective spread (flat-bullet equivalent)

The "rate-equivalent constant spread on the actual drawn
balance":

```
effective_spread = npv_borrower_cost / Σ avg_drawn_i × dt_years_i × DF_i
```

Expressed in basis points. This collapses a complex
drawdown/cleandown/grace pattern into a single comparable
number for cross-deal comparison. Term-sheet Doctor will show
both this and the raw spread.

### FPE-weighted RAROC

```
weighted_raroc = Σ raroc_i × FPE_i × dt_years_i
               / Σ FPE_i × dt_years_i
```

This is the single number the App headlines on Module A. It is
*not* the same as "average of raroc_i" — it correctly weights
periods where the bank has more capital at risk.

## 8. Output schema

```python
PeriodEngineOutput:
    per_period: List[RAROCOutput]   # one row per period
    aggregates: dict                # the §7 fields, plus:
                                     # npv_drawn_balance,
                                     # weighted_avg_exposure,
                                     # total_revenue (undiscounted),
                                     # total_el (undiscounted)
    discount_meta: dict             # curve_status, rate_used, day_count
    engine_meta: dict               # engine_version, regime, fixture_id (optional)
```

The `curve_status` field is the D-0003 quality flag. For Q1
fixtures (scalar discount) it is always `"scalar"`.

## 9. Backwards compatibility

A schedule of length 1, `dt_years=1.0`,
`commitment = inp.average_volume`, `avg_drawn = inp.average_drawn`,
`remaining_maturity_years = inp.residual_maturity / 12.0`, with
`floating_index=null`, **must** reproduce `RAROCCalculator.calculate`
output to within 1e-12 on every field. This is the smallest
integration test for the engine and the contract OpenRAROC's
public API depends on.

## 10. Conformance tolerances

| Metric | Tolerance | Rationale |
|---|---|---|
| Per-period RAROC | 0.5 bp absolute | Norm-CDF round-trip noise + float aggregation noise dominate; 0.5 bp is well above either |
| NPV total cost | 0.1% relative | Five-period sums with discrete annual DFs accumulate <1e-4 of error from any reasonable implementation; 0.1% gives a working margin |
| Per-period FPE | 0.5% relative | Knock-on from K |
| Effective spread | 0.5 bp absolute | Same as RAROC |
| Single-period parity | 1e-12 absolute, every field | §9 contract |

A fixture **passes** if every per-period and every aggregate
metric falls within tolerance against the corresponding cell in
the Excel reference workbook. Test harness (Task 1.4) reads
the YAML, runs the engine, and asserts cell by cell.

## 11. Fixtures shipped in Task 1.1

| Fixture | File | Maturity | Drawdown shape | Purpose |
|---|---|---|---|---|
| Confirmed RCF, 5y, cleandown | `tests/fixtures/period_rcf_5y.yaml` | 5y annual | 35M y1–3, 20M y4–5 on 50M commitment | revolver + cleandown, fee mix |
| Term loan, 7y, linear amortising | `tests/fixtures/period_termloan_7y_amortising.yaml` | 7y annual | 70M day-1 drawn, 10M/yr paydown | scheduled amortisation, GRR>0 |
| Project finance, 10y, grace + amortise + bullet | `tests/fixtures/period_projfin_10y_grace.yaml` | 10y annual | 30→70→100M ramp, 100M grace y4–5, amortise y6–9, 20M bullet y10 | drawdown ramp, grace, residual bullet |

Each fixture has:
- a YAML file with `engine_config`, `deal`, `schedule`, `discount`,
  and a `expected` block holding per-period outputs and aggregates
  to the precision the engine is required to match;
- an Excel reference workbook at
  `tests/fixtures/reference_excel/<name>.xlsx` with the same
  inputs and outputs *but expressed as Excel formulas* (using
  `NORM.S.INV`, `NORM.S.DIST`, `LN`, etc.), so a banker reviewer
  can open the file and walk the math.

The fixture-math notebook
(`docs/engine/multiperiod-fixture-math.ipynb`) documents how the
expected values were derived.

## 12. Open items deferred

| ID | Item | Owner |
|---|---|---|
| F-20 | Float-rate fixing flow into the discount cascade (D-0003 Tiers 1–5). The Q1 fixtures use scalar discount, so the cascade is unexercised. | Phase 1 Q2 agent (Task 1.6) |
| F-21 | Sub-annual period fixtures (quarterly RCF, monthly trade-finance line). | Phase 1 Q2 |
| F-22 | Forward-curve scenario engine (rate shocks). | a future phase |
| F-23 | `Schedule.from_termsheet(...)` helper for the Term-Sheet Doctor input parser. | Phase 1 Q2 alongside the form UI |

## 13. References

- the broader Credenda roadmap — the product framing.
- see METHODOLOGY.md for discount conventions and floating-rate handling
  data sources.
- `raroc_engine/calculator.py` — the single-period math.
- `METHODOLOGY.md` — the Basel III IRB formula derivation.
