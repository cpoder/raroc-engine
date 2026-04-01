"""FastAPI web backend for the RAROC engine."""

import os
import io
import csv
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import FastAPI, Header, HTTPException, Request, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from .config import EngineConfig
from .banks import BANK_PROFILES, BankProfile, is_premium_loaded, get_free_bank_keys, get_premium_bank_count
from .models import (
    RAROCInput, RAROCOutput, PRODUCT_TYPES, PRODUCT_DESCRIPTIONS,
    RATING_ORDER, MOODYS_TO_SP, normalize_rating,
)
from .repository import Repository
from .calculator import RAROCCalculator
from .analytics import track
from . import benchmarks

app = FastAPI(title="RAROC Engine", version="1.0.0")

# CORS for admin dashboard cross-origin analytics fetch
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://api.openraroc.com", "http://localhost:8001"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

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


class OptimizeRequest(BaseModel):
    facilities: List[DealRequest]
    bank_keys: List[str]
    target_raroc: Optional[float] = None
    max_bank_pct: float = 0.30
    min_banks: int = 3
    max_region_pct: float = 0.50
    locked: Optional[dict] = None  # {"0": "bnp_paribas", "3": "hsbc"}


class ReportRequest(BaseModel):
    facilities: List[DealRequest]
    bank_keys: List[str]
    company_name: str = ""
    target_raroc: Optional[float] = None
    optimize: bool = False
    max_bank_pct: float = 0.40
    min_banks: int = 3
    max_region_pct: float = 0.60


# ── Endpoints ─────────────────────────────────────────────────────

@app.get("/")
async def landing():
    return FileResponse(os.path.join(STATIC_DIR, "landing.html"))


