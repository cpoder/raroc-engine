"""Bank-vs-bank comparison pages.

URL pattern: /compare/{bank-a-slug}-vs-{bank-b-slug}
e.g. /compare/bnp-paribas-vs-deutsche-bank

Targets queries like "BNP Paribas vs Deutsche Bank cost of capital",
"HSBC vs Barclays corporate lending pricing".

Any pair of banks in the dataset will render on demand. The sitemap
only advertises a curated list of high-value pairs to avoid spam.
"""

from typing import List, Optional, Tuple

from .banks import BANK_PROFILES, BankProfile
from .bank_pages import (
    PAGE_CSS,
    nav_html,
    footer_html,
    slug_for_key,
    key_for_slug,
    format_bn,
    _calc_for_bank,
    _ranked_banks,
)


def parse_compare_slug(slug: str) -> Optional[Tuple[str, str]]:
    """Split 'bnp-paribas-vs-deutsche-bank' into (bnp_paribas, deutsche_bank)."""
    if "-vs-" not in slug:
        return None
    parts = slug.split("-vs-", 1)
    if len(parts) != 2:
        return None
    a = key_for_slug(parts[0])
    b = key_for_slug(parts[1])
    if not a or not b or a == b:
        return None
    return a, b


def curated_pairs() -> List[Tuple[str, str]]:
    """Generate a curated list of high-value comparison pairs.

    Strategy: top 2 banks (by EAD) within each country yields one pair per
    country, plus a few cross-country marquee matchups.
    """
    by_country = {}
    for k, p in BANK_PROFILES.items():
        by_country.setdefault(p.country, []).append((k, p))

    pairs: List[Tuple[str, str]] = []
    for country, banks in by_country.items():
        if len(banks) < 2:
            continue
        banks_sorted = sorted(banks, key=lambda kp: -kp[1].corporate_ead_bn)
        top = banks_sorted[:3]
        # Top-2 pair
        pairs.append((top[0][0], top[1][0]))
        # Top-1 vs top-3 if available
        if len(top) >= 3:
            pairs.append((top[0][0], top[2][0]))

    # Cross-country marquee matchups
    marquee = [
        ("bnp_paribas", "deutsche_bank"),
        ("bnp_paribas", "hsbc"),
        ("hsbc", "jp_morgan"),
        ("deutsche_bank", "ubs"),
        ("societe_generale", "credit_agricole"),
        ("santander", "bbva"),
        ("ing_group", "abn_amro"),
        ("intesa_sanpaolo", "unicredit"),
        ("barclays", "hsbc"),
        ("jp_morgan", "bank_of_america"),
    ]
    for a, b in marquee:
        if a in BANK_PROFILES and b in BANK_PROFILES and (a, b) not in pairs and (b, a) not in pairs:
            pairs.append((a, b))

    return pairs


def all_compare_slugs() -> List[str]:
    return [f"{slug_for_key(a)}-vs-{slug_for_key(b)}" for a, b in curated_pairs()]


