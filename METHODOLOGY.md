# RAROC Calculation Methodology

## Overview

RAROC (Risk-Adjusted Return on Capital) measures the risk-adjusted profitability of a banking product. It answers: *"Does this deal generate enough return to justify the capital the bank must hold against it?"*

Banks use RAROC as their primary pricing and credit decision metric. A deal that earns a 15% RAROC is more attractive than one earning 8%, and both are measured against the bank's hurdle rate (typically 10-15%).

For a corporate treasurer, understanding RAROC means understanding how your bank evaluates your facilities -- and why different banks offer different pricing for the same deal.

---

## The RAROC Formula

```
                        Revenue - Cost - Funding Cost - Expected Loss
RAROC = (1 - Tax) ×  [ ──────────────────────────────────────────────── + Risk-Free Rate ]
                                    Economic Capital (FPE)
```

The rest of this document explains each component in detail.

---

## 1. Revenue

Revenue is the total annual income the bank earns from the facility:

```
Revenue = Spread × Average Drawn
        + Commitment Fee × (Average Volume - Average Drawn)
        + Flat Fee + Participation Fee + Upfront Fee
```

| Component | Description |
|-----------|-------------|
| **Spread** | Annual margin over reference rate (e.g., 150bp over EURIBOR) |
| **Commitment fee** | Annual fee on the undrawn portion of committed facilities |
| **Flat fee** | Fixed annual fee |
| **Participation fee** | One-time participation fee |
| **Upfront fee** | One-time upfront fee |

**Example:** A EUR 30M committed facility, EUR 25M average drawn, 150bp spread, 25bp commitment fee:
- Spread income: 25,000,000 × 0.015 = EUR 375,000
- Commitment fee: 5,000,000 × 0.0025 = EUR 12,500
- **Total revenue: EUR 387,500**

---

## 2. Cost

The bank's operating cost to manage the facility. Calculated as a percentage of revenue:

| Product Category | Cost/Income Ratio |
|-----------------|-------------------|
| Credit facilities (loans, revolvers, guarantees) | 40% |
| Capital markets | 60% |
| Derivatives (swaps, options, forwards) | 75% |
| Cash management | 80% |

**Example:** Revenue of EUR 387,500 on a term loan → Cost = 387,500 × 0.40 = **EUR 155,000**

When comparing across banks, each bank's actual cost-to-income ratio (from their annual report) is used instead.

---

## 3. Exposure at Default (EAD)

EAD is the bank's expected credit exposure if the borrower defaults. It accounts for the fact that committed but undrawn facilities may be drawn down before default.

```
EAD = CAD × Average Drawn + CA × Average Volume + CG × Collateral Value
```

The coefficients depend on the product type and whether the facility is committed:

### Committed facilities

| Product | CAD | CA | CG |
|---------|-----|-----|-----|
| Term loans / revolving credit | 0.25 | 0.75 | -1 |
| Financial guarantees | 0.25 | 0.75 | -1 |
| Technical guarantees | 0.125 | 0.375 | -1 |
| Import documentary credits | 0.125 | 0.375 | -1 |
| Cautions (sureties) | 0.05 | 0.15 | -1 |

### Uncommitted facilities

| Product | CAD | CA | CG |
|---------|-----|-----|-----|
| Term loans / revolving credit | 1.0 | 0 | -1 |
| Financial guarantees | 1.0 | 0 | -1 |
| Technical guarantees | 0.5 | 0 | -1 |
| Cautions (sureties) | 0.2 | 0 | -1 |

The CG coefficient of -1 means collateral reduces exposure.

**Example:** EUR 30M committed term loan, EUR 25M average drawn, no collateral:
- EAD = 0.25 × 25,000,000 + 0.75 × 30,000,000 = **EUR 28,750,000**

---

## 4. Probability of Default (PD)

PD is the likelihood that the borrower defaults within one year. It is derived from the borrower's credit rating using S&P Global long-run average corporate default rates.

