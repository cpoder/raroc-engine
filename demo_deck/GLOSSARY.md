# Glossary — speaker cheat sheet

Hand-held reference for the OpenRAROC corporate + partner demo. Read once before the talk, keep open on a second screen during.

**Why you need this.** The audience is mixed:
- *Half* (treasurers from larger corporates, ex-bank advisors, the more technical CFOs) will be fluent in PD/LGD/EAD/CTI and will roll their eyes if you over-explain.
- *Half* (CFOs of smaller mid-caps, fractional CFOs, accountants pivoting into corporate finance, mid-level finance directors) have heard the acronyms but couldn't define them under pressure.

Your job is to **define each term in one short sentence as you use it** — fast enough not to bore the experts, clear enough not to lose the rest. The "Plain English" line in each entry below is calibrated for that.

Terms grouped by **what comes up first in the talk**, not alphabetically. Each entry has:
- **Plain English** — the one-sentence definition you say out loud if you sense the room is blank.
- **In one number** — the typical magnitude, so you can sanity-check live without a calculator.
- **If asked, say** — your one-line answer if a savvier attendee challenges you on it.

---

## I. The five letters that decide your loan price (and that your bank assumes you don't know)

### RAROC — Risk-Adjusted Return on Capital
**Plain English.** The post-tax return a bank earns on the regulatory capital it's forced to set aside for one specific deal. *"Is this loan worth the equity it ties up?"*
**The formula:** `RAROC = (1 − tax) × [ (Revenue − Cost − Funding − Expected Loss) / Economic Capital + Risk-free rate ]`
**In one number.** Banks target ~12% in Europe, ~14–15% in the US, ~9% for retail-heavy or state-owned banks. Below the bank's own *hurdle rate*, the deal gets rejected.
**If asked, say.** "RAROC is the metric every bank credit committee approves against. Same definition for thirty years. The new thing is that *you* can compute it too — that's what OpenRAROC does."

### PD — Probability of Default
**Plain English.** The chance the borrower defaults within one year, expressed as a percentage. Comes from S&P / Moody's long-run averages mapped to the borrower's credit rating.
**In one number.** AAA = 0.01%; A = 0.05%; BBB+ / Baa1 = **0.10%** (Nordwind); BBB = 0.16%; BB+ = 0.38%. Investment grade ends at BBB-/Baa3 (≈0.24%); below that, PD jumps an order of magnitude.
**If asked, say.** "S&P long-run, floored at 5 basis points under Basel III."

### LGD — Loss Given Default
**Plain English.** Of the money exposed when a borrower defaults, what fraction does the bank actually lose (after recovery, collateral, legal process)? *"How bad is bad?"*
**In one number.** Unsecured corporate: 30–45%. Secured by receivables / real estate: 15–25%. Senior unsecured bond: ~50%. Basel IV introduces FLOORS: 25% unsecured / 10% secured.
**If asked, say.** "It's 1 minus the recovery rate. The output floor caps how low banks can claim it."

### EAD — Exposure at Default
**Plain English.** The size of the bank's exposure if the borrower defaults *next year*. Not the same as the loan amount — for a revolving credit, the borrower may draw the line down before defaulting.
**Formula.** EAD = (drawn amount) + (CCF × undrawn amount) − collateral.
**For Nordwind.** 35M drawn + 75% × 15M undrawn − 0 collateral = **46.25M**.
**If asked, say.** "Drawn at 100%, undrawn at the credit conversion factor. 75% for confirmed RCFs."

### EL — Expected Loss
**Plain English.** Average annual loss the bank expects on this deal, across all possible futures. = EAD × PD × LGD.
**In one number.** Tiny for investment grade (Nordwind: 23k EUR/year on a 46M exposure). Material for high-yield. Drives loan-loss provisions.
**If asked, say.** "It's already in the price — that's why investment-grade spreads are tight."

---

## II. Capital, the regulatory machine

### K — Risk weight (capital requirement)
**Plain English.** The percentage of EAD that the bank must hold as regulatory equity capital against this deal. Computed from PD, LGD, maturity, and a correlation factor via the Basel IRB formula.
**In one number.** Investment-grade corporate: 3–6%. High-yield: 10–25%. Defaulted: 100%+.
**For Nordwind.** K = 4.26%.
**If asked, say.** "Basel IRB formula — same one every IRB bank uses. The output floor pins it from below."

