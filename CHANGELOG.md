# Changelog

All notable changes to OpenRAROC are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.0.0] — 2026-05-14

### Summary

OpenRAROC v2.0 promotes the engine from a **single-period calculator** to a
**multi-period RAROC engine**. A facility's life is now modelled as an
ordered `Schedule` of `Period` rows; the engine walks each period through
the same Basel III IRB math as v1 and aggregates the per-period output
into wallet-grade headline metrics (NPV, effective spread, capital-weighted
RAROC). The v1 single-period API is preserved unchanged — existing
callers keep working byte-for-byte.

### Added

- **Multi-period engine** (`raroc_engine.period_engine.PeriodEngine`):
  walks a `Schedule` row by row, reuses `RAROCCalculator` per period,
  emits per-period output rows + `FacilityAggregates`.
- **Schedule + Period model** (`raroc_engine.schedule`) with five shape
  constructors covering common term-sheet structures:
  - `Schedule.single_period(...)` — back-compat hinge (length-1, dt=1.0)
  - `Schedule.from_raroc_input(inp, start=...)` — auto-bridge from v1 input
  - `Schedule.bullet_rcf_with_cleandown(...)` — flat commit, stepped drawn
  - `Schedule.scheduled_amortising_term_loan(...)` — linear amortisation
  - `Schedule.drawdown_ramp_with_grace(...)` — project-finance shape
  - `Schedule.project_finance_milestones(...)` — generic milestone form
- **Aggregates module** (`raroc_engine.aggregate.FacilityAggregates`)
  with NPV, total cost, effective spread, FPE-weighted RAROC,
  time-weighted RAROC, and FPE-years.
- **DiscountSpec** with three shapes (`scalar`, `curve`, `schedule`)
  per the D-0003 discount-rate convention.
- **CurveRepository** (`raroc_engine.curves`) wired through the D-0003
  fallback cascade: fresh → stale → interpolated → scalar_fallback →
  raise on unknown index name. Curves ship as flat CSVs in
  `raroc_engine/data/curves/` for EUR / USD / GBP overnight rates and
  multi-tenor curves.
- **`refresh_curves.py`** cron entry point with live HTTP parsers for
  ESTR (ECB SDMX), SONIA (BoE), SOFR (NY Fed JSON) and synthetic
  carry-forward for the multi-tenor curves.
- **CLI**:
  - New `openraroc period <fixture.yaml>` subcommand prints a per-period
    RAROC table + the wallet-grade aggregates panel.
  - Top-level `--schedule FILE` flag as a shortcut (equivalent to
    `openraroc period FILE`).
  - `--json` flag emits the full engine output as JSON for downstream tools.
- **MCP server**:
  - New tools: `run_multi_period(yaml_path, bank=...)`,
    `calculate_amortising_term_loan(...)`,
    `calculate_bullet_rcf(commitment, drawn_levels=...)`.
  - New resource: `raroc://multiperiod-spec` documents the schedule
    shapes, output fields, aggregates, and tolerances.
  - Existing `raroc://methodology` resource updated to mention the
    multi-period engine and the discount-rate convention.
- **Public Python API** (`raroc_engine.__init__`): all v1 single-period
  symbols (`RAROCCalculator`, `RAROCInput`, `RAROCOutput`, `Repository`,
  `EngineConfig`, `normalize_rating`, `PRODUCT_TYPES`, `RATING_ORDER`,
  …) plus all v2 multi-period symbols (`Schedule`, `Period`,
  `PeriodEngine`, `DiscountSpec`, `FacilityAggregates`,
  `CurveRepository`) are now re-exported from the top-level package.
- **METHODOLOGY.md** §16 covers the multi-period math (schedule shapes,
  dt-scaling convention, aggregates) and §17 covers the discount-rate
  convention (D-0003 cascade + bank-vs-advisor view).
- **Three golden fixtures** under `tests/fixtures/period_*.yaml` plus
  hand-built Excel references under `tests/fixtures/reference_excel/`.
