"""FastAPI web backend for the RAROC engine."""

import os
import io
import csv
from dataclasses import asdict
from typing import Optional, List
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from .config import EngineConfig
from .banks import BANK_PROFILES, BankProfile, is_premium_loaded, get_free_bank_keys, get_premium_bank_count
from .models import (
    RAROCInput, RAROCOutput, PRODUCT_TYPES, PRODUCT_DESCRIPTIONS,
    RATING_ORDER, MOODYS_TO_SP, normalize_rating,
)
from .repository import Repository
from .calculator import RAROCCalculator

app = FastAPI(title="RAROC Engine", version="1.0.0")

# Serve static frontend
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Global state
_repo = Repository()
_config = EngineConfig()
_calc = RAROCCalculator(_repo, _config)


def _rebuild_calc():
    global _calc
    _calc = RAROCCalculator(_repo, _config)


# ── Pydantic models ──────────────────────────────────────────────

class DealRequest(BaseModel):
    product_type: str = "mlt_credit"
    operation: str = ""
    bank: str = ""
    average_drawn: float = 0
    average_volume: Optional[float] = None
    spread: float = 0
    commitment_fee: float = 0
    flat_fee: float = 0
    participation_fee: float = 0
    upfront_fee: float = 0
    user_cost: Optional[float] = None
    rating: str = "BBB+"
    residual_maturity: float = 60
    confirmed: bool = True
    global_grr: float = 0
    collateral_stress_value: float = 0

    def to_engine_input(self) -> RAROCInput:
        avg_vol = self.average_volume if self.average_volume is not None else self.average_drawn
        return RAROCInput(
            product_type=self.product_type,
            operation=self.operation,
            bank=self.bank,
            average_drawn=self.average_drawn,
            average_volume=avg_vol,
            initial_maturity=self.residual_maturity,
            residual_maturity=self.residual_maturity,
            spread=self.spread,
            commitment_fee=self.commitment_fee,
            flat_fee=self.flat_fee,
            participation_fee=self.participation_fee,
            upfront_fee=self.upfront_fee,
            user_cost=self.user_cost,
            rating=self.rating,
            confirmed=self.confirmed,
            global_grr=self.global_grr,
            collateral_stress_value=self.collateral_stress_value,
        )


class ConfigRequest(BaseModel):
    regime: Optional[str] = None
    risk_free_rate: Optional[float] = None
    bank_tax_rate: Optional[float] = None
    funding_cost_bp: Optional[float] = None
    output_floor_pct: Optional[float] = None
    pd_floor: Optional[float] = None
    lgd_floor_unsecured: Optional[float] = None
    lgd_floor_secured: Optional[float] = None
    default_collateral_type: Optional[str] = None
    target_raroc: Optional[float] = None


class SolveRequest(BaseModel):
    deal: DealRequest
    target_raroc: Optional[float] = None
    solve_for: str = "spread"  # "spread" or "grr"


class SensitivityRequest(BaseModel):
    deal: DealRequest
    parameter: str = "grr"
    start: Optional[float] = None
    stop: Optional[float] = None
    step: Optional[float] = None


class PortfolioCompareRequest(BaseModel):
    facilities: List[DealRequest]
    bank_keys: List[str]


# ── Endpoints ─────────────────────────────────────────────────────

