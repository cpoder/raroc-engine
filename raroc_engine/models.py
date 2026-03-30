"""Data models for RAROC calculations."""

from dataclasses import dataclass, field
from typing import Optional, Dict, List

# Clean aliases -> CSV product type name prefixes (used for fuzzy matching)
PRODUCT_TYPES: Dict[str, str] = {
    "short_term_credit":     "Short Term Credit Lines",
    "mlt_credit":            "MLT Loan or Credit Lines",
    "leasing":               "Leasing",
    "caution":               "Caution",
    "technical_guarantee":   "Technical First Demand Guarantee",
    "financial_guarantee":   "Financial First Demand Guarantee",
    "import_lc":             "Import Documentary Credit",
    "buyer_supplier_credit": "Buyer or Supplier Credit",
    "export_lc":             "Confirmation of Export LC",
    "forfaiting":            "Forfaiting or Discount Credit Line",
    "ir_swap":               "IR Swap",
    "ir_option":             "IR Option",
    "ccy_swap":              "Cross Currency Swap",
    "ccy_option":            "Cross Currency Option",
    "fx_swap":               "FX Swap",
    "fx_option":             "FX Option",
    "commodities_swap":      "Commodities Swap",
    "commodities_option":    "Commodities Option",
    "otc_swap":              "Other OTC trading Swap",
    "otc_option":            "Other OTC trading Option",
    "forward":               "Forward",
    "spot":                  "Spot",
    "mlt_investment":        "Medium Long Term Investment",
    "st_investment":         "Short Term Investment",
    "cash_management":       "Cash Management",
    "commercial_paper":      "Commercial Paper Program",
    "capital_market":        "Capital Market",
}

# Human-readable descriptions for CLI
PRODUCT_DESCRIPTIONS: Dict[str, str] = {
    "short_term_credit":     "Short-Term Credit Lines (revolving)",
    "mlt_credit":            "Medium/Long-Term Loans or Credit Lines",
    "leasing":               "Leasing",
    "caution":               "Caution (surety bond)",
    "technical_guarantee":   "Technical First Demand Guarantee (Bid/Perf Bond)",
    "financial_guarantee":   "Financial First Demand Guarantee (StandBy LC)",
    "import_lc":             "Import Documentary Credit",
    "buyer_supplier_credit": "Buyer or Supplier Credit",
    "export_lc":             "Confirmation of Export LC",
    "forfaiting":            "Forfaiting / Discount Credit Line",
    "ir_swap":               "Interest Rate Swap",
    "ir_option":             "Interest Rate Option",
    "ccy_swap":              "Cross Currency Swap",
    "ccy_option":            "Cross Currency Option",
    "fx_swap":               "FX Swap",
    "fx_option":             "FX Option",
    "commodities_swap":      "Commodities Swap",
    "commodities_option":    "Commodities Option",
    "forward":               "Forward (FX/Commodities)",
    "spot":                  "Spot Transaction",
}

# Moody's ratings ordered best-to-worst
RATING_ORDER: List[str] = [
    "Aaa", "Aa1", "Aa2", "Aa3", "A1", "A2", "A3",
    "Baa1", "Baa2", "Baa3", "Ba1", "Ba2", "Ba3",
    "B1", "B2", "B3", "Caa1", "Caa2", "Caa3", "Ca", "C",
]

# ── Multi-agency rating mapping ──────────────────────────────────
# Maps S&P, Fitch, and common aliases to canonical Moody's ratings.
# Users can input any of these; the engine normalizes to Moody's internally.

SP_TO_MOODYS: Dict[str, str] = {
    "AAA":  "Aaa",
    "AA+":  "Aa1",
    "AA":   "Aa2",
    "AA-":  "Aa3",
    "A+":   "A1",
    "A":    "A2",
    "A-":   "A3",
    "BBB+": "Baa1",
    "BBB":  "Baa2",
    "BBB-": "Baa3",
    "BB+":  "Ba1",
    "BB":   "Ba2",
    "BB-":  "Ba3",
    "B+":   "B1",
    "B":    "B2",
    "B-":   "B3",
    "CCC+": "Caa1",
    "CCC":  "Caa2",
    "CCC-": "Caa3",
    "CC":   "Ca",
    "C":    "C",
    "D":    "C",
}

