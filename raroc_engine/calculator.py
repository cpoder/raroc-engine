"""Core RAROC calculation engine.

Implements both Basel II (original BFinance formulas) and Basel III/IV
(CRR3, 2023 finalization) risk weight calculations.

All regulatory and market parameters are configurable via EngineConfig.
"""

import math
from dataclasses import asdict
from scipy.stats import norm
from scipy.optimize import brentq
from .models import RAROCInput, RAROCOutput, RATING_ORDER, normalize_rating
from .config import EngineConfig
from .repository import Repository


class RAROCCalculator:
    """Risk-Adjusted Return on Capital calculator.

    All parameters are configurable via the EngineConfig object.

    Usage:
        repo = Repository()
        config = EngineConfig(regime="basel3", risk_free_rate=0.035)
        calc = RAROCCalculator(repo, config)
        result = calc.calculate(deal_input)
    """

    def __init__(self, repository: Repository = None, config: EngineConfig = None):
        self.repo = repository or Repository()
        self.cfg = config or EngineConfig()

    def calculate(self, inp: RAROCInput) -> RAROCOutput:
        """Calculate full RAROC for a single deal."""
        inp.rating = normalize_rating(inp.rating)

        out = RAROCOutput()
        out.product_type = inp.product_type
        out.rating = inp.rating
        out.global_grr = inp.global_grr

        # 1. Revenue
        out.revenue = self._revenue(inp)

        # 2. Cost
        out.cost = self._cost(inp, out.revenue)

        # 3. Exposure at Default
        out.exposure = self._exposure(inp)

        # 4. Probability of Default
        out.pd = self.repo.get_rating_value(inp.rating)
        if self.cfg.regime == "basel3":
            out.pd = max(out.pd, self.cfg.pd_floor)

        # 5. Basel PD (adjusted for guarantee recovery)
        out.pd_basel2 = out.pd * (1.0 - inp.global_grr)

        # 6. Risk Weight (IRB capital requirement K)
        out.correlation, out.maturity_adj_b, out.risk_weight = self._risk_weight(
            inp, out.pd
        )

        # 7. FPE = Exposure * K
        out.fpe = out.exposure * out.risk_weight

        # 8. Expected Loss
        out.average_loss = out.exposure * out.pd_basel2

        # 9. Margins (include funding cost)
        funding_cost = self.cfg.funding_cost_bp * out.exposure
        out.gross_margin = out.revenue - out.cost - funding_cost
        out.revenues_of_fpe = self.cfg.risk_free_rate * out.fpe
        out.net_margin = out.gross_margin - out.average_loss + out.revenues_of_fpe

        # 10. Taxes
        out.taxes = out.net_margin * self.cfg.bank_tax_rate

        # 11. RAROC
        if out.fpe > 0:
            tax = self.cfg.bank_tax_rate
            rfr = self.cfg.risk_free_rate
            out.raroc = (1.0 - tax) * (
                (out.revenue - out.cost - funding_cost - out.average_loss)
                / out.fpe
                + rfr
            )

        return out

    # ── Revenue ───────────────────────────────────────────────────

    def _revenue(self, inp: RAROCInput) -> float:
        spread = inp.spread or 0.0
        avg_drawn = inp.average_drawn or 0.0
        commit_fee = inp.commitment_fee or 0.0
        avg_vol = inp.average_volume or 0.0
        flat = inp.flat_fee or 0.0
        part = inp.participation_fee or 0.0
        up = inp.upfront_fee or 0.0

        return (
            spread * avg_drawn
            + commit_fee * (avg_vol - avg_drawn)
            + flat + part + up
        )

    # ── Cost ──────────────────────────────────────────────────────

    def _cost(self, inp: RAROCInput, revenue: float) -> float:
        if inp.user_cost is not None:
            return inp.user_cost
        coeff = self.repo.get_revenue_coeff(inp.product_type)
        return revenue * coeff

    # ── Exposure at Default ───────────────────────────────────────

    def _exposure(self, inp: RAROCInput) -> float:
        avg_drawn = inp.average_drawn or 0.0
        avg_vol = inp.average_volume or 0.0
        col_stress = inp.collateral_stress_value or 0.0

        cad, ca, cg = self.repo.get_exposure_coeffs(inp.product_type, inp.confirmed)
        return cad * avg_drawn + ca * avg_vol + cg * col_stress

    # ── Risk Weight (Basel II / III IRB) ──────────────────────────

    def _risk_weight(self, inp: RAROCInput, pd: float) -> tuple:
        """Compute (correlation R, maturity adjustment b, risk_weight K)."""
        grr = inp.global_grr
        lgd = 1.0 - grr
        maturity_years = inp.residual_maturity / 12.0

        if self.cfg.regime == "basel3":
            pd = max(pd, self.cfg.pd_floor)
            coll_type = "none" if grr == 0 else self.cfg.default_collateral_type
            lgd_floor = self.cfg.get_lgd_floor(coll_type)
            lgd = max(lgd, lgd_floor)

        # Asset correlation R -- BIS CRE31
        R = (
            0.12
            * (1.0 + math.exp(-50.0 * pd) - 2.0 * math.exp(-50.0))
            / (1.0 - math.exp(-50.0))
        )

        # Maturity adjustment b
        b = (0.11852 - 0.05478 * math.log(pd)) ** 2

        # Capital requirement K
        z = (
            math.sqrt(1.0 / (1.0 - R)) * norm.ppf(pd)
            + math.sqrt(R / (1.0 - R)) * norm.ppf(0.999)
        )
        K = (
            lgd
            * (norm.cdf(z) - pd)
            * (1.0 + (maturity_years - 2.5) * b)
            / (1.0 - 1.5 * b)
        )

        # Basel III output floor
        if self.cfg.regime == "basel3":
            sa_rw = self._standardised_risk_weight(pd)
            K_floor = self.cfg.output_floor_pct * sa_rw / 12.5
            K = max(K, K_floor)

        return R, b, K

    @staticmethod
    def _standardised_risk_weight(pd: float) -> float:
        """Basel III SA risk weight for corporates (BIS d424 Table 5)."""
        if pd <= 0.0005:
            return 0.20
        elif pd <= 0.0015:
            return 0.50
        elif pd <= 0.0075:
            return 0.75
        elif pd <= 0.03:
            return 1.00
        else:
            return 1.50

    # ── Sensitivity analysis ──────────────────────────────────────

    def sensitivity(self, inp: RAROCInput, parameter: str,
                    start: float, stop: float, step: float) -> list:
        results = []
        val = start
        while val <= stop + step * 0.001:
            modified = self._apply_delta(inp, parameter, val)
            out = self.calculate(modified)
            results.append((val, out))
            val += step
        return results

    def _apply_delta(self, inp: RAROCInput, parameter: str, value: float) -> RAROCInput:
        d = asdict(inp)
        modified = RAROCInput(**d)

        if parameter == "grr":
            modified.global_grr = max(0.0, min(1.0, value))
        elif parameter == "rating":
            modified.rating = self.repo.roll_rating(inp.rating, int(value))
        elif parameter == "spread":
            modified.spread = value
        elif parameter == "spread_delta":
            modified.spread = inp.spread + value
        elif parameter == "maturity":
            modified.residual_maturity = max(1.0, value)
            modified.initial_maturity = max(modified.initial_maturity, value)
        elif parameter == "average_drawn":
            modified.average_drawn = value
        elif parameter == "cost_pct":
            if inp.user_cost is not None:
                modified.user_cost = inp.user_cost * (1.0 + value)
        elif parameter == "revenue_pct":
            factor = 1.0 + value
            modified.spread = inp.spread * factor
            modified.commitment_fee = inp.commitment_fee * factor
            modified.flat_fee = inp.flat_fee * factor
            modified.participation_fee = inp.participation_fee * factor
            modified.upfront_fee = inp.upfront_fee * factor

        return modified

    # ── Reverse RAROC solver ─────────────────────────────────────

    def solve_spread(self, inp: RAROCInput, target_raroc: float = None,
                     spread_min: float = 0.0, spread_max: float = 0.10) -> dict:
        target = target_raroc if target_raroc is not None else self.cfg.target_raroc

        def objective(spread_val):
            d = asdict(inp)
            trial = RAROCInput(**d)
            trial.spread = spread_val
            return self.calculate(trial).raroc - target

        lo, hi = objective(spread_min), objective(spread_max)
        if lo > 0:
            solved = spread_min
        elif hi < 0:
            solved = spread_max
        else:
            solved = brentq(objective, spread_min, spread_max, xtol=1e-8)

        d = asdict(inp)
        final_inp = RAROCInput(**d)
        final_inp.spread = solved
        final_out = self.calculate(final_inp)

        return {
            "target_raroc": target,
            "solved_spread": solved,
            "solved_spread_bp": solved * 10000,
            "output": final_out,
            "input": final_inp,
        }

    def solve_grr(self, inp: RAROCInput, target_raroc: float = None) -> dict:
        target = target_raroc if target_raroc is not None else self.cfg.target_raroc

        def objective(grr_val):
            d = asdict(inp)
            trial = RAROCInput(**d)
            trial.global_grr = grr_val
            return self.calculate(trial).raroc - target

        lo, hi = objective(0.0), objective(0.95)
        if lo > 0:
            solved = 0.0
        elif hi < 0:
            solved = 0.95
        else:
            solved = brentq(objective, 0.0, 0.95, xtol=1e-6)

        d = asdict(inp)
        final_inp = RAROCInput(**d)
        final_inp.global_grr = solved
        final_out = self.calculate(final_inp)

        return {
            "target_raroc": target,
            "solved_grr": solved,
            "output": final_out,
            "input": final_inp,
        }
