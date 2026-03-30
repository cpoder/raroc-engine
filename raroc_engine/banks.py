"""Bank profiles built from public Pillar 3 disclosures and annual reports.

The RAROC Engine includes 4 bank profiles for free (open source).
Full coverage (35+ banks across 13 countries) requires a premium data license.

To load premium banks, place your `premium_banks.json` file in the project root
or set the RAROC_PREMIUM_BANKS environment variable to its path.

Free banks: BNP Paribas, HSBC, Deutsche Bank, JP Morgan
Premium: All other European, US, and Chinese banks

See https://raroc-engine.com for licensing information.
"""

import os
import json
from dataclasses import dataclass, asdict
from typing import Dict, Optional, List


@dataclass
class BankProfile:
    """Bank-specific parameters from public disclosures."""
    name: str
    country: str
    irb_approach: str
    cost_to_income: float
    effective_tax_rate: float
    avg_lgd_unsecured: float
    avg_lgd_secured: float
    funding_spread_bp: float
    corporate_ead_bn: float
    corporate_avg_pd: float
    source: str
    confidence: str = "high"
    notes: str = ""
    tier: str = "free"  # "free" or "premium"


# ═══════════════════════════════════════════════════════════════════
# FREE TIER: 4 banks included with open source engine
# ═══════════════════════════════════════════════════════════════════

FREE_BANKS: Dict[str, BankProfile] = {

    "bnp_paribas": BankProfile(
        name="BNP Paribas", country="France", irb_approach="A-IRB",
        cost_to_income=0.618, effective_tax_rate=0.262,
        avg_lgd_unsecured=0.37, avg_lgd_secured=0.20,
        funding_spread_bp=0.0015,
        corporate_ead_bn=260, corporate_avg_pd=0.0221,
        source="BNP Paribas URD 2025 Ch.5 CR6; FY25 Results",
        confidence="high", tier="free",
        notes="Corp-Other A-IRB: EAD 260bn, PD 2.21%, LGD 37%. FY2025.",
    ),
    "hsbc": BankProfile(
        name="HSBC", country="United Kingdom", irb_approach="A-IRB",
        cost_to_income=0.502, effective_tax_rate=0.226,
        avg_lgd_unsecured=0.459, avg_lgd_secured=0.25,
        funding_spread_bp=0.0010,
        corporate_ead_bn=25, corporate_avg_pd=0.0042,
        source="HSBC Pillar 3 31 Dec 2025 CR6; FY25 Annual Report",
        confidence="high", tier="free",
        notes="AIRB Corp: EAD $25bn, PD 0.42%, LGD 45.9%, mat 1.1y. FY2025.",
    ),
    "deutsche_bank": BankProfile(
        name="Deutsche Bank", country="Germany", irb_approach="Mixed",
        cost_to_income=0.76, effective_tax_rate=0.34,
        avg_lgd_unsecured=0.3927, avg_lgd_secured=0.1690,
        funding_spread_bp=0.0025,
        corporate_ead_bn=129, corporate_avg_pd=0.0256,
        source="Deutsche Bank Pillar 3 FY2025 CR6; FY25 Results",
        confidence="high", tier="free",
        notes="Corp-Other: EAD 129bn, PD 2.56%, LGD 39.27%, mat 2.5y. FY2025.",
    ),
    "jp_morgan": BankProfile(
        name="JP Morgan", country="United States", irb_approach="A-IRB",
        cost_to_income=0.55, effective_tax_rate=0.24,
        avg_lgd_unsecured=0.2216, avg_lgd_secured=0.15,
        funding_spread_bp=0.0010,
        corporate_ead_bn=2019, corporate_avg_pd=0.0132,
        source="JPM Pillar 3 Q2 2025 Wholesale Table; Annual Report",
        confidence="high", tier="free",
        notes="Wholesale: EAD $2.0tn, PD 1.32%, LGD 22.16%. RW 28.33%. US Basel.",
    ),
}


# ═══════════════════════════════════════════════════════════════════
# PREMIUM TIER: loaded from local file OR remote API
# ═══════════════════════════════════════════════════════════════════

_PREMIUM_API_URL = "https://api.raroc-engine.com/v1/banks"


def _parse_bank_data(data: dict) -> Dict[str, BankProfile]:
    """Parse a dict of bank data into BankProfile objects."""
    banks = {}
    for key, d in data.items():
        d["tier"] = "premium"
        banks[key] = BankProfile(**d)
    return banks


def _load_premium_from_file() -> Dict[str, BankProfile]:
    """Try loading premium banks from a local JSON file."""
    path = os.environ.get("RAROC_PREMIUM_BANKS")

    if not path:
        candidates = [
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "premium_banks.json"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "premium_banks.json"),
            os.path.expanduser("~/.raroc/premium_banks.json"),
        ]
        for c in candidates:
            if os.path.exists(c):
                path = c
                break

    if not path or not os.path.exists(path):
        return {}

    try:
        with open(path, "r") as f:
            return _parse_bank_data(json.load(f))
    except Exception:
        return {}


def _load_premium_from_api() -> Dict[str, BankProfile]:
    """Try loading premium banks from the remote API."""
    api_key = os.environ.get("RAROC_API_KEY", "")
    if not api_key:
        # Check ~/.raroc/config for saved key
        config_path = os.path.expanduser("~/.raroc/config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path) as f:
                    api_key = json.load(f).get("api_key", "")
            except Exception:
                pass

    if not api_key:
        return {}

    try:
        import urllib.request
        import urllib.error
        req = urllib.request.Request(
            _PREMIUM_API_URL,
            headers={"Authorization": f"Bearer {api_key}", "User-Agent": "RAROC-Engine/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return _parse_bank_data(data.get("banks", data))
    except Exception:
        return {}


def _load_premium_banks() -> Dict[str, BankProfile]:
    """Load premium banks: try local file first, then API."""
    banks = _load_premium_from_file()
    if banks:
        return banks
    return _load_premium_from_api()


# ═══════════════════════════════════════════════════════════════════
# COMBINED: Free + Premium
# ═══════════════════════════════════════════════════════════════════

BANK_PROFILES: Dict[str, BankProfile] = {}
BANK_PROFILES.update(FREE_BANKS)
BANK_PROFILES.update(_load_premium_banks())


def get_bank_profile(bank_key: str) -> Optional[BankProfile]:
    return BANK_PROFILES.get(bank_key)


def list_bank_profiles() -> Dict[str, BankProfile]:
    return BANK_PROFILES


def get_free_bank_keys() -> List[str]:
    return list(FREE_BANKS.keys())


def get_premium_bank_count() -> int:
    return len(BANK_PROFILES) - len(FREE_BANKS)


def is_premium_loaded() -> bool:
    return len(BANK_PROFILES) > len(FREE_BANKS)
