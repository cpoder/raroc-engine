"""Runtime configuration for the RAROC engine.

All parameters that a user might want to adjust are centralized here.
The web UI exposes these as settings; the CLI reads from settings.csv.
"""

from dataclasses import dataclass, field, asdict
from typing import Optional, Dict


@dataclass
class EngineConfig:
    """All configurable RAROC engine parameters."""

    # ── Regulatory regime ─────────────────────────────────────────
    regime: str = "basel3"  # "basel2" or "basel3"

    # ── Market parameters ─────────────────────────────────────────
    risk_free_rate: float = 0.0325      # EUR mid-swap or govt bond yield
    bank_tax_rate: float = 0.25         # Bank's effective corporate tax rate
    funding_cost_bp: float = 0.0        # Bank's funding spread over risk-free (bp as decimal, e.g. 0.001 = 10bp)

    # ── Cost model ────────────────────────────────────────────────
    # "percentage" = cost is a % of revenue (original model)
    # "fixed" = user provides absolute cost
    cost_model: str = "percentage"
    default_cost_income_ratio: float = 0.40  # for credit products
    derivative_cost_income_ratio: float = 0.75  # for derivative products

    # ── Basel III specific ────────────────────────────────────────
    # Output floor phase-in: 2025=50%, 2026=55%, 2027=60%, 2028=65%, 2029=70%, 2030+=72.5%
    output_floor_pct: float = 0.55
    pd_floor: float = 0.0005            # 5bp
    lgd_floor_unsecured: float = 0.25
    lgd_floor_secured: float = 0.10     # receivables / real estate
    lgd_floor_financial_coll: float = 0.0

    # ── Collateral type for LGD floor ─────────────────────────────
    # "none", "financial", "receivables", "real_estate", "other_physical"
    default_collateral_type: str = "receivables"

    # ── Bank's target RAROC (for solver) ──────────────────────────
    target_raroc: float = 0.12          # 12% -- typical European bank hurdle

    # ── Bank profile (optional) ──────────────────────────────────
    bank_profile: str = ""              # key from BANK_PROFILES, e.g. "bnp_paribas"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "EngineConfig":
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in d.items() if k in valid_fields}
        return cls(**filtered)

    def apply_bank_profile(self, profile_key: str):
        """Apply a bank profile's parameters to this config."""
        from .banks import get_bank_profile
        p = get_bank_profile(profile_key)
        if p is None:
            return
        self.bank_profile = profile_key
        self.bank_tax_rate = p.effective_tax_rate
        self.funding_cost_bp = p.funding_spread_bp

    def get_lgd_floor(self, collateral_type: str = None) -> float:
        """Get LGD floor based on collateral type."""
        ct = collateral_type or self.default_collateral_type
        if ct == "financial":
            return self.lgd_floor_financial_coll
        elif ct in ("receivables", "real_estate"):
            return self.lgd_floor_secured
        elif ct == "other_physical":
            return 0.15
        elif ct == "none":
            return self.lgd_floor_unsecured
        return self.lgd_floor_unsecured
