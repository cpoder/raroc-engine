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