| Moody's | S&P / Fitch | PD |
|---------|------------|-----|
| Aaa | AAA | 0.01% |
| Aa1 | AA+ | 0.01% |
| Aa2 | AA | 0.01% |
| Aa3 | AA- | 0.03% |
| A1 | A+ | 0.04% |
| A2 | A | 0.05% |
| A3 | A- | 0.07% |
| Baa1 | BBB+ | 0.10% |
| Baa2 | BBB | 0.16% |
| Baa3 | BBB- | 0.24% |
| Ba1 | BB+ | 0.38% |
| Ba2 | BB | 0.63% |
| Ba3 | BB- | 1.11% |
| B1 | B+ | 2.14% |
| B2 | B | 3.82% |
| B3 | B- | 7.12% |
| Caa1 | CCC+ | 15.00% |

The engine accepts ratings in any scale (Moody's, S&P, or Fitch) and normalizes automatically.

### PD Floor (Basel III)

Under Basel III, PD is floored at **5 basis points** (0.05%). Even a AAA-rated borrower cannot have a PD below this floor.

### Guarantee Adjustment

When the facility is partially guaranteed (GRR > 0), the effective PD used in the capital formula is reduced:

```
PD (adjusted) = PD × (1 - GRR)
```

A 50% guarantee recovery rate halves the effective PD.

---

## 5. Loss Given Default (LGD)

LGD is the percentage of exposure the bank expects to lose if the borrower defaults:

```
LGD = 1 - GRR
```

Where GRR (Global Guarantee Recovery Rate) represents the percentage of the exposure covered by guarantees or collateral.

### LGD Floors (Basel III)

Basel III imposes minimum LGD values that cannot be breached regardless of collateral:

| Collateral Type | LGD Floor |
|----------------|-----------|
| Unsecured (no collateral) | 25% |
| Receivables / Real estate | 10% |
| Financial instruments | 0% |

**Example:** A facility with 80% GRR → LGD = 1 - 0.80 = 0.20 → floored at **25%** (unsecured floor applies unless financial collateral).

---

## 6. Risk Weight (Capital Requirement K)

This is the core of the Basel IRB framework. The capital requirement K determines how much equity the bank must hold against the exposure.

### 6.1 Asset Correlation (R)

Asset correlation measures how much the borrower's default risk depends on the overall economy:

```
R = 0.12 × [1 + exp(-50 × PD) - 2 × exp(-50)] / [1 - exp(-50)]
```

Higher-rated borrowers have higher correlation (their defaults are more systemic). Lower-rated borrowers default more idiosyncratically.

### 6.2 Maturity Adjustment (b)

Longer maturities create more risk because there is more time for the borrower's credit quality to deteriorate:

```
b = (0.11852 - 0.05478 × ln(PD))²
```

### 6.3 Capital Requirement (K)

The IRB formula calculates the capital charge at the 99.9th percentile of the loss distribution:

```
z = √(1/(1-R)) × N⁻¹(PD) + √(R/(1-R)) × N⁻¹(0.999)

K = LGD × [N(z) - PD] × [1 + (M - 2.5) × b] / (1 - 1.5 × b)
```

Where:
- N⁻¹ = inverse cumulative normal distribution
- N = cumulative normal distribution
- M = maturity in years
- 0.999 = Basel 99.9% confidence level

**Maturity effect:** The formula is calibrated to M = 2.5 years. Shorter maturities reduce K; longer maturities increase it.

### 6.4 Basel III Output Floor

Under Basel III (CRR3), the IRB capital requirement cannot fall below a percentage of the Standardised Approach risk weight:

```
K = max(K, Output Floor % × SA Risk Weight / 12.5)
```

**Standardised risk weights for corporates:**

| PD Range | SA Risk Weight |
|----------|---------------|
| PD ≤ 0.05% | 20% |
| 0.05% < PD ≤ 0.15% | 50% |
| 0.15% < PD ≤ 0.75% | 75% |
| 0.75% < PD ≤ 3.0% | 100% |
| PD > 3.0% | 150% |

**Output floor phase-in:**

| Year | Floor |
|------|-------|
| 2025 | 50.0% |
| 2026 | 55.0% |
| 2027 | 60.0% |
| 2028 | 65.0% |
| 2029 | 70.0% |
| 2030+ | 72.5% |

---

## 7. Economic Capital (Funds Put at Equity)

Economic capital is the equity the bank must allocate against the facility:

```
FPE = EAD × K
```

This is the denominator of the RAROC calculation -- the "capital at risk" that must earn its return.

**Example:** EAD of EUR 28.75M, K = 8% → FPE = 28,750,000 × 0.08 = **EUR 2,300,000**

---

## 8. Expected Loss

The average annual loss the bank anticipates:

```
Expected Loss = EAD × PD (adjusted)
```

Expected loss is a cost of doing business, not a risk. It is deducted from revenue before calculating the return on risk capital.

---

## 9. Funding Cost

The bank's cost of borrowing the funds it lends:

```
Funding Cost = Funding Spread × EAD
```

The funding spread varies by bank (typically 10-25bp above the interbank rate) and reflects the bank's own credit quality and funding structure.

---

## 10. RAROC Calculation

Putting it all together:

```
                        Revenue - Cost - Funding Cost - Expected Loss
RAROC = (1 - Tax) ×  [ ──────────────────────────────────────────────── + Risk-Free Rate ]
                                           FPE
```

The risk-free rate is added because the bank earns a return on the equity capital it holds (currently 3.25%, EUR mid-swap rate).

**Full worked example:**

| Component | Value |
|-----------|-------|
| Facility | EUR 30M committed term loan, EUR 25M drawn |
| Rating | BBB+ (PD = 0.10%) |
| Spread | 150bp |
| Commitment fee | 25bp on undrawn |
| Maturity | 5 years |
| GRR | 40% |
| | |
| Revenue | EUR 387,500 |
| Cost (40%) | EUR 155,000 |
| EAD | EUR 28,750,000 |
| PD (adjusted) | 0.10% × (1 - 0.40) = 0.06% |
| LGD | max(1 - 0.40, 0.25) = 0.60 |
| K (risk weight) | ~4.8% |
| FPE | EUR 1,380,000 |
| Expected loss | EUR 17,250 |
| Funding cost (15bp) | EUR 43,125 |
| | |
| Numerator | 387,500 - 155,000 - 43,125 - 17,250 = EUR 172,125 |
| Return on capital | 172,125 / 1,380,000 = 12.47% |
| + Risk-free rate | 12.47% + 3.25% = 15.72% |
| After tax (25%) | 15.72% × (1 - 0.25) = **11.79%** |

RAROC of 11.79% is just below a 12% hurdle rate -- the bank might ask for a slightly higher spread or more collateral.

---

## 11. Reverse Solver

The engine can solve backwards:

### Minimum Spread
*"What is the lowest spread the bank will accept?"*

Given a target RAROC (e.g., 12%), the solver finds the exact spread that achieves it. Uses Brent's root-finding method.

### Minimum Collateral (GRR)
*"How much collateral do I need to make this deal work?"*

Given a target RAROC, the solver finds the minimum guarantee recovery rate needed.

---

## 12. Bank Comparison

Different banks have different:
- **Cost-to-income ratios** (40-76%) -- operational efficiency
- **Tax rates** (22-34%) -- jurisdiction and structure
- **Funding costs** (10-25bp) -- credit quality and deposit base
- **LGD estimates** (14-46%) -- internal model calibration (A-IRB banks)

This means the same deal yields different RAROC values at different banks. A EUR 25M BBB+ loan might show RAROC of 12.3% at HSBC but only 8.5% at Deutsche Bank -- explaining the 55bp spread difference.

The engine uses actual parameters from each bank's Pillar 3 CR6 regulatory disclosures to make these comparisons real, not theoretical.

---

## 13. IRB Approaches

Banks use different regulatory approaches for their corporate portfolios:

| Approach | PD Source | LGD Source | Banks |
|----------|-----------|------------|-------|
| **A-IRB** (Advanced) | Bank's internal model | Bank's internal model | Most large European & US banks |
| **F-IRB** (Foundation) | Bank's internal model | Regulatory fixed (45% unsecured) | Some banks, Chinese banks |
| **Mixed** | Varies by portfolio segment | Varies | Banks transitioning or with multiple portfolios |

In the engine, the LGD values for each bank already reflect their actual approach -- A-IRB banks show their internal LGD estimates; F-IRB banks show regulatory LGDs.

---

## 14. Regulatory References

The formulas implemented follow:

- **BIS CRE31** -- IRB approach: risk weight functions (asset correlation, capital requirement)
- **BIS CRE32** -- IRB approach: risk quantification (PD, LGD, EAD requirements)
- **BIS d424** -- Basel III standardised approach (output floor risk weights)
- **CRR3 (EU 2024/1623)** -- European implementation of Basel III finalization
- **S&P Global** -- Long-run average corporate default rates (PD calibration)

---

## 15. Configuration Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| Risk-free rate | 3.25% | EUR mid-swap rate |
| Bank tax rate | 25% | Effective corporate tax rate |
| Funding cost | 0bp | Bank's marginal funding spread |
| Output floor | 55% | Basel III floor (2026 phase-in) |
| PD floor | 5bp | Minimum PD (Basel III) |
| LGD floor (unsecured) | 25% | Minimum LGD without collateral |
| LGD floor (secured) | 10% | Minimum LGD with receivables/RE |
| Target RAROC | 12% | Bank's hurdle rate |

All parameters are configurable per calculation.

---

## 16. Multi-Period Engine (v2.0)

Sections 1–15 above describe the **single-period** engine: one row of inputs (commitment, drawn, spread, rating, residual maturity, GRR) produces one RAROC figure that summarises the deal's profitability *at a single point in time*.

Real facilities aren't single periods. A 7-year amortising loan repays principal every year, so its FPE shrinks over time. A 5-year RCF "cleans down" mid-life as the borrower's working-capital needs taper. A project-finance facility ramps up, sits in grace, amortises, then leaves a bullet. The single-period engine cannot model any of this — it sees only the day-1 snapshot.

The **multi-period engine** (`raroc_engine.period_engine.PeriodEngine`, added in v2.0) walks a `Schedule` of `Period` rows and runs the single-period math on each one, then aggregates the results into the headline metrics a corporate treasurer or advisor actually needs: NPV of borrower cost, NPV of bank net margin, effective spread, capital-weighted RAROC.

### 16.1 Schedule and Period

```python
from raroc_engine import Schedule, Period, PeriodEngine

schedule = Schedule.scheduled_amortising_term_loan(
    initial_drawn=70_000_000,
    total_years=7,
    start=date(2026, 1, 1),
    upfront_fee=350_000,
)
```

A `Schedule` is the time-varying companion to a `RAROCInput`. The deal carries the **static** facets (rating, product, spread, commit fee, GRR). The schedule carries the **time-varying** facets per period:

| Field | Meaning |
|-------|---------|
| `index` | 1-based period number |
| `start`, `end` | Period boundaries (`date` objects) |
| `dt_years` | Length of the period in years (e.g. 1.0 annual, 0.25 quarterly) |
| `commitment` | Committed amount during the period |
| `avg_drawn` | Average drawn balance during the period |
| `remaining_maturity_years` | Contractual residual maturity at period start |
| `upfront_fee`, `flat_fee`, `participation_fee` | Period-allocated fees |
| `floating_index`, `fixing_rate` | Optional curve index + fixing for floating periods |

### 16.2 Schedule shapes

Five constructors cover the common term-sheet shapes:

| Shape | Use case |
|-------|----------|
| `Schedule.single_period(...)` | Length-1 schedule with `dt=1.0` — back-compat hinge |
| `Schedule.from_raroc_input(inp, start=...)` | Auto-bridge from an existing `RAROCInput` |
| `Schedule.bullet_rcf_with_cleandown(commitment, drawn_levels, ...)` | RCF — constant commit, stepped drawn |
| `Schedule.scheduled_amortising_term_loan(initial_drawn, total_years, ...)` | Linear-amortising term loan |
| `Schedule.drawdown_ramp_with_grace(...)` | Project-finance shape: ramp → grace → amortise → bullet |
| `Schedule.project_finance_milestones(commitment, milestones, ...)` | Generic `[(avg_drawn, n_years), …]` |

All shapes funnel through `Schedule._build_annual` which fills `remaining_maturity_years = (n - i + 1)` for an annual schedule.

### 16.3 The per-period loop

For each period the engine:

1. Builds a synthetic `RAROCInput` carrying the period's `commitment` (as `average_volume`), `avg_drawn` (as `average_drawn`), and `remaining_maturity_years × 12` (as `residual_maturity`), copying static deal fields verbatim.
2. Calls `RAROCCalculator.calculate(period_input)` — the same single-period code path as v1 — to get the baseline `RAROCOutput`.
3. **Rescales** the dt-dependent fields by `period.dt_years` (see §16.4).
4. Computes the period's `RAROC` from the rescaled numerator + the baseline FPE.
5. Records the residual maturity, the discount factor `DF = (1 + r)^(-t_end)`, and the PVs the aggregates need.

This construction guarantees the **back-compat contract** by construction: a single-period schedule with `dt = 1.0` reproduces the v1 `RAROCCalculator.calculate` output to 1e-12 on every field (spec §9; test: `tests/test_period_engine.py::test_single_period_parity`).

### 16.4 dt-scaling convention

Some quantities are **accruals** that scale linearly with the period length (a half-year accrues half the revenue). Others are **bookings** that don't scale (an upfront fee of EUR 200k is paid once regardless of period length). The engine handles them differently:

| Quantity | Scales by `dt`? | Why |
|----------|-----------------|-----|
| Spread × drawn (interest) | ✅ | Accrual: 6 months of spread = ½ × annual amount |
| Commitment fee × undrawn | ✅ | Accrual on the undrawn |
| Funding cost (`funding_cost_bp × EAD`) | ✅ | Bank's marginal funding accrues over time |
| Expected loss (`EAD × PD_basel`) | ✅ | Annualised loss expectation, prorated |
| FPE return (`r × FPE`) | ✅ | Return on capital held during the period |
| `upfront_fee`, `flat_fee`, `participation_fee` | ❌ | Bookings paid at term-sheet level, not accruals |
| FPE itself (`EAD × K`) | ❌ | Stock measurement, not a flow |
| Risk weight K, asset correlation R, maturity adj b | ❌ | Calibration parameters, not flows |

The cost-to-income ratio is **preserved** from the single-period calculator's resolved value: `cost_period = revenue_period × (calc.cost / calc.revenue)`. This means a product-specific override (e.g. 75% for derivatives) carries through the multi-period loop unchanged.

### 16.5 Aggregates (§7 of the spec)

After walking the schedule the engine builds wallet-grade aggregates (`raroc_engine.aggregate.FacilityAggregates`):

```
npv_borrower_cost     = Σ revenue_i × DF_i        (PV of what the borrower pays the bank)
npv_bank_net_margin   = Σ net_margin_i × DF_i     (PV of the bank's after-cost return)
npv_bank_costs        = Σ (cost_i + funding_i + EL_i) × DF_i
npv_drawn_balance     = Σ avg_drawn_i × dt_i × DF_i

total_revenue_undisc  = Σ revenue_i
total_el_undisc       = Σ el_i

effective_spread      = npv_borrower_cost / npv_drawn_balance
                       (the flat constant spread on a bullet facility
                        economically equivalent to the schedule)

avg_raroc             = Σ raroc_i × dt_i / Σ dt_i        (time-weighted)
capital_weighted_raroc = Σ raroc_i × fpe_i × dt_i
                       / Σ fpe_i × dt_i                 (= spec §7 fpe_weighted_raroc)

fpe_years             = Σ fpe_i × dt_i                  (wallet capital-usage proxy)
```

The **effective spread** is the headline number for cross-deal comparison: it tells a treasurer "this 5y RCF with cleandown costs you the same as a 182.2bp flat-spread bullet loan would" — useful when banks quote different shapes on the same underlying credit.

The **capital-weighted RAROC** matches what the bank's relationship banker actually sees: the periods that consume the most capital × time dominate the average.

### 16.6 Tolerances

| Metric | Tolerance |
|--------|-----------|
| Per-period RAROC | 0.5 bp absolute |
| NPV totals | 0.1% relative |
| Effective spread | 0.5 bp absolute |
| Single-period parity (dt=1.0 length-1 schedule vs v1 calculator) | 1e-12 absolute |

See `docs/engine/multiperiod-spec.md` §10 and the three golden fixtures under `tests/fixtures/period_*.yaml`.

---

## 17. Discount-Rate Convention (D-0003)

The multi-period engine discounts every period's cash flow to present value with a per-period factor `DF_i = (1 + r_i)^(-t_end_i)`, Act/365F discrete annual. The discount rate `r_i` comes from a `DiscountSpec`:

```python
from raroc_engine import DiscountSpec
discount = DiscountSpec(kind="scalar", rate=0.0325)
```

### 17.1 Three shapes

| `kind` | Behavior | When to use |
|--------|----------|-------------|
| `scalar` | A single rate for every period | Default. Engine config's `risk_free_rate` (3.25% EUR mid-swap by default). |
| `curve` | Look up by curve name against a `CurveRepository` | Risk-free curve in the deal currency (EUR/USD/GBP) — the recommended default in production. |
| `schedule` | `[(date, rate), …]` linearly interpolated | Advisor flows: discount a corporate borrower's facilities at *their own WACC* curve instead of risk-free. |

### 17.2 Floating-rate fallback cascade

When a period carries a `floating_index` (e.g. `EURIBOR_3M`, `SOFR`, `SONIA`) but no `fixing_rate`, the engine resolves the fixing through the D-0003 cascade in `CurveRepository.fix`:

| Tier | Cascade level | Status flag |
|------|---------------|-------------|
| 1 | Fresh — fixing ≤24h old | `fresh` |
| 2 | Stale — fixing 24h–7d old | `stale` |
| 3 | Interpolated — neighbour tenors only | `interpolated` |
| 4 | Scalar fallback — engine config `risk_free_rate` (3.25% default) | `scalar_fallback` |
| 5 | Unknown index name — raises `CurveDataUnavailable` | (exception) |

The engine **never crashes** on a missing curve point: tiers 1–4 always produce a fixing. Only an unrecognised index name (a typo in a YAML fixture, say) raises.

The worst-tier seen across all periods rolls up to `engine_meta["curve_status"]` so the App's UI can badge the answer ("3 periods used stale fixings — refresh the curve table").

### 17.3 Discount choice — bank vs advisor view

The same multi-period engine output can be re-discounted at a different rate by calling `aggregate.attach_discount_factors(rows, new_discount)` and then `aggregate_periods(rows)` again. Two conventions:

- **Bank view (risk-free, default)**: NPVs reflect the present value of cash flows discounted at the bank's funding-equivalent rate. The bank's hurdle rate is applied implicitly via the `target_raroc` parameter.
- **Advisor / borrower view (WACC)**: NPVs reflect the present value to the borrower of paying the facility's cash flows out of their own equity. Pass a `kind="schedule"` `DiscountSpec` with the borrower's WACC term structure.

The `effective_spread` aggregate is **scale-invariant** under uniform rate shifts: scaling every `DF_i` by a constant cancels out in `revenue_pv / drawn_pv`. So advisor-vs-bank NPV totals differ but the effective-spread number is robust across choices.

### 17.4 Configuration follow-ups

This source policy applies the operational policy: ECB / BoE / Fed daily pulls; paid feeds only on written customer ask; live curve table populated by `scripts/refresh_curves.py`. Phase 1 ships flat CSVs in `raroc_engine/data/curves/`; the Postgres-backed curve table (F-10, F-11) lands in Phase 2 Q2.

---

## 18. Migrating from v1 to v2

The v1 single-period API (`RAROCCalculator`, `RAROCInput`, `RAROCOutput`, reverse solver, bank comparison, CLI `calc` subcommand) is **unchanged** in v2.0. Existing v1 callers keep working byte-for-byte. New code can opt into the multi-period engine.

### Minimal v2 example

```python
from datetime import date
from raroc_engine import (
    EngineConfig, PeriodEngine, RAROCInput, Schedule, DiscountSpec,
)

deal = RAROCInput(
    product_type="mlt_credit",
    rating="Baa1",
    spread=0.0200,        # 200bp
    commitment_fee=0.0025,
    confirmed=True,
)
schedule = Schedule.scheduled_amortising_term_loan(
    initial_drawn=70_000_000,
    total_years=7,
    start=date(2026, 1, 1),
    upfront_fee=350_000,
)
engine = PeriodEngine(config=EngineConfig())
output = engine.run(deal, schedule, DiscountSpec(rate=0.0325))

print(f"Effective spread: {output.aggregates['effective_spread_bp']:.1f}bp")
print(f"Capital-weighted RAROC: {output.aggregates['fpe_weighted_raroc']:.2%}")
```

### CLI shortcuts

```bash
openraroc period tests/fixtures/period_rcf_5y.yaml         # rich tables
openraroc period tests/fixtures/period_rcf_5y.yaml --json  # JSON
openraroc --schedule tests/fixtures/period_rcf_5y.yaml     # top-level shortcut
```

See `CHANGELOG.md` for the full v2.0 release notes.