### FPE — Fonds Propres Économiques (Economic Capital)
**Plain English.** The actual euros of equity capital allocated to the deal. = EAD × K.
**French term, used in this engine** because the original BFinance model was French.
**For Nordwind.** FPE = 46.25M × 4.26% = **1.97M EUR** of BNP's equity tied up in this single facility.
**If asked, say.** "Same thing as 'allocated capital' or 'risk-weighted assets times target capital ratio'. The denominator of RAROC."

### Output floor
**Plain English.** A Basel IV mechanism that forces the IRB-computed K to be at least a percentage of what the simpler *Standardised* approach would compute. Stops banks from using fancy models to game capital downward.
**Phase-in.** 2025: 50%; **2026: 55%** (today); 2027: 60%; 2028: 65%; 2029: 70%; 2030+: 72.5%.
**Why it matters.** A bank not yet at 55% looks artificially cheap on capital today and re-prices its book in 2027–28.
**If asked, say.** "Customer benefit is short-lived. If you quote me 30bp under market today, I'll be re-quoted in 24 months."

### IRB — Internal Ratings-Based approach
**Plain English.** The Basel approach where a bank computes capital using its own statistical PD/LGD models (subject to regulator approval), instead of regulatory defaults.
**Two flavours.** **A-IRB (Advanced)** — bank models PD, LGD, and EAD. **F-IRB (Foundation)** — bank models PD only; LGD and EAD are regulatory defaults.
**Who uses what.** Most large EU banks: A-IRB on corporate. US banks under "Basel III endgame" 2025: largely standardised on corporate. Chinese: mixed.
**If asked, say.** "A-IRB shaves capital but it's the regime that the output floor most directly bites."

### SA — Standardised approach
**Plain English.** The simple regulatory alternative to IRB. Risk weights come from a table indexed by external rating: 20% (AAA-AA), 50% (A), 75% (BBB), 100% (BB-B), 150% (below).
**Why it matters here.** The output floor is "55% of the SA-implied K". So SA is the floor's reference point, not a separate calculation banks usually use.
**If asked, say.** "SA is what our calculator defaults to when a bank's CR6 isn't granular enough for IRB. It's also the floor's anchor."

### CCF — Credit Conversion Factor
**Plain English.** What fraction of an UNDRAWN committed line should be added to EAD because the borrower will probably draw it before defaulting.
**In one number.** Confirmed (committed, irrevocable) RCF: **75%** under Basel III. Unconfirmed (uncommitted, cancellable): 10–40%. Standby letters of credit: 50%.
**If asked, say.** "Borrowers always draw the line before defaulting. CCF prices that in."

---

## III. The bank's economics

### CTI — Cost-to-Income ratio
**Plain English.** Operating costs divided by net banking income. The headline efficiency metric on every bank's P&L. Lower = leaner.
**In one number.** Best-in-class (Italian/Spanish digital banks): 38–42%. US wholesale banks: 50–55%. European universal banks: 55–65%. The hard cases: 65%+.
**Where it enters RAROC.** As the "Cost" line. A 10-point CTI gap on the same revenue moves RAROC by ~70bp on this deal.
**If asked, say.** "Public, audited, in every annual report. Not a number your RM can argue away on a pricing call."

### Effective tax rate (ETR)
**Plain English.** Actual taxes paid divided by pre-tax income. Differs from the statutory headline because of deferred taxes, jurisdiction mix, levies.
**In one number.** US banks post-TCJA: ~21%. UK: 22–25%. France/Germany: 25–28%. Netherlands: 27–29% (high CIT + financial-sector levy). Switzerland/Singapore: 15–20%.
**Why it matters.** RAROC is post-tax. A 5-point ETR delta moves RAROC by ~70bp.
**If asked, say.** "Geography, not skill. JP Morgan's tax advantage is just being American."

### Funding spread / funding cost
**Plain English.** The bank's incremental cost to raise the money it's about to lend. Approximated by the spread on the bank's senior unsecured bonds over the risk-free rate.
**In one number.** AAA banks (rare): 5–10bp. AA-: 15–25bp. A: 30–50bp. BBB: 60–100bp.
**Why it matters.** Subtracted from gross margin in the RAROC formula.
**Why we mostly use 0–20bp here.** Banks don't disclose product-level funding cost in Pillar 3. The 0–20bp baseline is conservative — and exactly what Door 3 of the closing slide is asking for.
**If asked, say.** "Underestimated, deliberately. Treasury teams who'll share their indicative term-funding curve get a sharper profile."

