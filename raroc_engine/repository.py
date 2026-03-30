"""Reference data repository - loads from the existing CSV files."""

import os
import csv
from typing import Dict, Tuple, Optional
from .models import Settings, PRODUCT_TYPES, RATING_ORDER


class Repository:
    """Loads and provides access to all RAROC reference data.

    Reads from the CSV files in the repository/ directory that were
    part of the original Java application's HSQLDB database.
    """

    def __init__(self, data_dir: Optional[str] = None):
        if data_dir is None:
            data_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "repository",
            )
        self.data_dir = data_dir

        self.settings = Settings()
        self.ratings: Dict[str, float] = {}
        # product_key -> (other_coeff, revenue_coeff, constant)
        self.cost_coeffs: Dict[str, Tuple[float, float, float]] = {}
        # product_key -> (cad, ca, cg, ncad, nca, ncg)
        self.exposure_coeffs: Dict[str, Tuple[float, float, float, float, float, float]] = {}
        # bank alias -> canonical bank name
        self.banks: Dict[str, str] = {}
        # bank name -> group name
        self.bank_groups: Dict[str, str] = {}

        self._load_all()

    # ── CSV reading ───────────────────────────────────────────────

    def _read_csv(self, filename: str, delimiter: str = ";") -> list:
        filepath = os.path.join(self.data_dir, filename)
        if not os.path.exists(filepath):
            return []
        rows = []
        with open(filepath, "r", encoding="latin-1") as f:
            reader = csv.reader(f, delimiter=delimiter)
            for row in reader:
                rows.append([cell.strip().strip('"') for cell in row])
        return rows

    @staticmethod
    def _normalize(name: str) -> str:
        """Normalize a product type name for fuzzy matching."""
        n = name.strip().strip('"').lower()
        # Cut off parenthetical descriptions
        if "(" in n:
            n = n[: n.index("(")].strip()
        return n

    # ── Loaders ───────────────────────────────────────────────────

    def _load_all(self):
        self._load_settings()
        self._load_ratings()
        self._load_cost_coeffs()
        self._load_exposure_coeffs()
        self._load_banks()
        self._load_bank_groups()

    def _load_settings(self):
        rows = self._read_csv("settings.csv")
        d: Dict[str, str] = {}
        for row in rows[1:]:
            if len(row) >= 2 and row[0]:
                d[row[0]] = row[1]

        self.settings = Settings(
            start_year=int(d.get("startYear", "2005")),
            end_year=int(d.get("endYear", "2012")),
            date=d.get("date", "01/10/2007"),
            risk_free_rate=float(d.get("riskFreeRate", "0.0283")),
            tax_rate=float(d.get("taxRate", "0.02")),
            study_name=d.get("studyName", ""),
            spot_swap_rate=float(d.get("spotSwapRate", "0.0002")),
        )

    def _load_ratings(self):
        rows = self._read_csv("ratings.csv")
        for row in rows[1:]:
            if len(row) >= 3 and row[1]:
                self.ratings[row[1]] = float(row[2])

    def _load_cost_coeffs(self):
        rows = self._read_csv("cost_calculation_coeffs.csv")
        for row in rows[1:]:
            if len(row) >= 5 and row[0]:
                try:
                    other = float(row[2]) if row[2] else 0.0
                    rev = float(row[3]) if row[3] else 0.0
                    const = float(row[4]) if row[4] else 0.0
                    self.cost_coeffs[self._normalize(row[0])] = (other, rev, const)
                except ValueError:
                    pass

    def _load_exposure_coeffs(self):
        rows = self._read_csv("exposure_calculation_coeffs.csv")
        for row in rows[1:]:
            if len(row) >= 8 and row[0]:
                try:
                    vals = []
                    for i in range(2, 8):
                        vals.append(float(row[i]) if row[i] else 0.0)
                    self.exposure_coeffs[self._normalize(row[0])] = tuple(vals)  # type: ignore
                except ValueError:
                    pass

    def _load_banks(self):
        rows = self._read_csv("banks.csv")
        for row in rows[1:]:
            if len(row) >= 2 and row[0]:
                self.banks[row[0].strip()] = row[1].strip()

    def _load_bank_groups(self):
        rows = self._read_csv("bank_groups.csv")
        for row in rows[1:]:
            if len(row) >= 2 and row[0]:
                self.bank_groups[row[0].strip()] = row[1].strip()

    # ── Lookup methods ────────────────────────────────────────────

    def get_rating_value(self, rating_name: str) -> float:
        """Get probability of default for a Moody's rating."""
        if rating_name in self.ratings:
            return self.ratings[rating_name]
        raise ValueError(
            f"Unknown rating: '{rating_name}'. "
            f"Valid ratings: {', '.join(RATING_ORDER)}"
        )

    def roll_rating(self, rating_name: str, notches: int) -> str:
        """Shift a rating by N notches. Positive = downgrade, negative = upgrade."""
        if rating_name not in RATING_ORDER:
            return rating_name
        idx = RATING_ORDER.index(rating_name)
        new_idx = max(0, min(len(RATING_ORDER) - 1, idx + notches))
        return RATING_ORDER[new_idx]

    def _resolve_product_key(self, product_type: str) -> str:
        """Resolve a product type alias to a normalized CSV key."""
        # If it's a clean alias, get the CSV name
        if product_type in PRODUCT_TYPES:
            return self._normalize(PRODUCT_TYPES[product_type])
        # Otherwise normalize directly
        return self._normalize(product_type)

    def _find_in_dict(self, target: str, candidates: dict):
        """Fuzzy prefix match in a dictionary."""
        key = self._resolve_product_key(target)

        # Exact match
        if key in candidates:
            return candidates[key]

        # Prefix match (either direction)
        for k, v in candidates.items():
            if k.startswith(key) or key.startswith(k):
                return v

        # Substring match
        for k, v in candidates.items():
            if key in k or k in key:
                return v

        return None

    def get_revenue_coeff(self, product_type: str) -> float:
        """Get the revenue-to-cost coefficient for theoretical cost."""
        result = self._find_in_dict(product_type, self.cost_coeffs)
        if result is not None:
            return result[1]  # revenue_coeff
        return 0.4  # default for credit products

    def get_exposure_coeffs(
        self, product_type: str, confirmed: bool
    ) -> Tuple[float, float, float]:
        """Get (coef_avg_drawn, coef_authorisation, coef_guarantee)."""
        result = self._find_in_dict(product_type, self.exposure_coeffs)
        if result is not None:
            if confirmed:
                return result[0], result[1], result[2]
            else:
                return result[3], result[4], result[5]
        # Default for confirmed credit
        if confirmed:
            return 0.25, 0.75, -1.0
        return 1.0, 0.0, -1.0

    def resolve_bank_group(self, bank_name: str) -> str:
        """Resolve a bank alias to its group name."""
        canonical = self.banks.get(bank_name, bank_name)
        return self.bank_groups.get(canonical, canonical)