def render_compare_page(key_a: str, key_b: str) -> Optional[str]:
    pa = BANK_PROFILES.get(key_a)
    pb = BANK_PROFILES.get(key_b)
    if not pa or not pb:
        return None

    ma = _calc_for_bank(pa)
    mb = _calc_for_bank(pb)

    slug = f"{slug_for_key(key_a)}-vs-{slug_for_key(key_b)}"
    canonical = f"https://openraroc.com/compare/{slug}"

    # Determine winner on RAROC (higher = better for the bank, lower min-spread = cheaper for borrower)
    cheaper_bank = pa if ma["min_spread_bp"] < mb["min_spread_bp"] else pb
    cheaper_spread = min(ma["min_spread_bp"], mb["min_spread_bp"])
    other_spread = max(ma["min_spread_bp"], mb["min_spread_bp"])
    spread_diff = other_spread - cheaper_spread

    def cell(label: str, value_a, value_b, lower_is_better=True, fmt="{}"):
        a_better = (value_a < value_b) if lower_is_better else (value_a > value_b)
        cls_a = "winner" if a_better else ""
        cls_b = "winner" if not a_better else ""
        return (
            f'<tr><td>{label}</td>'
            f'<td class="num {cls_a}">{fmt.format(value_a)}</td>'
            f'<td class="num {cls_b}">{fmt.format(value_b)}</td></tr>'
        )

    title = f"{pa.name} vs {pb.name}: RAROC & Credit Pricing Comparison | OpenRAROC"
    description = (
        f"Side-by-side comparison of {pa.name} and {pb.name} on a BBB+ EUR 25M corporate term loan. "
        f"{pa.name} min spread {ma['min_spread_bp']:.0f}bp vs {pb.name} {mb['min_spread_bp']:.0f}bp. "
        "Real Pillar 3 data."
    )

    verdict = (
        f"On a representative BBB+ EUR 25M 5-year term loan, "
        f"<strong>{cheaper_bank.name}</strong> is the cheaper lender by {spread_diff:.0f}bp "
        f"in minimum spread. For a EUR 25M facility, that's "
        f"EUR {spread_diff * 25_000_000 / 10000:,.0f} per year."
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<meta name="description" content="{description}">
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="article">
<meta property="og:url" content="{canonical}">
<meta property="og:title" content="{pa.name} vs {pb.name}: RAROC Comparison">
<meta property="og:description" content="{description}">
<meta property="og:site_name" content="OpenRAROC">
<style>
{PAGE_CSS}
.compare-table td.winner {{ background:rgba(34,197,94,0.12); color:#fff; font-weight:700; }}
.compare-table th.bank-col {{ color:#fff; font-size:13px; text-transform:none; letter-spacing:0; padding:14px; }}
</style>
</head>
<body>
{nav_html()}
<div class="container">
  <div class="crumbs"><a href="/">Home</a> / <a href="/banks">Banks</a> / Comparison</div>
  <h1>{pa.name} vs {pb.name}</h1>
  <p class="subtitle">Side-by-side credit pricing comparison from Pillar 3 disclosures.</p>

  <div class="callout">
    <strong>Verdict:</strong>
    <p style="margin:8px 0 0;">{verdict}</p>
  </div>

  <h2>Bank profiles compared</h2>
  <table class="compare-table">
    <thead>
      <tr>
        <th>Metric</th>
        <th class="bank-col num">{pa.name}<br><span style="color:var(--text3);font-weight:400;font-size:11px;">{pa.country}</span></th>
        <th class="bank-col num">{pb.name}<br><span style="color:var(--text3);font-weight:400;font-size:11px;">{pb.country}</span></th>
      </tr>
    </thead>
    <tbody>
      {cell("IRB approach", pa.irb_approach, pb.irb_approach, lower_is_better=False, fmt="{}")}
      {cell("Cost-to-income", pa.cost_to_income, pb.cost_to_income, lower_is_better=True, fmt="{:.1%}")}
      {cell("Effective tax rate", pa.effective_tax_rate, pb.effective_tax_rate, lower_is_better=True, fmt="{:.1%}")}
      {cell("Avg corporate PD", pa.corporate_avg_pd, pb.corporate_avg_pd, lower_is_better=True, fmt="{:.2%}")}
      {cell("Avg LGD unsecured", pa.avg_lgd_unsecured, pb.avg_lgd_unsecured, lower_is_better=True, fmt="{:.1%}")}
      {cell("Avg LGD secured", pa.avg_lgd_secured, pb.avg_lgd_secured, lower_is_better=True, fmt="{:.1%}")}
      {cell("Funding spread (bp)", pa.funding_spread_bp*10000, pb.funding_spread_bp*10000, lower_is_better=True, fmt="{:.0f}bp")}
      {cell("Corporate EAD", pa.corporate_ead_bn, pb.corporate_ead_bn, lower_is_better=False, fmt="EUR {:.0f}bn")}
    </tbody>
  </table>

  <h2>Sample RAROC: BBB+ EUR 25M 5Y term loan</h2>
  <p>Both banks priced on the exact same deal &mdash; 150bp spread, 20bp commitment fee, 60-month maturity.
  Higher RAROC means the bank earns more from this deal. Lower min-spread means the borrower gets a better rate.</p>
  <table class="compare-table">
    <thead>
      <tr><th>Component</th>
      <th class="bank-col num">{pa.name}</th>
      <th class="bank-col num">{pb.name}</th></tr>
    </thead>
    <tbody>
      {cell("Annual revenue", ma["revenue"], mb["revenue"], lower_is_better=False, fmt="EUR {:,.0f}")}
      {cell("Operating cost", ma["cost"], mb["cost"], lower_is_better=True, fmt="EUR {:,.0f}")}
      {cell("Expected loss", ma["expected_loss"], mb["expected_loss"], lower_is_better=True, fmt="EUR {:,.0f}")}
      {cell("Capital required (FPE)", ma["fpe"], mb["fpe"], lower_is_better=True, fmt="EUR {:,.0f}")}
      {cell("RAROC (after tax)", ma["raroc"], mb["raroc"], lower_is_better=False, fmt="{:.2%}")}
      {cell("Min spread for 12% RAROC", ma["min_spread_bp"], mb["min_spread_bp"], lower_is_better=True, fmt="{:.0f}bp")}
    </tbody>
  </table>

  <div class="callout">
    <strong>This is just one sample deal.</strong>
    <p style="margin:8px 0 12px;">Your actual portfolio has different ratings, sizes, maturities, and collateral.
    The cheapest bank for one deal isn't always cheapest for another. Upload your real facilities and OpenRAROC
    will run the same calculation on each, against {pa.name}, {pb.name}, and 57 other banks.</p>
    <a href="/app" class="btn btn-primary">Compare your portfolio</a>
  </div>

  <h2>Read more</h2>
  <div class="peer-list">
    <span class="peer-tag"><a href="/banks/{slug_for_key(key_a)}">{pa.name} full profile</a></span>
    <span class="peer-tag"><a href="/banks/{slug_for_key(key_b)}">{pb.name} full profile</a></span>
    <span class="peer-tag"><a href="/banks">All banks</a></span>
    <span class="peer-tag"><a href="/methodology">RAROC methodology</a></span>
  </div>
</div>
{footer_html()}
</body>
</html>"""