### Hurdle rate
**Plain English.** The minimum RAROC the bank requires to approve a deal. Below it, the deal gets rejected — no matter how nice the relationship is.
**In one number.** European universal: 10–12%. UK: 12–13%. US: 14–15%. Chinese state: 8–10%. Highly varies by product (capital markets ~15–18%, retail mortgages ~9%).
**If asked, say.** "It's not public, but it leaks. Investor day decks talk about 'group target return on tangible equity' — that's the same number plus or minus a beta."

---

## IV. The framework, the rules, the acronyms

### Basel II / Basel III / Basel IV
**Plain English.** Successive versions of the international banking capital framework, written by the Basel Committee on Banking Supervision (BCBS). Implemented locally by each jurisdiction (CRR3 in EU, "Basel III endgame" in US, etc.).
- **Basel II (2007)** — introduced the IRB approach.
- **Basel III (2010, refined 2017)** — tougher capital ratios, leverage ratio, liquidity rules.
- **"Basel IV" (the 2017 finalization, phasing in 2025–2030)** — output floor, LGD floors, restrictions on IRB. The current pain point.
**If asked, say.** "We're Basel III + the 2017 finalization. The toggle for Basel II is in the engine if you want to compare regimes."

### BIS — Bank for International Settlements
**Plain English.** The "central bank of central banks" in Basel, Switzerland. Hosts the BCBS. Publishes the framework documents (CRE31, CRE32, etc.).
**If asked, say.** "The source. CRE31 is the IRB risk-weight chapter — that's the formula in our engine."

### EBA — European Banking Authority
**Plain English.** The EU's banking regulator. Translates BIS rules into binding EU technical standards (RTS, ITS). Runs the EU-wide stress tests.
**If asked, say.** "EBA is who the European banks actually answer to on day-to-day regulatory implementation."

### CRR3 / CRD VI
**Plain English.** The current EU regulatory package implementing Basel IV. CRR3 = the regulation (binding). CRD VI = the directive (national transposition).
**If asked, say.** "Came into effect Jan 1 2025. The output floor is in here."

### Pillar 3
**Plain English.** The third pillar of the Basel framework — the "market discipline" pillar. Forces every IRB bank to publish detailed risk and capital information annually (and quarterly for the largest).
**The Pillars.** 1: minimum capital. 2: supervisory review. 3: public disclosure.
**If asked, say.** "Pillar 3 is the only reason this product can exist. Every CR6 table in the world is a free PDF."

### CR6 (and friends)
**Plain English.** A specific table within Pillar 3. The "credit risk by IRB approach and PD band" table. Other useful tables: CR6-A (IRB approach split), CR7 (effect of credit risk mitigation), CR8 (RWA flow statement).
**For this product.** CR6 gives us PD, LGD, EAD by exposure class for each bank. Foundation of all 59 bank profiles.
**If asked, say.** "Open the bank's last Pillar 3 PDF, search 'CR6'. That's where every number in this tool comes from."

---

## V. The deal vocabulary

### RCF — Revolving Credit Facility
**Plain English.** A committed credit line the borrower can draw, repay, redraw at will up to a limit. Pays a commitment fee on the undrawn portion.
**Nordwind's deal.** 5-year RCF, EUR 50M committed, 35M expected average drawn (70% utilisation).
**If asked, say.** "The most common corporate credit product. Liquidity insurance, basically."

### Term loan
**Plain English.** Lump-sum loan with a defined repayment schedule. Drawn once, then either bullet (single repayment at maturity) or amortising (scheduled paydowns).
**If asked, say.** "Not what Nordwind has, but the engine handles them — toggle 'mlt_credit'."

### Bullet vs amortising
**Plain English.** **Bullet** = principal repaid in one shot at maturity. **Amortising** = scheduled paydowns reducing principal over time.
**Why it matters for RAROC.** Bullet has a higher EAD profile (borrower owes the full amount the whole time) → higher capital → lower RAROC at the same spread.
**If asked, say.** "Engine takes residual maturity in months — handles both."

### Tenor / maturity
**Plain English.** **Tenor** = how long the deal lasts in total. **Residual maturity** = how long it has left to run today. Drives the maturity adjustment in the IRB formula.
**In one number.** Short-term trade finance: 3–12m. Working capital RCF: 1–5y. Term loan: 3–7y. Project finance: 10–20y.
**If asked, say.** "Longer tenor = higher capital = lower RAROC at the same price."