- **Test suite**: 86 tests (61 baseline v1 + 25 v2 multi-period) all
  green. v1 single-period parity tested to 1e-12 absolute on every field.

### Changed

- `__version__` bumped from `1.0.0` to `2.0.0`.
- `pyproject.toml` project version bumped from `0.1.0` to `2.0.0` and
  `pyyaml>=6.0` added to the dependency list (needed by the period
  fixture loader; previously only used in tests).
- The MCP `calculate_raroc` instruction string now references both
  single-period and multi-period capabilities.

### Unchanged (v1 back-compat contract)

The following v1 surfaces are guaranteed unchanged in v2.0:

- `raroc_engine.calculator.RAROCCalculator.calculate(RAROCInput) -> RAROCOutput`
- `RAROCCalculator.solve_spread`, `.solve_grr`, `.sensitivity`
- `RAROCInput`, `RAROCOutput` dataclasses — all field names + defaults
- `EngineConfig` — all field names + defaults (regime, risk_free_rate,
  bank_tax_rate, funding_cost_bp, output_floor_pct, pd_floor, etc.)
- `Repository` — `get_rating_value`, `get_revenue_coeff`, `roll_rating`
- `normalize_rating`, `PRODUCT_TYPES`, `RATING_ORDER`, `MOODYS_TO_SP`
- CLI subcommands: `demo`, `calc`, `batch`, `sensitivity`, `solve`,
  `ratings`, `products`, `settings`
- MCP tools: `calculate_raroc`, `solve_minimum_spread`, `compare_banks`,
  `sensitivity_analysis`, `list_available_banks`, `list_credit_ratings`,
  `list_product_types`
- Resource URIs: `raroc://config`, `raroc://methodology`

A regression test (`tests/test_v1_backcompat.py`) pins the v1 public
surface to its v1 behaviour. The fixture parity test
(`tests/test_period_engine.py::test_single_period_parity`) verifies
that a length-1 dt=1.0 schedule reproduces v1 calculator output to
1e-12 on every field.

### Migration

There is no breaking change. Existing v1 callers do not need to change
any code. To opt into the multi-period engine:

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
output = PeriodEngine(config=EngineConfig()).run(
    deal, schedule, DiscountSpec(rate=0.0325)
)

print(f"Effective spread: {output.aggregates['effective_spread_bp']:.1f}bp")
print(f"Capital-weighted RAROC: {output.aggregates['fpe_weighted_raroc']:.2%}")
```

CLI:

```bash
openraroc period tests/fixtures/period_rcf_5y.yaml          # rich tables
openraroc period tests/fixtures/period_rcf_5y.yaml --json   # JSON
openraroc --schedule tests/fixtures/period_rcf_5y.yaml      # shortcut
```

MCP tool (in any MCP-compatible AI assistant):

```
run_multi_period(schedule_yaml_path="/abs/path/to/fixture.yaml")
calculate_amortising_term_loan(
    initial_drawn=70_000_000, total_years=7, rating="Baa1", spread_bp=200,
)
```

### Distribution

OpenRAROC continues to be distributed as the `openraroc` package; the
Python module name remains `raroc_engine`. Downstream apps (including
[Credenda](https://credenda.io)) consume OpenRAROC as an editable
install pinned to this v2.0.0 release. A private PyPI mirror remains a
follow-up — for now downstream apps pin the upstream commit.

### Acknowledgements

This release introduces the multi-period RAROC engine with Schedule /
Period dataclasses, the per-period RAROC loop and aggregation, the
floating-rate curves source, and the public API + CLI + MCP surface.

---

## [1.0.0] — pre-2026-05

Initial release. Single-period Basel III IRB RAROC calculator, modern
Python re-implementation of the original BFinance Java application
(2007). CLI, MCP server, web UI, bank profiles from public Pillar 3
disclosures, reverse spread/GRR solver.

See git history for detailed commits.
