"""Per-bank unique commentary generator.

Goal: stop looking like a programmatic-SEO template farm. Each bank page
gets 2–3 paragraphs of genuinely different prose, built by combining:
  1) Hand-written editorial (HAND_WRITTEN dict) when available.
  2) Peer-relative framing — rank within country, deltas vs country/global
     averages, IRB approach implications, cost base tier, PD tier. These
     strings differ meaningfully from bank to bank.

The output is meant to supplement (not replace) the templated intro and
sample RAROC narrative already on the page.
"""

from typing import Dict, List, Tuple

from .banks import BankProfile


# ── Hand-written editorial (optional, per-bank) ──────────────────────
# Seed a few banks with a paragraph that couldn't be inferred from the
# numbers alone. Keep it strictly factual and sourced from the Pillar 3
# narrative or disclosed business-mix commentary.
HAND_WRITTEN: Dict[str, str] = {
    "bnp_paribas": (
        "BNP Paribas runs the largest corporate credit book in continental Europe, with a "
        "diversified mix of French large-cap, global trade finance, and Global Banking US coverage. "
        "Its F-IRB weighting keeps regulatory LGDs closer to the supervisory floor than A-IRB peers, "
        "which structurally inflates capital required on unsecured corporate exposures relative to, "
        "for example, HSBC or Barclays on the same obligor."
    ),
    "hsbc": (
        "HSBC's corporate book is dominated by Asia-Pacific trade finance and UK mid-market lending, "
        "two segments with very different PD-LGD profiles. The consolidated average masks a bimodal "
        "book: short-dated, low-LGD trade claims pull the capital number down, while UK corporate "
        "term lending drives most of the credit RWA. That's why HSBC's sample RAROC on a 5-year "
        "term loan is less flattering than its headline cost-to-income would suggest."
    ),
    "jp_morgan": (
        "JP Morgan reports under the US advanced approaches framework rather than EU CRR, so its "
        "disclosed PD and LGD averages are not strictly comparable to European peers. The bank's "
        "corporate book is heavily skewed toward investment-grade US corporates with revolving "
        "credit facilities, which keeps funded EAD low relative to committed exposure and flatters "
        "RAROC on drawn-equivalent calculations."
    ),
    "deutsche_bank": (
        "Deutsche Bank's Corporate Bank segment has been repositioned since 2019 around transaction "
        "banking and German Mittelstand lending, away from the structured-credit book that drove "
        "pre-2019 capital consumption. The F-IRB designation and relatively high funding spread "
        "versus French or US peers keep its minimum viable spread on BBB+ term lending above the "
        "European median."
    ),
    "goldman_sachs": (
        "Goldman Sachs is not a clearing-style corporate lender; its disclosed corporate EAD is "
        "dominated by relationship-lending facilities tied to investment banking mandates. The "
        "reported RAROC on a standalone BBB+ term loan understates the economics of the full "
        "client relationship, where league-table M&A and capital-markets fees typically cross-"
        "subsidise the lending spread."
    ),
    "ing_group": (
        "ING runs one of the most operationally efficient corporate books in Europe, a legacy of "
        "its digital-first retail platform subsidising the wholesale cost base. Its A-IRB "
        "designation on the bulk of the corporate portfolio produces lower model LGDs than F-IRB "
        "peers, which is the single biggest reason its sample minimum spread screens at the low "
        "end of the Benelux cohort."
    ),
    "ubs": (
        "UBS's corporate exposure is concentrated in Swiss domestic lending and a narrow set of "
        "global wealth-management-adjacent facilities to ultra-high-net-worth operating companies. "
        "The book's average PD is below the European median but LGDs are elevated because most "
        "Swiss corporate loans are unsecured senior, not secured against real-estate collateral."
    ),
    "santander": (
        "Santander's corporate credit profile is the weighted average of three very different "
        "businesses: Spanish large-cap (A-IRB, low PD), Latin American mid-market (higher PD, "
        "higher yield), and Santander CIB global wholesale. The blended numbers in its Pillar 3 "
        "disclosure can make peer comparison misleading — the Spanish-only sub-book would price "
        "tighter than the consolidated number implies."
    ),
    "bbva": (
        "BBVA's disclosed corporate PD sits above most euro-area peers, a direct consequence of "
        "Mexican and Turkish book consolidation rather than a signal of Spanish domestic risk. "
        "Stripping out the emerging-market entities, Spanish corporate pricing at BBVA is "
        "competitive with CaixaBank and Santander Spain on comparable obligors."
    ),
    "barclays": (
        "Barclays runs an A-IRB corporate book with one of the lower average LGDs among "
        "UK large banks, reflecting its bias toward senior unsecured lending to FTSE 350 obligors "
        "where workout recoveries have historically been high. Barclays Investment Bank's US "
        "corporate book is reported separately but consolidates into the same CR6 table."
    ),
}


