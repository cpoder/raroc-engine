"""Portfolio optimization: assign facilities to banks to minimize borrowing cost.

Uses Mixed-Integer Linear Programming (scipy.optimize.milp) to solve the
constrained assignment problem. Each facility is assigned to exactly one bank,
subject to concentration, diversification, and lock constraints.
"""

import numpy as np
from dataclasses import asdict
from scipy.optimize import milp, LinearConstraint, Bounds
from scipy.sparse import eye as speye, block_diag, vstack, csc_matrix

from .models import RAROCInput
from .config import EngineConfig
from .repository import Repository
from .calculator import RAROCCalculator
from .banks import BANK_PROFILES, BankProfile

REGIONS = {
    "Western Europe": ["France", "Belgium", "Netherlands", "Luxembourg"],
    "UK & Ireland": ["United Kingdom", "Ireland"],
    "Southern Europe": ["Spain", "Italy", "Portugal", "Greece"],
    "DACH": ["Germany", "Austria", "Switzerland"],
    "Nordics": ["Sweden", "Finland", "Denmark", "Norway", "Iceland"],
    "North America": ["United States", "Canada"],
    "Asia-Pacific": ["China", "Japan", "South Korea", "Australia", "Singapore", "Hong Kong", "India"],
    "Latin America": ["Brazil", "Colombia", "Mexico", "Chile", "Argentina"],
    "Middle East & Africa": ["UAE", "Qatar", "Saudi Arabia", "South Africa"],
    "CEE": ["Poland", "Czech Republic", "Hungary", "Romania"],
}


def _get_region(country: str) -> str:
    for region, countries in REGIONS.items():
        if country in countries:
            return region
    return "Other"


