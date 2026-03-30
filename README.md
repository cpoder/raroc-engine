# RAROC Engine

**See your credit through your banker's eyes.**

A Risk-Adjusted Return on Capital (RAROC) calculator that shows corporate treasurers how banks evaluate their credit facilities. Uses Basel III formulas and real bank data extracted from public Pillar 3 regulatory filings.

## What it does

Upload your credit portfolio (term loans, revolving facilities, guarantees, derivatives) and instantly see:

- **RAROC for each facility** -- how profitable is your deal for your bank?
- **Bank comparison** -- the same deal priced by 35 different banks (HSBC vs Deutsche Bank vs JP Morgan...)
- **Minimum spread solver** -- "what's the lowest spread my bank will accept?"
- **Sensitivity analysis** -- how GRR, rating, maturity, and spread affect your bank's economics

## Quick start

```bash
# Install dependencies
pip install scipy click rich fastapi uvicorn

# CLI demo
python3 run_raroc.py demo

# Web app
python3 serve.py
# Open http://localhost:8000

# MCP server (for AI agents)
python3 -m raroc_engine.mcp_server
```

## Free vs Premium

The open source engine includes **4 bank profiles** for free:
- BNP Paribas (France)
- HSBC (United Kingdom)
- Deutsche Bank (Germany)
- JP Morgan (United States)

**Premium data** (31 additional banks across 13 countries) is available via annual license. Premium banks include all major European banks (SocGen, Credit Agricole, Barclays, ING, UniCredit, Santander, BBVA...), US banks (Citi, BofA, Goldman, Morgan Stanley, Wells Fargo...), and Chinese banks (ICBC, CCB, Bank of China).

All bank data is extracted from actual Pillar 3 CR6 regulatory filings -- not estimates.

To activate premium: place your `premium_banks.json` in the project root.

## Bank comparison example

```
BBB+ rated 5Y term loan, EUR 25M drawn / 30M committed, 150bp spread, 40% GRR

Bank                    RAROC    Min Spread
HSBC                   12.25%       147bp
Credit Agricole        11.86%       152bp
Barclays               11.64%       154bp
BNP Paribas            10.96%       164bp
Deutsche Bank           8.51%       202bp
```

Same deal, 55bp spread difference between cheapest and most expensive bank.

## Architecture

```
raroc_engine/
  models.py         Data models, rating mappings (S&P/Moody's/Fitch)
  config.py         All configurable parameters
  repository.py     Reference data (PD tables, exposure coefficients)
  calculator.py     Basel III IRB formulas
  banks.py          Bank profiles (free + premium loader)
  cli.py            Terminal CLI
  web.py            FastAPI backend
  mcp_server.py     MCP server for AI agents
  static/index.html Web frontend
```

## Data sources

- **PD values**: S&P Global long-run average corporate default rates
- **Bank profiles**: Public Pillar 3 CR6 tables extracted from regulatory filings
- **Basel III formulas**: BIS CRE31/CRE32 (verified against official standards)

## License

MIT for the engine code. Premium bank data is licensed separately.