def _tier(value: float, thresholds: List[Tuple[float, str]]) -> str:
    """Map a value to a tier label based on ascending thresholds."""
    for threshold, label in thresholds:
        if value <= threshold:
            return label
    return thresholds[-1][1]


def _format_pct(x: float) -> str:
    return f"{x*100:.1f}%"


def generate_commentary(
    key: str,
    profile: BankProfile,
    metrics: dict,
    ranked: List[Tuple[str, BankProfile, dict]],
    country_peers: List[Tuple[str, BankProfile, dict]],
) -> str:
    """Return an HTML-safe block of 2–3 paragraphs, unique per bank.

    `ranked` is the full list sorted by RAROC desc.
    `country_peers` is same-country entries (may include the bank itself).
    """
    n_total = len(ranked)
    rank_idx = next((i for i, (k, _, _) in enumerate(ranked) if k == key), 0)
    rank = rank_idx + 1

    # Country context
    country_group = [(k, p, m) for k, p, m in country_peers if k != key]
    n_country = len(country_peers)
    country_rank = None
    if n_country > 1:
        sorted_country = sorted(country_peers, key=lambda r: -r[2]["raroc"])
        country_rank = next((i for i, (k, _, _) in enumerate(sorted_country) if k == key), 0) + 1

    # Global averages
    avg_ci = sum(p.cost_to_income for _, p, _ in ranked) / n_total
    avg_pd = sum(p.corporate_avg_pd for _, p, _ in ranked) / n_total
    avg_lgd = sum(p.avg_lgd_unsecured for _, p, _ in ranked) / n_total

    ci_delta = profile.cost_to_income - avg_ci
    pd_delta = profile.corporate_avg_pd - avg_pd
    lgd_delta = profile.avg_lgd_unsecured - avg_lgd

    # Tiered framing
    ci_tier = _tier(profile.cost_to_income, [
        (0.45, "exceptionally lean"),
        (0.55, "structurally efficient"),
        (0.65, "in line with the European large-bank average"),
        (0.75, "heavier than the cross-bank median"),
        (1.0, "elevated"),
    ])
    pd_tier = _tier(profile.corporate_avg_pd, [
        (0.005, "investment-grade-dominated"),
        (0.015, "predominantly investment-grade"),
        (0.03, "mixed-grade"),
        (0.05, "weighted toward sub-IG obligors"),
        (1.0, "risk-heavy"),
    ])

    # EAD scale tier
    sorted_by_ead = sorted(ranked, key=lambda r: -r[1].corporate_ead_bn)
    ead_rank = next((i for i, (k, _, _) in enumerate(sorted_by_ead) if k == key), 0) + 1
    if ead_rank <= 5:
        ead_phrase = f"one of the five largest corporate credit books in the dataset ({ead_rank}{_ord(ead_rank)} by EAD)"
    elif ead_rank <= 10:
        ead_phrase = f"a top-10 corporate lender by disclosed EAD ({ead_rank}{_ord(ead_rank)})"
    elif ead_rank <= n_total / 2:
        ead_phrase = f"mid-sized by corporate EAD ({ead_rank} of {n_total})"
    else:
        ead_phrase = f"a smaller corporate book by disclosed EAD ({ead_rank} of {n_total})"

    # IRB implication
    irb = profile.irb_approach.upper() if profile.irb_approach else ""
    if "A-IRB" in irb or "AIRB" in irb:
        irb_note = (
            "Because the bank runs the advanced IRB approach, its own LGD and credit-conversion "
            "models drive capital requirements, which on our comparable sample deal typically "
            "produces tighter minimum spreads than foundation-IRB peers with identical obligor risk."
        )
    elif "F-IRB" in irb or "FIRB" in irb:
        irb_note = (
            "Under the foundation IRB approach, supervisory LGDs are applied rather than internal "
            "estimates, which generally inflates credit RWA versus A-IRB banks with the same "
            "obligor mix — a structural headwind this bank carries on every BBB+ term facility."
        )
    elif "MIXED" in irb:
        irb_note = (
            "The consolidated book blends A-IRB and F-IRB sub-portfolios, so the headline PD and "
            "LGD averages mask meaningful dispersion between segments — relevant when benchmarking "
            "specific sectors or geographies."
        )
    else:
        irb_note = (
            "The bank's Pillar 3 disclosure uses a standardised or jurisdiction-specific framework, "
            "which means its reported averages are not directly comparable to EU CRR IRB peers "
            "without adjustment."
        )

    # Paragraph 1 — positioning
    p1 = (
        f"{profile.name} is {ead_phrase}. Its cost-to-income ratio of "
        f"<strong>{_format_pct(profile.cost_to_income)}</strong> is {ci_tier} "
        f"({'+' if ci_delta >= 0 else ''}{ci_delta*100:.1f}pp vs the {n_total}-bank cross-section "
        f"average of {_format_pct(avg_ci)}). The corporate portfolio is {pd_tier}, with an "
        f"EAD-weighted average PD of <strong>{_format_pct(profile.corporate_avg_pd)}</strong> "
        f"against a cross-bank average of {_format_pct(avg_pd)}."
    )

    # Paragraph 2 — IRB note + LGD angle
    lgd_sign = "+" if lgd_delta >= 0 else ""
    p2 = (
        f"{irb_note} Unsecured LGD disclosed at <strong>{_format_pct(profile.avg_lgd_unsecured)}</strong> "
        f"is {lgd_sign}{lgd_delta*100:.1f}pp against the {_format_pct(avg_lgd)} cross-bank average, "
    )
    if lgd_delta > 0.02:
        p2 += "indicating a harder workout profile than the peer median and pushing up capital "
        p2 += "consumption on defaulted exposures."
    elif lgd_delta < -0.02:
        p2 += "indicating recovery assumptions that are more favourable than the peer median — "
        p2 += "often a feature of senior-unsecured lending to large investment-grade obligors."
    else:
        p2 += "in line with the peer median."

    # Paragraph 3 — ranking context
    raroc_pct = metrics["raroc"] * 100
    min_spread = metrics["min_spread_bp"]
    if rank <= 5:
        rank_phrase = f"top-5 (#{rank} of {n_total}) on this standardised deal"
    elif rank <= 10:
        rank_phrase = f"in the top 10 by sample RAROC (#{rank} of {n_total})"
    elif rank <= n_total / 2:
        rank_phrase = f"in the top half of the pricing ranking (#{rank} of {n_total})"
    else:
        rank_phrase = f"in the lower half of the pricing ranking (#{rank} of {n_total})"

    p3 = (
        f"On the standardised BBB+ EUR 25M 5-year term loan used across every bank profile, "
        f"{profile.name} lands {rank_phrase}, with a RAROC of "
        f"<strong>{raroc_pct:.2f}%</strong> and a minimum spread of "
        f"<strong>{min_spread:.0f}bp</strong> to reach the 12% hurdle."
    )
    if country_rank and n_country > 1:
        p3 += (
            f" Within {profile.country} specifically, the bank ranks #{country_rank} of "
            f"{n_country} on this same calculation."
        )

    hand = HAND_WRITTEN.get(key)
    paras = [p1, p2, p3]
    if hand:
        paras.insert(0, hand)

    return "".join(f"<p>{para}</p>" for para in paras)


def _ord(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