### Spread (in this context)
**Plain English.** The annual margin the bank charges over the reference rate. *Not* the bid-offer spread, *not* the credit spread on a bond. Specifically: lending margin.
**Reference rates.** EURIBOR (EUR), SONIA (GBP), SOFR (USD), TONA (JPY).
**Nordwind's deal.** 150bp = 1.50% over EURIBOR.
**If asked, say.** "Spread × drawn balance is the bank's primary income line on this deal."

### Commitment fee
**Plain English.** Annual fee paid on the UNDRAWN portion of a committed line. Compensates the bank for reserving the capacity.
**In one number.** 25–35% of the spread is typical. (Nordwind: 20bp commitment vs 150bp spread = 13%.)
**If asked, say.** "The bank gets paid for the optionality even if the customer never draws."

### Participation fee / arrangement fee / upfront fee
**Plain English.** One-off fees paid at signing.
- **Participation** = paid by the borrower to each lender.
- **Arrangement** = paid to the lead bank for structuring.
- **Upfront** = generic; usually amortised over the tenor for accounting but counts as Year-1 revenue for RAROC.
**If asked, say.** "Front-loads RAROC. Useful when the spread alone wouldn't clear hurdle."

### GRR — Global Guarantee Recovery Rate
**Plain English.** The fraction of EAD that's covered by a third-party guarantee (parent company, government export credit agency, insurer, etc.).
**Nordwind's deal.** 50% — the parent guarantees half.
**Mechanically.** Reduces effective LGD in the Basel formula. Does NOT reduce PD.
**Common confusion.** GRR is about RECOVERY (what gets covered if default happens). PD is about PROBABILITY (whether default happens). The guarantee makes the bank's loss smaller, not the default itself less likely.
**If asked, say.** "It's in the LGD, not the PD. Easy to mess up; the engine handles it correctly."

### Collateral (in the Basel sense)
**Plain English.** Specific assets pledged to the bank. Different from a guarantee. Reduces EAD if eligible.
**Eligible types.** Financial collateral (cash, securities), real estate, receivables, "other physical". Each has its own LGD floor.
**For Nordwind.** Zero — it's a clean line backed only by the parent guarantee.
**If asked, say.** "Engine handles all four collateral types. Most corporate RCFs have none."

### Confirmed vs unconfirmed (a.k.a. committed vs uncommitted)
**Plain English.** **Confirmed/committed** = bank has a contractual obligation to fund if conditions are met. **Unconfirmed/uncommitted** = bank can refuse to fund at any time.
**Why it matters.** Confirmed CCF is much higher (75% vs 10–40%) so EAD and capital are higher.
**If asked, say.** "The customer pays for the bank's obligation. That's the commitment fee."

---

## VI. The relationship vocabulary

### RM — Relationship Manager
**Plain English.** Day-to-day client contact at the bank. Mid-level: VP/Director. Owns the wallet but doesn't have credit authority alone.

### KAM — Key Account Manager
**Plain English.** Senior version of an RM, manages strategic / multi-billion accounts. Often MD-level.

### Wallet
**Plain English.** The total bundle of business one bank does with one client across all products: credit + cash + FX + hedging + advisory + bonds.
**Wallet share.** What % of that bundle you have versus competitors. The bank-vs-bank scoreboard.

### Cross-sell
**Plain English.** Selling additional products to a credit client. The actual source of relationship-banking profit. Stand-alone credit RAROC is often below hurdle; the bundle isn't.

### Bundle RAROC (ours, not industry standard)
**Plain English.** RAROC computed across the wallet, not on one product alone. Door 3 of the negotiation chapter.
**If asked, say.** "Stand-alone credit RAROC is the wrong question. Bundle RAROC is the right one. Tool can do both."

### Pricing committee
**Plain English.** The internal forum (weekly or monthly) where RMs bring deals for approval. Approves on RAROC, regulatory capital, policy compliance.

### Credit committee
**Plain English.** Distinct from pricing committee. Approves the *risk* (rating, structure, covenants). Pricing committee approves the *return*.

---

## VII. The borrower vocabulary

### Mid-cap
**Plain English.** Mid-sized corporate. EUR 500M – 5B revenue, typically. Below = small-cap / SME. Above = large-cap.

### Mittelstand
**Plain English.** Specifically German mid-cap. Family/founder-owned, often global niche leaders ("hidden champions"). The backbone of the German export economy.