@app.get("/app")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/methodology", response_class=HTMLResponse)
async def methodology():
    """Render METHODOLOGY.md as a styled HTML page."""
    md_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "METHODOLOGY.md")
    if not os.path.isfile(md_path):
        raise HTTPException(404, "Methodology document not found")

    with open(md_path) as f:
        md_text = f.read()

    # Simple markdown to HTML (no external dependency)
    import re
    html = md_text

    # Code blocks
    html = re.sub(r'```(\w*)\n(.*?)```', lambda m: f'<pre><code>{m.group(2).replace("<","&lt;")}</code></pre>', html, flags=re.DOTALL)

    # Tables
    def convert_table(m):
        lines = [l.strip() for l in m.group(0).strip().split('\n') if l.strip()]
        if len(lines) < 2:
            return m.group(0)
        headers = [c.strip() for c in lines[0].split('|') if c.strip()]
        rows = []
        for line in lines[2:]:  # skip separator
            cols = [c.strip() for c in line.split('|') if c.strip()]
            if cols:
                rows.append(cols)
        th = ''.join(f'<th>{h}</th>' for h in headers)
        trs = ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in row) + '</tr>' for row in rows)
        return f'<table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>'

    html = re.sub(r'(?:^\|.+\|$\n?)+', convert_table, html, flags=re.MULTILINE)

    # Headers
    html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
    html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
    html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)

    # Horizontal rules
    html = re.sub(r'^---+$', '<hr>', html, flags=re.MULTILINE)

    # Bold and italic
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
    html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)

    # Inline code
    html = re.sub(r'`([^`]+)`', r'<code class="inline">\1</code>', html)

    # Paragraphs (blank lines)
    html = re.sub(r'\n\n+', '</p><p>', html)
    html = f'<p>{html}</p>'

    # Clean up empty paragraphs around block elements
    for tag in ['h1','h2','h3','hr','pre','table','ul','ol']:
        html = html.replace(f'<p><{tag}', f'<{tag}')
        html = html.replace(f'</{tag}></p>', f'</{tag}>')

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RAROC Calculation Methodology - OpenRAROC</title>
<style>
  :root {{ --bg: #0f172a; --surface: #1e293b; --border: #334155; --text: #e2e8f0; --text2: #94a3b8; --accent: #3b82f6; }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; line-height: 1.7; }}
  .container {{ max-width: 780px; margin: 0 auto; padding: 32px 24px 64px; }}
  a {{ color: var(--accent); text-decoration: none; }}
  .back {{ display: inline-block; margin-bottom: 24px; font-size: 13px; color: var(--text2); }}
  .back:hover {{ color: var(--accent); }}
  h1 {{ font-size: 28px; margin-bottom: 8px; color: #fff; }}
  h2 {{ font-size: 20px; margin: 32px 0 12px; color: #fff; border-bottom: 1px solid var(--border); padding-bottom: 8px; }}
  h3 {{ font-size: 16px; margin: 24px 0 8px; color: #fff; }}
  p {{ margin-bottom: 14px; color: var(--text); }}
  hr {{ border: none; border-top: 1px solid var(--border); margin: 24px 0; }}
  strong {{ color: #fff; }}
  em {{ color: var(--text2); font-style: italic; }}
  pre {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; overflow-x: auto; margin: 14px 0; font-size: 13px; line-height: 1.5; }}
  code {{ font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace; font-size: 13px; }}
  code.inline {{ background: var(--surface); padding: 2px 6px; border-radius: 4px; font-size: 12px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 14px 0; background: var(--surface); border-radius: 8px; overflow: hidden; font-size: 13px; }}
  th {{ text-align: left; padding: 8px 12px; background: rgba(59,130,246,0.1); color: var(--accent); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: 0.3px; }}
  td {{ padding: 8px 12px; border-top: 1px solid var(--border); }}
  tr:hover td {{ background: rgba(59,130,246,0.03); }}
</style>
</head>
<body>
<div class="container">
  <a href="/" class="back">&larr; Back to OpenRAROC</a>
  {html}
</div>
</body>
</html>"""
    return page


@app.post("/api/calculate")
async def calculate(req: DealRequest, x_benchmark_consent: str = Header(default="")):
    try:
        inp = req.to_engine_input()
        out = _calc.calculate(inp)
        track("calculate", product=req.product_type, rating=req.rating, bank=req.bank)
        if x_benchmark_consent == "true":
            benchmarks.record(
                product_type=inp.product_type, rating=inp.rating,
                maturity_months=inp.residual_maturity, spread=inp.spread,
                commitment_fee=inp.commitment_fee, grr=inp.global_grr,
                confirmed=inp.confirmed, raroc=out.raroc, exposure=out.exposure,
            )
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
        track("solve", solve_for=req.solve_for)
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
        track("sensitivity", parameter=req.parameter)
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
async def portfolio(file: UploadFile = File(...), x_benchmark_consent: str = Header(default="")):
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

        track("portfolio_upload", facilities=len(valid), errors=len(facilities) - len(valid))
        if x_benchmark_consent == "true":
            for f in valid:
                inp = f["input"]
                out = f["output"]
                benchmarks.record(
                    product_type=inp["product_type"], rating=inp["rating"],
                    maturity_months=inp["residual_maturity"], spread=inp["spread"],
                    commitment_fee=inp["commitment_fee"], grr=inp["global_grr"],
                    confirmed=inp["confirmed"], raroc=out["raroc"], exposure=out["exposure"],
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
    track("compare_banks", banks=len(req.bank_keys), facilities=len(req.facilities))
    return {"comparisons": results, "facility_count": len(req.facilities)}


@app.post("/api/optimize")
async def optimize(req: OptimizeRequest):
    """Find the optimal allocation of facilities across banks."""
    from .optimizer import optimize_portfolio

    inputs = [f.to_engine_input() for f in req.facilities]
    target = req.target_raroc or _config.target_raroc

    # Convert locked keys from string to int
    locked = {}
    if req.locked:
        for k, v in req.locked.items():
            try:
                locked[int(k)] = v
            except (ValueError, TypeError):
                pass

    try:
        result = optimize_portfolio(
            facilities=inputs,
            bank_keys=req.bank_keys,
            repo=_repo,
            base_config=_config,
            target_raroc=target,
            max_bank_pct=req.max_bank_pct,
            min_banks=req.min_banks,
            max_region_pct=req.max_region_pct,
            locked=locked,
        )
        track("optimize", facilities=len(inputs), banks=len(req.bank_keys), status=result["status"])
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/report")
async def generate_report_endpoint(req: ReportRequest):
    """Generate a PDF credit profile report."""
    from .report import generate_report

    target = req.target_raroc or _config.target_raroc
    inputs = [f.to_engine_input() for f in req.facilities]

    # Calculate portfolio
    facilities_data = []
    total_rev = total_cost = total_el = total_fpe = total_exposure = 0
    for i, (deal, inp) in enumerate(zip(req.facilities, inputs)):
        out = _calc.calculate(inp)
        name = deal.operation or f"Facility {i+1}"
        fac = {"name": name, "input": asdict(inp), "output": asdict(out)}
        facilities_data.append(fac)
        total_rev += out.revenue
        total_cost += out.cost
        total_el += out.average_loss
        total_fpe += out.fpe
        total_exposure += out.exposure

    portfolio_raroc = 0.0
    if total_fpe > 0:
        funding = _config.funding_cost_bp * total_exposure
        portfolio_raroc = (1.0 - _config.bank_tax_rate) * (
            (total_rev - total_cost - funding - total_el) / total_fpe + _config.risk_free_rate
        )

    portfolio_summary = {
        "count": len(facilities_data),
        "total_exposure": total_exposure,
        "total_fpe": total_fpe,
        "total_revenue": total_rev,
        "total_expected_loss": total_el,
        "portfolio_raroc": portfolio_raroc,
    }

    # Bank comparison
    comparisons = []
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
            target_raroc=target,
        )
        calc = RAROCCalculator(_repo, cfg)
        b_rev = b_cost = b_el = b_fpe = b_exp = 0
        for inp in inputs:
            out = calc.calculate(RAROCInput(**asdict(inp)))
            b_rev += out.revenue
            b_cost += out.cost
            b_el += out.average_loss
            b_fpe += out.fpe
            b_exp += out.exposure

        b_raroc = 0.0
        if b_fpe > 0:
            b_funding = cfg.funding_cost_bp * b_exp
            b_raroc = (1.0 - cfg.bank_tax_rate) * (
                (b_rev - b_cost - b_funding - b_el) / b_fpe + cfg.risk_free_rate
            )
        comparisons.append({
            "bank_key": bank_key, "bank_name": profile.name,
            "country": profile.country, "cost_to_income": profile.cost_to_income,
            "tax_rate": profile.effective_tax_rate, "raroc": b_raroc,
            "total_fpe": b_fpe, "total_exposure": b_exp,
            "total_revenue": b_rev, "total_el": b_el,
        })
    comparisons.sort(key=lambda x: -x["raroc"])

    # Optional optimization
    optimization = None
    if req.optimize:
        from .optimizer import optimize_portfolio
        locked = {}
        optimization = optimize_portfolio(
            facilities=inputs, bank_keys=req.bank_keys, repo=_repo, base_config=_config,
            target_raroc=target, max_bank_pct=req.max_bank_pct,
            min_banks=req.min_banks, max_region_pct=req.max_region_pct, locked=locked,
        )

    pdf_bytes = generate_report(
        company_name=req.company_name,
        facilities=facilities_data,
        portfolio_summary=portfolio_summary,
        comparisons=comparisons,
        optimization=optimization,
        config=_config.to_dict(),
    )

    track("report", facilities=len(inputs), banks=len(req.bank_keys), optimize=req.optimize)

    filename = f"openraroc_report_{req.company_name or 'portfolio'}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.pdf"
    filename = filename.replace(" ", "_").lower()

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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


@app.get("/api/analytics")
async def get_analytics(days: int = 30):
    """Usage analytics. No auth required — data is aggregate only, no PII."""
    from .analytics import get_stats
    return get_stats(days)


@app.get("/api/benchmarks")
async def get_benchmarks_endpoint(
    product: str = "",
    rating: str = "",
    maturity_min: int = 0,
    maturity_max: int = 999,
):
    """Anonymous market benchmarks from consenting users."""
    track("benchmark_query", product=product, rating=rating)
    return benchmarks.get_benchmarks(product, rating, maturity_min, maturity_max)


def run_server(host: str = "0.0.0.0", port: int = 8000):
    import uvicorn
    uvicorn.run(app, host=host, port=port)