# Fitch uses the same scale as S&P
FITCH_TO_MOODYS: Dict[str, str] = SP_TO_MOODYS.copy()

# Reverse: Moody's -> S&P equivalent (for display)
MOODYS_TO_SP: Dict[str, str] = {v: k for k, v in SP_TO_MOODYS.items() if k != "D"}

# All valid rating inputs (any agency)
ALL_VALID_RATINGS: List[str] = RATING_ORDER + list(SP_TO_MOODYS.keys())


def normalize_rating(rating: str) -> str:
    """Convert any rating (S&P, Fitch, Moody's) to canonical Moody's.

    Examples:
        "BBB+" -> "Baa1"
        "A-"   -> "A3"
        "Baa2" -> "Baa2" (already Moody's)
        "aa2"  -> "Aa2"  (case-insensitive)
    """
    r = rating.strip()

    # Already Moody's?
    if r in RATING_ORDER:
        return r

    # Case-insensitive Moody's match
    for m in RATING_ORDER:
        if r.lower() == m.lower():
            return m

    # S&P / Fitch (uppercase for matching)
    upper = r.upper()
    if upper in SP_TO_MOODYS:
        return SP_TO_MOODYS[upper]

    raise ValueError(
        f"Unknown rating: '{rating}'. "
        f"Use Moody's (Aaa-C), S&P (AAA-D), or Fitch (AAA-D)."
    )


@dataclass
class Settings:
    """Global study parameters loaded from settings.csv."""
    start_year: int = 2005
    end_year: int = 2012
    date: str = "01/10/2007"
    risk_free_rate: float = 0.0283
    tax_rate: float = 0.02
    study_name: str = ""
    spot_swap_rate: float = 0.0002


@dataclass
class RAROCInput:
    """All input parameters for a single RAROC deal calculation."""

    # Product type (use keys from PRODUCT_TYPES, e.g. "mlt_credit")
    product_type: str = "mlt_credit"

    # Identification
    operation: str = ""
    bank: str = ""
    bank_group: str = ""
    division: str = ""
    entity: str = ""

    # Volumes (currency units, e.g. EUR)
    initial_volume: float = 0.0
    initial_drawn: float = 0.0
    average_volume: float = 0.0
    average_drawn: float = 0.0

    # Maturity (months)
    initial_maturity: float = 60.0
    residual_maturity: float = 60.0

    # Pricing
    spread: float = 0.0              # as decimal: 0.015 = 150bp
    commitment_fee: float = 0.0      # as decimal on undrawn
    flat_fee: float = 0.0            # absolute amount
    participation_fee: float = 0.0   # absolute amount
    upfront_fee: float = 0.0         # absolute amount
    user_cost: Optional[float] = None  # None = use theoretical cost

    # Collateral / Guarantee
    collateral: str = ""
    collateral_face_value: float = 0.0
    collateral_stress_value: float = 0.0
    global_grr: float = 0.0          # 0.0 to 1.0 (guarantee recovery rate)

    # Facility status
    confirmed: bool = True

    # Credit risk
    rating: str = "Baa1"             # Moody's rating

    # FX
    exchange_rate: float = 1.0


@dataclass
class RAROCOutput:
    """Complete RAROC calculation results with full breakdown."""

    # Echo inputs
    product_type: str = ""
    rating: str = ""
    global_grr: float = 0.0

    # Revenue & Cost
    revenue: float = 0.0
    cost: float = 0.0

    # Credit Risk
    exposure: float = 0.0
    pd: float = 0.0                  # probability of default from rating
    pd_basel2: float = 0.0           # PD adjusted for GRR
    correlation: float = 0.0         # asset correlation R
    maturity_adj_b: float = 0.0      # maturity adjustment factor b
    risk_weight: float = 0.0         # Basel II capital requirement

    # Capital
    fpe: float = 0.0                 # Funds Put at Equity (economic capital)
    average_loss: float = 0.0        # Expected Loss

    # Margins
    gross_margin: float = 0.0
    revenues_of_fpe: float = 0.0     # return on allocated capital
    net_margin: float = 0.0
    taxes: float = 0.0

    # Final
    raroc: float = 0.0               # Risk-Adjusted Return on Capital