### Investment grade vs high yield
**Plain English.** **Investment grade** = S&P BBB- / Moody's Baa3 and above. **High yield** = below. The cliff at the boundary is enormous: PD jumps from ~0.24% (Baa3) to ~0.38% (Ba1) and bid-ask spreads on bonds blow out 3-5x.

### Rating notation (S&P / Moody's / Fitch)
| S&P | Moody's | Fitch | 1-yr PD |
|-----|---------|-------|---------|
| AAA | Aaa | AAA | 0.01% |
| AA+/AA/AA- | Aa1/Aa2/Aa3 | AA+/AA/AA- | 0.01–0.03% |
| A+/A/A- | A1/A2/A3 | A+/A/A- | 0.04–0.07% |
| **BBB+** | **Baa1** | **BBB+** | **0.10%** ← Nordwind |
| BBB/BBB- | Baa2/Baa3 | BBB/BBB- | 0.16–0.24% |
| BB+/BB/BB- | Ba1/Ba2/Ba3 | BB+/BB/BB- | 0.38–1.11% |
| B+/B/B- | B1/B2/B3 | B+/B/B- | 2.14–7.12% |
| CCC and below | Caa+ | CCC | 15%+ |

**If asked, say.** "Engine accepts Moody's notation natively (Baa1 is BBB+). UI lets you type either."

### EBITDA / EBITDA margin
**Plain English.** Earnings Before Interest, Taxes, Depreciation, Amortisation. Proxy for cash generation. Margin = EBITDA / revenue.
**In one number.** Industrial machinery: 8–15%. Software: 25–40%. Retail: 4–8%.

### Net leverage
**Plain English.** (Net debt) / EBITDA. How many years of cash flow it would take to repay the debt at zero growth.
**In one number.** Investment-grade corporate: < 3x. Leveraged: 4–6x. Distressed: 7x+.

---

## VIII. The product vocabulary

### Freemium
**Plain English.** Standard SaaS pricing: free version with limited capabilities + paid tier with everything. We're 4 banks free, all 59 in the EUR 49/year Pro tier.

### MCP — Model Context Protocol
**Plain English.** Open spec by Anthropic for AI assistants to call external tools. Your Claude / ChatGPT / Cursor can run our RAROC engine directly — type "what's the min spread on my BNP RCF?" and get an answer.
**If asked, say.** "Niche today, mainstream in 12 months. Pre-positioned for it."

### Min-spread solver / "reverse spread solver"
**Plain English.** Inverts the RAROC formula. Input: target RAROC + everything else. Output: the minimum spread that achieves it.
**Algorithmically.** Brent's method (a 1-D root finder). 5ms per call.
**If asked, say.** "Same engine, run backwards."

### Sensitivity analysis / sensitivity grid
**Plain English.** A 2-D table showing how RAROC changes when you vary one input. e.g. RAROC across rating bands × maturity. Standard credit committee artifact.

### Bank comparison
**Plain English.** The same deal, computed against multiple bank profiles, side-by-side. The single most powerful feature in the tool — it's the chart you put in front of the RM.

### Portfolio optimizer
**Plain English.** Pro-tier feature. Given your full multi-facility portfolio + N candidate banks, allocates each facility to the bank that minimises your total cost subject to constraints (max % per bank, min number of banks for diversification).
**If asked, say.** "Reduces wallet allocation from gut-feel to LP problem."

---

## Five-minute pre-talk skim

Read JUST THIS if you're 5 minutes from showtime:

1. **RAROC** = post-tax return / capital. Bank's pricing metric.
2. **K** = capital % required. **EAD** = exposure size. **FPE** = K × EAD = euros of capital.
3. **PD × LGD × EAD** = Expected Loss. Tiny for IG.
4. **CTI / tax rate / funding spread / output floor / LGD floor** = the five bank-specific drivers.
5. **Hurdle rate** ≈ 12% Europe, 14% US.
6. **Pillar 3 / CR6** = the public source for all bank parameters.
7. **GRR** is in LGD, not in PD.
8. **Confirmed RCF** has 75% CCF on the undrawn portion.
9. The deal: 5-year RCF, 50M committed, 35M drawn, BBB+/Baa1, 50% GRR, 150bp + 20bp + 50k.
10. The numbers: BNP RAROC 12.52%, range 11.56–14.26%, BNP min spread 143bp.

Now go.
