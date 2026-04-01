"""Anonymous benchmark data collection and aggregation.

Collects anonymized facility-level pricing data from consenting users
to build market benchmarks. No PII is stored — only product type, rating,
maturity, spread, collateral, and exposure bucket.
"""

import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .models import normalize_rating, MOODYS_TO_SP

_DATA_DIR = Path(os.environ.get("RAROC_BENCHMARKS_DIR", "/tmp/raroc_benchmarks"))
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_DATA_PATH = _DATA_DIR / "data.jsonl"


def _exposure_bucket(amount: float) -> str:
    if amount < 1_000_000:
        return "<1M"
    elif amount < 10_000_000:
        return "1-10M"
    elif amount < 50_000_000:
        return "10-50M"
    elif amount < 200_000_000:
        return "50-200M"
    else:
        return "200M+"


def record(
    product_type: str,
    rating: str,
    maturity_months: float,
    spread: float,
    commitment_fee: float,
    grr: float,
    confirmed: bool,
    raroc: float,
    exposure: float,
):
    """Append an anonymized benchmark data point. Never raises."""
    try:
        entry = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "product": product_type,
            "rating": rating,
            "maturity": round(maturity_months),
            "spread_bp": round(spread * 10000, 1),
            "commit_bp": round(commitment_fee * 10000, 1),
            "grr_pct": round(grr * 100, 1),
            "confirmed": confirmed,
            "raroc": round(raroc, 4),
            "bucket": _exposure_bucket(exposure),
        }
        with open(_DATA_PATH, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.write(json.dumps(entry) + "\n")
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except Exception:
        pass


def _load_data() -> list[dict]:
    if not _DATA_PATH.exists():
        return []
    records = []
    with open(_DATA_PATH) as f:
        for line in f:
            try:
                records.append(json.loads(line))
            except Exception:
                continue
    return records


def _percentiles(values: list[float]) -> dict:
    if not values:
        return {}
    arr = np.array(values)
    return {
        "min": round(float(np.min(arr)), 2),
        "p25": round(float(np.percentile(arr, 25)), 2),
        "p50": round(float(np.percentile(arr, 50)), 2),
        "p75": round(float(np.percentile(arr, 75)), 2),
        "max": round(float(np.max(arr)), 2),
        "mean": round(float(np.mean(arr)), 2),
    }


def get_percentile(values: list[float], value: float) -> int:
    """Return the percentile rank of a value within a distribution."""
    if not values:
        return 50
    arr = np.array(values)
    return int(round(float(np.sum(arr <= value) / len(arr) * 100)))


def get_benchmarks(
    product_type: str = "",
    rating: str = "",
    maturity_min: int = 0,
    maturity_max: int = 999,
) -> dict:
    """Compute aggregate benchmarks from stored data.

    Filters by product type, rating, and maturity range.
    Returns percentiles for spread, RAROC, GRR, and maturity.
    """
    all_data = _load_data()

    # Normalize rating to Moody's (data is stored as Moody's)
    if rating:
        rating = normalize_rating(rating)

    filtered = all_data
    if product_type:
        filtered = [d for d in filtered if d.get("product") == product_type]
    if rating:
        filtered = [d for d in filtered if d.get("rating") == rating]
    if maturity_min > 0 or maturity_max < 999:
        filtered = [d for d in filtered if maturity_min <= d.get("maturity", 0) <= maturity_max]

    if not filtered:
        return {
            "query": {"product": product_type, "rating": rating, "maturity_range": [maturity_min, maturity_max]},
            "data_points": 0,
        }

    spreads = [d["spread_bp"] for d in filtered if "spread_bp" in d]
    rarocs = [d["raroc"] for d in filtered if "raroc" in d]
    grrs = [d["grr_pct"] for d in filtered if "grr_pct" in d]
    mats = [d["maturity"] for d in filtered if "maturity" in d]

    # Bucket distribution
    buckets = {}
    for d in filtered:
        b = d.get("bucket", "unknown")
        buckets[b] = buckets.get(b, 0) + 1

    return {
        "query": {"product": product_type, "rating": rating, "maturity_range": [maturity_min, maturity_max]},
        "data_points": len(filtered),
        "spread_bp": _percentiles(spreads),
        "raroc": _percentiles(rarocs),
        "grr_pct": _percentiles(grrs),
        "maturity_months": _percentiles(mats),
        "exposure_buckets": buckets,
    }
