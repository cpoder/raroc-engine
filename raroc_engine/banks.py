"""Bank profiles built from public Pillar 3 disclosures and annual reports.

All bank data lives in premium_banks.json. Each bank has a "tier" field:
  - "free": included with the open source engine (BNP Paribas, HSBC, Deutsche Bank, JP Morgan)
  - "premium": requires a data license

To load banks, place your `premium_banks.json` file in the project root
or set the RAROC_PREMIUM_BANKS environment variable to its path.

See https://openraroc.com for licensing information.
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
    tier: str = "premium"  # "free" or "premium"


# ═══════════════════════════════════════════════════════════════════
# LOADING: single source from premium_banks.json
# ═══════════════════════════════════════════════════════════════════

_PREMIUM_API_URL = "https://api.openraroc.com/v1/banks"


def _parse_bank_data(data: dict) -> Dict[str, BankProfile]:
    """Parse a dict of bank data into BankProfile objects."""
    banks = {}
    for key, d in data.items():
        banks[key] = BankProfile(**d)
    return banks


def _load_from_file() -> Dict[str, BankProfile]:
    """Try loading banks from a local JSON file."""
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


def _load_from_api() -> Dict[str, BankProfile]:
    """Try loading banks from the remote API."""
    api_key = os.environ.get("RAROC_API_KEY", "")
    if not api_key:
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
        req = urllib.request.Request(
            _PREMIUM_API_URL,
            headers={"Authorization": f"Bearer {api_key}", "User-Agent": "RAROC-Engine/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return _parse_bank_data(data.get("banks", data))
    except Exception:
        return {}


def _load_banks() -> Dict[str, BankProfile]:
    """Load all banks: try local file first, then API."""
    banks = _load_from_file()
    if banks:
        return banks
    return _load_from_api()


# ═══════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════

BANK_PROFILES: Dict[str, BankProfile] = _load_banks()


def get_bank_profile(bank_key: str) -> Optional[BankProfile]:
    return BANK_PROFILES.get(bank_key)


def list_bank_profiles() -> Dict[str, BankProfile]:
    return BANK_PROFILES


def get_free_bank_keys() -> List[str]:
    return [k for k, p in BANK_PROFILES.items() if p.tier == "free"]


def get_premium_bank_count() -> int:
    return sum(1 for p in BANK_PROFILES.values() if p.tier == "premium")


def is_premium_loaded() -> bool:
    return any(p.tier == "premium" for p in BANK_PROFILES.values())