def optimize_portfolio(
    facilities: list[RAROCInput],
    bank_keys: list[str],
    repo: Repository,
    base_config: EngineConfig,
    target_raroc: float = 0.12,
    max_bank_pct: float = 0.30,
    min_banks: int = 3,
    max_region_pct: float = 0.50,
    locked: dict[int, str] | None = None,
) -> dict:
    """Find the optimal facility-to-bank assignment that minimizes total cost.

    Args:
        facilities: List of facility inputs
        bank_keys: Bank keys to consider
        repo: Repository for reference data
        base_config: Base engine config (regime, risk_free_rate, etc.)
        target_raroc: Bank's target RAROC hurdle
        max_bank_pct: Max % of total exposure per bank (0-1)
        min_banks: Minimum number of banks in the solution
        max_region_pct: Max % of total exposure per region (0-1)
        locked: Dict of facility_index → bank_key for fixed assignments

    Returns:
        Optimization result with assignments, summary, and constraint status.
    """
    locked = locked or {}
    n = len(facilities)
    m = len(bank_keys)

    if n == 0 or m == 0:
        return {"status": "infeasible", "error": "No facilities or banks provided"}

    # Validate bank keys
    profiles: list[BankProfile] = []
    for bk in bank_keys:
        p = BANK_PROFILES.get(bk)
        if not p:
            return {"status": "infeasible", "error": f"Unknown bank: {bk}"}
        profiles.append(p)

    # ── Step 1: Precompute min spreads and EADs ──────────────────

    min_spread = np.full((n, m), np.inf)
    ead = np.zeros(n)
    current_spread = np.zeros(n)
    facility_names = []

    for i, fac in enumerate(facilities):
        facility_names.append(fac.operation or f"Facility {i+1}")
        current_spread[i] = fac.spread

        # Get EAD from a baseline calculation
        base_calc = RAROCCalculator(repo, base_config)
        base_out = base_calc.calculate(fac)
        ead[i] = base_out.exposure

        for j, bk in enumerate(bank_keys):
            p = profiles[j]
            cfg = EngineConfig(
                regime=base_config.regime,
                risk_free_rate=base_config.risk_free_rate,
                bank_tax_rate=p.effective_tax_rate,
                funding_cost_bp=p.funding_spread_bp,
                output_floor_pct=base_config.output_floor_pct,
                pd_floor=base_config.pd_floor,
                lgd_floor_unsecured=base_config.lgd_floor_unsecured,
                lgd_floor_secured=base_config.lgd_floor_secured,
                target_raroc=target_raroc,
            )
            calc = RAROCCalculator(repo, cfg)
            try:
                result = calc.solve_spread(
                    RAROCInput(**asdict(fac)),
                    target_raroc=target_raroc,
                )
                min_spread[i, j] = result["solved_spread"]
            except Exception:
                min_spread[i, j] = np.inf  # infeasible pair

    total_ead = ead.sum()
    if total_ead <= 0:
        return {"status": "infeasible", "error": "Total exposure is zero"}

    # Replace inf with a large penalty (so the solver can still find a solution)
    max_finite = np.max(min_spread[np.isfinite(min_spread)]) if np.any(np.isfinite(min_spread)) else 1.0
    penalty = max_finite * 10
    min_spread = np.where(np.isfinite(min_spread), min_spread, penalty)

    # ── Step 2: Build MILP ───────────────────────────────────────

    # Variables: x[i,j] for i=0..n-1, j=0..m-1 → index = i*m + j
    #            y[j] for j=0..m-1 (bank used indicator) → index = n*m + j
    num_x = n * m
    num_y = m
    num_vars = num_x + num_y

    # Cost vector: minimize Σ min_spread[i,j] * ead[i] * x[i,j]
    # Small penalty on y variables to force y[j]=0 when bank j is unused
    # (without this, solver sets all y[j]=1 trivially satisfying min_banks)
    c = np.zeros(num_vars)
    for i in range(n):
        for j in range(m):
            c[i * m + j] = min_spread[i, j] * ead[i]
    y_penalty = max(c.max() * 1e-6, 1e-6)
    for j in range(m):
        c[num_x + j] = y_penalty

    # Integrality: all binary
    integrality = np.ones(num_vars, dtype=int)

    # Bounds
    lb = np.zeros(num_vars)
    ub = np.ones(num_vars)

    # Apply locks: fix x[i, j_locked] = 1 and x[i, other] = 0
    for fac_idx, bk in locked.items():
        if fac_idx < 0 or fac_idx >= n:
            continue
        if bk not in bank_keys:
            continue
        j_locked = bank_keys.index(bk)
        for j in range(m):
            idx = fac_idx * m + j
            if j == j_locked:
                lb[idx] = 1.0  # must be 1
            else:
                ub[idx] = 0.0  # must be 0

    bounds = Bounds(lb=lb, ub=ub)

    # Build all constraints as a single sparse matrix for reliability
    A_rows, A_cols, A_vals = [], [], []
    con_lb, con_ub = [], []
    row_idx = 0

    # Constraint 1: each facility to exactly one bank
    # For each i: Σ_j x[i,j] = 1
    for i in range(n):
        for j in range(m):
            A_rows.append(row_idx); A_cols.append(i * m + j); A_vals.append(1.0)
        con_lb.append(1.0); con_ub.append(1.0)
        row_idx += 1

    # Constraint 2: max exposure per bank
    # For each j: Σ_i ead[i] * x[i,j] ≤ max_bank_pct * total_ead
    max_bank_exp = max_bank_pct * total_ead
    for j in range(m):
        for i in range(n):
            A_rows.append(row_idx); A_cols.append(i * m + j); A_vals.append(ead[i])
        con_lb.append(0.0); con_ub.append(max_bank_exp)
        row_idx += 1

    # Constraint 3: link x[i,j] ≤ y[j]
    # For each i, j: x[i,j] - y[j] ≤ 0
    for i in range(n):
        for j in range(m):
            A_rows.append(row_idx); A_cols.append(i * m + j); A_vals.append(1.0)
            A_rows.append(row_idx); A_cols.append(num_x + j); A_vals.append(-1.0)
            con_lb.append(-np.inf); con_ub.append(0.0)
            row_idx += 1

    # Constraint 3b: force y[j]=0 when bank j is unused: y[j] ≤ Σ_i x[i,j]
    # Rewritten as: Σ_i x[i,j] - y[j] ≥ 0
    for j in range(m):
        for i in range(n):
            A_rows.append(row_idx); A_cols.append(i * m + j); A_vals.append(1.0)
        A_rows.append(row_idx); A_cols.append(num_x + j); A_vals.append(-1.0)
        con_lb.append(0.0); con_ub.append(np.inf)
        row_idx += 1

    # Constraint 3c: min banks — Σ_j y[j] ≥ min_banks
    for j in range(m):
        A_rows.append(row_idx); A_cols.append(num_x + j); A_vals.append(1.0)
    con_lb.append(float(min_banks)); con_ub.append(np.inf)
    row_idx += 1

    # Constraint 4: max exposure per region
    region_to_banks: dict[str, list[int]] = {}
    for j, bk in enumerate(bank_keys):
        region = _get_region(profiles[j].country)
        region_to_banks.setdefault(region, []).append(j)

    max_region_exp = max_region_pct * total_ead
    for region, bank_indices in region_to_banks.items():
        for j in bank_indices:
            for i in range(n):
                A_rows.append(row_idx); A_cols.append(i * m + j); A_vals.append(ead[i])
        con_lb.append(0.0); con_ub.append(max_region_exp)
        row_idx += 1

    A = csc_matrix((A_vals, (A_rows, A_cols)), shape=(row_idx, num_vars))
    constraints = LinearConstraint(A, lb=con_lb, ub=con_ub)

    # ── Step 3: Solve ────────────────────────────────────────────

    result = milp(
        c=c,
        constraints=constraints,
        integrality=integrality,
        bounds=bounds,
    )

    if not result.success:
        return {
            "status": "infeasible",
            "error": "No feasible allocation found. Try relaxing constraints (increase max bank %, decrease min banks, or increase max region %).",
        }

    # ── Step 4: Extract solution ─────────────────────────────────

    x_sol = result.x[:num_x].reshape(n, m)

    assignments = []
    bank_exposure: dict[str, float] = {}
    bank_facility_count: dict[str, int] = {}
    total_opt_cost = 0.0
    total_cur_cost = 0.0

    for i in range(n):
        j_assigned = int(np.argmax(x_sol[i]))
        bk = bank_keys[j_assigned]
        bp_opt = min_spread[i, j_assigned] * 10000
        bp_cur = current_spread[i] * 10000

        bank_exposure[bk] = bank_exposure.get(bk, 0) + ead[i]
        bank_facility_count[bk] = bank_facility_count.get(bk, 0) + 1
        total_opt_cost += min_spread[i, j_assigned] * ead[i]
        total_cur_cost += current_spread[i] * ead[i]

        is_locked = locked.get(i) == bk

        assignments.append({
            "facility": facility_names[i],
            "facility_index": i,
            "bank_key": bk,
            "bank_name": profiles[j_assigned].name,
            "country": profiles[j_assigned].country,
            "exposure": round(ead[i]),
            "min_spread_bp": round(bp_opt, 1),
            "current_spread_bp": round(bp_cur, 1),
            "saving_bp": round(bp_cur - bp_opt, 1),
            "locked": is_locked,
        })

    bank_allocations = []
    for bk in bank_keys:
        if bk in bank_exposure:
            j = bank_keys.index(bk)
            bank_allocations.append({
                "bank_key": bk,
                "bank_name": profiles[j].name,
                "country": profiles[j].country,
                "region": _get_region(profiles[j].country),
                "exposure": round(bank_exposure[bk]),
                "pct": round(bank_exposure[bk] / total_ead * 100, 1),
                "facilities": bank_facility_count[bk],
            })
    bank_allocations.sort(key=lambda x: -x["exposure"])

    saving = total_cur_cost - total_opt_cost
    saving_pct = (saving / total_cur_cost * 100) if total_cur_cost > 0 else 0

    return {
        "status": "optimal",
        "assignments": assignments,
        "summary": {
            "total_min_spread_cost": round(total_opt_cost),
            "current_cost": round(total_cur_cost),
            "saving": round(saving),
            "saving_pct": round(saving_pct, 1),
            "banks_used": len(bank_allocations),
            "total_exposure": round(total_ead),
            "bank_allocations": bank_allocations,
        },
        "constraints": {
            "max_bank_pct": max_bank_pct,
            "min_banks": min_banks,
            "max_region_pct": max_region_pct,
            "locked_count": len(locked),
        },
    }
