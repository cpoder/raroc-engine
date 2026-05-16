"""Generate the numbers used in the demo deck."""
from dataclasses import asdict
from raroc_engine.banks import list_bank_profiles
from raroc_engine.calculator import RAROCCalculator
from raroc_engine.config import EngineConfig
from raroc_engine.models import RAROCInput
from raroc_engine.repository import Repository

# Scenario: Nordwind Industries — German Mittelstand industrial
# 5Y revolving credit facility, EUR 50M committed, EUR 35M avg drawn
# BBB+ rating (~Baa1), 50% global GRR (parent guarantee), confirmed
DEAL = dict(
    product_type="mlt_credit",
    average_drawn=35_000_000,
    average_volume=50_000_000,
    spread=0.0150,            # 150 bp
    commitment_fee=0.0020,    # 20 bp
    flat_fee=0,
    participation_fee=50_000,
    upfront_fee=0,
    rating="Baa1",            # ≈ BBB+
    residual_maturity=60,     # 5y
    confirmed=True,
    global_grr=0.50,
    collateral_stress_value=0,
    bank="",
)

BANKS = [
    "bnp_paribas",
    "hsbc",
    "deutsche_bank",
    "jp_morgan",
    "societe_generale",
    "credit_agricole",
    "barclays",
    "ing_group",
]

profiles = list_bank_profiles()
repo = Repository()

print("=" * 80)
print("CHAPTER 1 — BNP Paribas deep-dive")
print("=" * 80)
p = profiles["bnp_paribas"]
cfg = EngineConfig(
    regime="basel3",
    bank_tax_rate=p.effective_tax_rate,
    funding_cost_bp=p.funding_spread_bp,
)
calc = RAROCCalculator(repo, cfg)
out = calc.calculate(RAROCInput(**DEAL))
print(f"Revenue:          {out.revenue:>14,.0f} EUR")
print(f"Cost:             {out.cost:>14,.0f} EUR")
print(f"EAD:              {out.exposure:>14,.0f} EUR")
print(f"PD (S&P long-run):{out.pd*100:>13.4f}%")
print(f"PD (Basel adj):   {out.pd_basel2*100:>13.4f}%  (after {DEAL['global_grr']*100:.0f}% GRR)")
print(f"Risk weight K:    {out.risk_weight*100:>13.4f}%")
print(f"FPE (econ. cap.): {out.fpe:>14,.0f} EUR")
print(f"Expected loss:    {out.average_loss:>14,.0f} EUR")
print(f"Net margin:       {out.net_margin:>14,.0f} EUR")
print(f"Taxes:            {out.taxes:>14,.0f} EUR")
print(f"--> RAROC:        {out.raroc*100:>13.2f}%")

print()
print("=" * 80)
print("CHAPTER 2 — Same deal, different banks")
print("=" * 80)
print(f"{'Bank':<22}{'Country':<14}{'CTI':>6}{'Tax':>7}{'RAROC':>9}{'MinSpread':>11}")
print("-" * 80)
rows = []
for k in BANKS:
    p = profiles[k]
    cfg = EngineConfig(
        regime="basel3",
        bank_tax_rate=p.effective_tax_rate,
        funding_cost_bp=p.funding_spread_bp,
    )
    calc = RAROCCalculator(repo, cfg)
    out = calc.calculate(RAROCInput(**DEAL))
    solve = calc.solve_spread(RAROCInput(**DEAL), target_raroc=0.12)
    rows.append((p.name, p.country, p.cost_to_income, p.effective_tax_rate, out.raroc, solve["solved_spread_bp"]))

rows.sort(key=lambda r: -r[4])
for name, ctry, cti, tax, raroc, minsp in rows:
    print(f"{name:<22}{ctry:<14}{cti*100:>5.0f}%{tax*100:>6.0f}%{raroc*100:>8.2f}%{minsp:>9.0f}bp")

print()
print("=" * 80)
print("CHAPTER 3 — Negotiation: BNP at different spreads")
print("=" * 80)
p = profiles["bnp_paribas"]
cfg = EngineConfig(regime="basel3", bank_tax_rate=p.effective_tax_rate,
                   funding_cost_bp=p.funding_spread_bp, target_raroc=0.12)
calc = RAROCCalculator(repo, cfg)

base_inp = RAROCInput(**DEAL)
solve = calc.solve_spread(RAROCInput(**DEAL), target_raroc=0.12)
print(f"BNP target RAROC: 12.00%")
print(f"Min spread that hits 12% RAROC: {solve['solved_spread_bp']:.0f} bp")
print()
print(f"{'Spread':>10}{'RAROC':>10}{'Annual revenue':>20}{'Saving vs 150bp':>18}")
print("-" * 60)
base_rev = None
for sp_bp in [150, 140, 130, 120, solve['solved_spread_bp']]:
    d = dict(DEAL); d["spread"] = sp_bp / 10000
    out = calc.calculate(RAROCInput(**d))
    if base_rev is None:
        base_rev = out.revenue
    saving = base_rev - out.revenue
    tag = "  <-- min" if abs(sp_bp - solve['solved_spread_bp']) < 0.5 else ""
    print(f"{sp_bp:>8.0f}bp{out.raroc*100:>9.2f}%{out.revenue:>18,.0f}{saving:>15,.0f}{tag}")