@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.post("/api/calculate")
async def calculate(req: DealRequest):
    try:
        inp = req.to_engine_input()
        out = _calc.calculate(inp)
        return {
            "input": asdict(inp),
            "output": asdict(out),
            "config": _config.to_dict(),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/solve")
async def solve(req: SolveRequest):
    try:
        inp = req.deal.to_engine_input()
        target = req.target_raroc or _config.target_raroc

        if req.solve_for == "spread":
            result = _calc.solve_spread(inp, target_raroc=target)
            return {
                "solve_for": "spread",
                "target_raroc": target,
                "solved_value": result["solved_spread"],
                "solved_bp": result["solved_spread_bp"],
                "output": asdict(result["output"]),
                "input": asdict(result["input"]),
            }
        elif req.solve_for == "grr":
            result = _calc.solve_grr(inp, target_raroc=target)
            return {
                "solve_for": "grr",
                "target_raroc": target,
                "solved_value": result["solved_grr"],
                "output": asdict(result["output"]),
                "input": asdict(result["input"]),
            }
        else:
            raise HTTPException(400, "solve_for must be 'spread' or 'grr'")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/sensitivity")
async def sensitivity(req: SensitivityRequest):
    try:
        inp = req.deal.to_engine_input()

        defaults = {
            "grr": (0.0, 0.9, 0.1),
            "rating": (-5, 5, 1),
            "spread_delta": (-0.005, 0.01, 0.0025),
            "maturity": (6, 120, 6),
        }
        start = req.start if req.start is not None else defaults.get(req.parameter, (0, 1, 0.1))[0]
        stop = req.stop if req.stop is not None else defaults.get(req.parameter, (0, 1, 0.1))[1]
        step = req.step if req.step is not None else defaults.get(req.parameter, (0, 1, 0.1))[2]

        results = _calc.sensitivity(inp, req.parameter, start, stop, step)

        points = []
        for val, out in results:
            label = f"{val:.0%}" if req.parameter == "grr" else (
                f"{val:+.0f}" if req.parameter == "rating" else (
                    f"{val*10000:+.0f}bp" if req.parameter == "spread_delta" else f"{val:.0f}m"
                )
            )
            rating_name = _repo.roll_rating(inp.rating, int(val)) if req.parameter == "rating" else None
            points.append({
                "value": val,
                "label": label,
                "rating_name": rating_name,
                "raroc": out.raroc,
                "fpe": out.fpe,
                "revenue": out.revenue,
                "exposure": out.exposure,
            })

        # Base case
        base_out = _calc.calculate(inp)
        return {
            "parameter": req.parameter,
            "base_raroc": base_out.raroc,
            "points": points,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/portfolio")
async def portfolio(file: UploadFile = File(...)):
    """Upload a CSV portfolio and get RAROC for every facility."""
    try:
        content = await file.read()
        text = content.decode("utf-8-sig")  # handle BOM
        reader = csv.DictReader(io.StringIO(text))

        facilities = []
        for i, row in enumerate(reader, 1):
            try:
                inp = _parse_portfolio_row(row, i)
                out = _calc.calculate(inp)
                facilities.append({
                    "row": i,
                    "name": row.get("facility_name", row.get("operation", f"Facility {i}")).strip(),
                    "input": asdict(inp),
                    "output": asdict(out),
                })
            except Exception as e:
                facilities.append({
                    "row": i,
                    "name": row.get("facility_name", f"Row {i}"),
                    "error": str(e),
                })

        # Portfolio aggregates
        valid = [f for f in facilities if "output" in f]
        total_revenue = sum(f["output"]["revenue"] for f in valid)
        total_cost = sum(f["output"]["cost"] for f in valid)
        total_el = sum(f["output"]["average_loss"] for f in valid)
        total_fpe = sum(f["output"]["fpe"] for f in valid)
        total_exposure = sum(f["output"]["exposure"] for f in valid)

        portfolio_raroc = 0.0
        if total_fpe > 0:
            tax = _config.bank_tax_rate
            rfr = _config.risk_free_rate
            funding = _config.funding_cost_bp * total_exposure
            portfolio_raroc = (1.0 - tax) * (
                (total_revenue - total_cost - funding - total_el) / total_fpe + rfr
            )

        return {
            "facilities": facilities,
            "portfolio": {
                "count": len(valid),
                "errors": len(facilities) - len(valid),
                "total_exposure": total_exposure,
                "total_fpe": total_fpe,
                "total_revenue": total_revenue,
                "total_cost": total_cost,
                "total_expected_loss": total_el,
                "portfolio_raroc": portfolio_raroc,
            },
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


def _parse_portfolio_row(row: dict, row_num: int) -> RAROCInput:
    """Parse a CSV row into a RAROCInput, accepting user-friendly column names."""
    def _f(val, default=0.0):
        if val is None or str(val).strip() == "":
            return default
        return float(val)

    avg_drawn = _f(row.get("average_drawn"))
    avg_vol = _f(row.get("average_volume")) or avg_drawn

    # Accept spread in bp (user-friendly) or decimal
    spread_bp = _f(row.get("spread_bp"))
    spread = _f(row.get("spread", 0))
    if spread_bp:
        spread = spread_bp / 10000
    elif spread > 0.5:  # likely in bp not decimal
        spread = spread / 10000

    commit_bp = _f(row.get("commitment_fee_bp"))
    commit = _f(row.get("commitment_fee", 0))
    if commit_bp:
        commit = commit_bp / 10000
    elif commit > 0.5:
        commit = commit / 10000

    grr_pct = _f(row.get("grr_pct"))
    grr = _f(row.get("global_grr", 0))
    if grr_pct:
        grr = grr_pct / 100
    elif grr > 1:
        grr = grr / 100

    maturity = _f(row.get("maturity_months")) or _f(row.get("residual_maturity"), 60)

    confirmed_str = str(row.get("confirmed", "true")).strip().lower()
    confirmed = confirmed_str in ("true", "1", "yes", "y", "confirmed")

    return RAROCInput(
        product_type=row.get("product_type", "mlt_credit").strip(),
        operation=row.get("facility_name", row.get("operation", "")).strip(),
        bank=row.get("bank", "").strip(),
        average_drawn=avg_drawn,
        average_volume=avg_vol,
        initial_maturity=maturity,
        residual_maturity=maturity,
        spread=spread,
        commitment_fee=commit,
        flat_fee=_f(row.get("flat_fee")),
        participation_fee=_f(row.get("participation_fee")),
        upfront_fee=_f(row.get("upfront_fee")),
        user_cost=_f(row.get("user_cost"), None) if str(row.get("user_cost", "")).strip() else None,
        rating=row.get("rating", "BBB").strip(),
        confirmed=confirmed,
        global_grr=grr,
        collateral_stress_value=_f(row.get("collateral_stress_value")),
    )


@app.get("/api/template")
async def download_template():
    """Download the sample CSV template."""
    path = os.path.join(STATIC_DIR, "template.csv")
    return FileResponse(path, filename="raroc_portfolio_template.csv", media_type="text/csv")


@app.get("/api/ratings")
async def get_ratings():
    ratings = []
    for name in RATING_ORDER:
        pd = _repo.ratings.get(name, 0)
        sp = MOODYS_TO_SP.get(name, "")
        ratings.append({"moodys": name, "sp": sp, "pd": pd})
    return {"ratings": ratings}


@app.get("/api/products")
async def get_products():
    products = []
    for key, desc in PRODUCT_DESCRIPTIONS.items():
        coeff = _repo.get_revenue_coeff(key)
        products.append({"key": key, "description": desc, "cost_coeff": coeff})
    return {"products": products}


@app.get("/api/banks")
async def get_banks():
    """List available bank profiles with parameters.

    All data is from public Pillar 3 regulatory filings.
    Free-tier users can only use free banks for calculations;
    Pro users can use all banks.
    """
    result = []
    free_keys = get_free_bank_keys()
    for key, p in BANK_PROFILES.items():
        result.append({
            "key": key,
            "name": p.name,
            "country": p.country,
            "confidence": p.confidence,
            "tier": p.tier,
            "irb_approach": p.irb_approach,
            "cost_to_income": p.cost_to_income,
            "effective_tax_rate": p.effective_tax_rate,
            "avg_lgd_unsecured": p.avg_lgd_unsecured,
            "avg_lgd_secured": p.avg_lgd_secured,
            "funding_spread_bp": p.funding_spread_bp,
            "source": p.source,
            "notes": p.notes,
        })
    return {
        "banks": result,
        "total": len(BANK_PROFILES),
        "free_count": len(free_keys),
        "premium_loaded": is_premium_loaded(),
        "premium_count": get_premium_bank_count(),
    }


class CompareRequest(BaseModel):
    deal: DealRequest
    bank_keys: List[str]


@app.post("/api/compare")
async def compare_banks(req: CompareRequest):
    """Calculate RAROC for the same deal across multiple banks."""
    inp = req.deal.to_engine_input()
    results = []

    for bank_key in req.bank_keys:
        profile = BANK_PROFILES.get(bank_key)
        if not profile:
            results.append({"bank_key": bank_key, "error": f"Unknown bank: {bank_key}"})
            continue

        cfg = EngineConfig(
            regime=_config.regime,
            risk_free_rate=_config.risk_free_rate,
            bank_tax_rate=profile.effective_tax_rate,
            funding_cost_bp=profile.funding_spread_bp,
            output_floor_pct=_config.output_floor_pct,
            pd_floor=_config.pd_floor,
            lgd_floor_unsecured=_config.lgd_floor_unsecured,
            lgd_floor_secured=_config.lgd_floor_secured,
            target_raroc=_config.target_raroc,
        )
        calc = RAROCCalculator(_repo, cfg)
        out = calc.calculate(RAROCInput(**asdict(inp)))  # fresh copy

        # Also solve for minimum spread
        solve = calc.solve_spread(RAROCInput(**asdict(inp)), target_raroc=_config.target_raroc)

        results.append({
            "bank_key": bank_key,
            "bank_name": profile.name,
            "country": profile.country,
            "irb_approach": profile.irb_approach,
            "cost_to_income": profile.cost_to_income,
            "tax_rate": profile.effective_tax_rate,
            "funding_bp": profile.funding_spread_bp * 10000,
            "output": asdict(out),
            "min_spread_bp": solve["solved_spread_bp"],
        })

    return {"deal": asdict(inp), "comparisons": results}


@app.post("/api/compare-portfolio")
async def compare_portfolio(req: PortfolioCompareRequest):
    """Compare an entire portfolio across multiple banks."""
    results = []
    for bank_key in req.bank_keys:
        profile = BANK_PROFILES.get(bank_key)
        if not profile:
            continue

        cfg = EngineConfig(
            regime=_config.regime,
            risk_free_rate=_config.risk_free_rate,
            bank_tax_rate=profile.effective_tax_rate,
            funding_cost_bp=profile.funding_spread_bp,
            output_floor_pct=_config.output_floor_pct,
            pd_floor=_config.pd_floor,
            target_raroc=_config.target_raroc,
        )
        calc = RAROCCalculator(_repo, cfg)

        total_rev = total_cost = total_el = total_fpe = total_exposure = 0
        for fac in req.facilities:
            inp = fac.to_engine_input()
            out = calc.calculate(inp)
            total_rev += out.revenue
            total_cost += out.cost
            total_el += out.average_loss
            total_fpe += out.fpe
            total_exposure += out.exposure

        portfolio_raroc = 0.0
        if total_fpe > 0:
            funding = cfg.funding_cost_bp * total_exposure
            portfolio_raroc = (1.0 - cfg.bank_tax_rate) * (
                (total_rev - total_cost - funding - total_el) / total_fpe + cfg.risk_free_rate
            )

        results.append({
            "bank_key": bank_key,
            "bank_name": profile.name,
            "country": profile.country,
            "confidence": profile.confidence,
            "cost_to_income": profile.cost_to_income,
            "tax_rate": profile.effective_tax_rate,
            "raroc": portfolio_raroc,
            "total_fpe": total_fpe,
            "total_exposure": total_exposure,
            "total_revenue": total_rev,
            "total_el": total_el,
        })

    results.sort(key=lambda x: -x["raroc"])
    return {"comparisons": results, "facility_count": len(req.facilities)}


@app.get("/api/config")
async def get_config():
    return _config.to_dict()


@app.post("/api/config")
async def update_config(req: ConfigRequest):
    global _config
    current = _config.to_dict()
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    current.update(updates)
    _config = EngineConfig.from_dict(current)
    _rebuild_calc()
    return _config.to_dict()


def run_server(host: str = "0.0.0.0", port: int = 8000):
    import uvicorn
    uvicorn.run(app, host=host, port=port)
