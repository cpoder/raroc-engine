"""Programmatic SEO pages for individual banks.

Generates one indexable page per bank with real Pillar 3 data, a sample
RAROC calculation, and peer ranking. Designed to capture long-tail search
queries like "BNP Paribas RAROC" or "HSBC cost of capital" for which
no good interactive resource currently exists.
"""

from dataclasses import asdict
from typing import Dict, List, Tuple, Optional
from functools import lru_cache

from .banks import BANK_PROFILES, BankProfile
from .config import EngineConfig
from .calculator import RAROCCalculator
from .repository import Repository
from .models import RAROCInput


# ── Sample deal used for the demonstrative RAROC calculation ─────────
# A representative mid-sized European corporate facility.
SAMPLE_DEAL = dict(
    product_type="mlt_credit",
    operation="Sample BBB+ Term Loan",
    bank="",
    average_drawn=25_000_000,
    average_volume=30_000_000,
    initial_maturity=60,
    residual_maturity=60,
    spread=0.0150,            # 150bp
    commitment_fee=0.0020,    # 20bp
    flat_fee=0,
    participation_fee=0,
    upfront_fee=0,
    user_cost=None,
    rating="BBB+",
    confirmed=True,
    global_grr=0,
    collateral_stress_value=0,
)


def slug_for_key(key: str) -> str:
    return key.replace("_", "-")


def key_for_slug(slug: str) -> Optional[str]:
    candidate = slug.replace("-", "_")
    return candidate if candidate in BANK_PROFILES else None


def country_slug(country: str) -> str:
    return country.lower().replace(" ", "-")


def _calc_for_bank(profile: BankProfile) -> dict:
    """Run the sample RAROC calculation using this bank's parameters."""
    repo = Repository()
    cfg = EngineConfig(
        regime="basel3",
        bank_tax_rate=profile.effective_tax_rate,
        funding_cost_bp=profile.funding_spread_bp,
    )
    calc = RAROCCalculator(repo, cfg)
    inp = RAROCInput(**SAMPLE_DEAL)
    out = calc.calculate(inp)
    solve = calc.solve_spread(RAROCInput(**SAMPLE_DEAL), target_raroc=cfg.target_raroc)
    return {
        "raroc": out.raroc,
        "revenue": out.revenue,
        "cost": out.cost,
        "expected_loss": out.average_loss,
        "fpe": out.fpe,
        "exposure": out.exposure,
        "min_spread_bp": solve["solved_spread_bp"],
    }


@lru_cache(maxsize=1)
def _ranked_banks() -> List[Tuple[str, BankProfile, dict]]:
    """Return all banks ranked by sample RAROC, descending. Cached."""
    rows = []
    for key, profile in BANK_PROFILES.items():
        try:
            metrics = _calc_for_bank(profile)
            rows.append((key, profile, metrics))
        except Exception:
            continue
    rows.sort(key=lambda r: -r[2]["raroc"])
    return rows


def all_bank_slugs() -> List[str]:
    return [slug_for_key(k) for k in BANK_PROFILES.keys()]


# ── Page rendering ───────────────────────────────────────────────────

_PAGE_CSS = """
:root { --bg:#0f172a; --surface:#1e293b; --surface2:#334155; --border:#475569;
        --text:#f1f5f9; --text2:#cbd5e1; --text3:#94a3b8;
        --accent:#3b82f6; --accent2:#2563eb; --green:#22c55e; --red:#ef4444; }
* { margin:0; padding:0; box-sizing:border-box; }
body { background:var(--bg); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; line-height:1.6; }
a { color:var(--accent); text-decoration:none; }
a:hover { text-decoration:underline; }
nav { max-width:1100px; margin:0 auto; padding:20px 24px; display:flex; align-items:center; justify-content:space-between; }
nav .logo { font-size:20px; font-weight:700; color:var(--text); }
nav .logo span { color:var(--accent); }
nav .links { display:flex; gap:24px; align-items:center; font-size:14px; }
nav .links a { color:var(--text3); }
nav .links a:hover { color:var(--text); text-decoration:none; }
.btn { display:inline-block; padding:10px 22px; border-radius:8px; font-weight:600; font-size:14px; border:none; cursor:pointer; }
.btn-primary { background:var(--accent); color:#fff; }
.btn-outline { border:1px solid var(--border); color:var(--text); background:transparent; }
.container { max-width:980px; margin:0 auto; padding:24px; }
.crumbs { font-size:13px; color:var(--text3); margin-bottom:18px; }
.crumbs a { color:var(--text3); }
h1 { font-size:36px; font-weight:800; line-height:1.2; margin-bottom:8px; letter-spacing:-0.01em; }
.subtitle { font-size:18px; color:var(--text2); margin-bottom:28px; }
.country-tag { display:inline-block; background:var(--surface); border:1px solid var(--border); color:var(--text2); padding:3px 12px; border-radius:12px; font-size:12px; margin-left:8px; vertical-align:middle; }
h2 { font-size:22px; font-weight:700; margin:36px 0 14px; color:#fff; }
h2:first-of-type { margin-top:24px; }
p { color:var(--text2); margin-bottom:14px; }
.stat-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-bottom:8px; }
@media (max-width:720px) { .stat-grid { grid-template-columns:repeat(2,1fr); } }
.stat-card { background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:16px; }
.stat-label { font-size:11px; text-transform:uppercase; letter-spacing:0.5px; color:var(--text3); margin-bottom:6px; }
.stat-value { font-size:22px; font-weight:700; color:#fff; }
.stat-sub { font-size:11px; color:var(--text3); margin-top:4px; }
table { width:100%; border-collapse:collapse; background:var(--surface); border:1px solid var(--border); border-radius:12px; overflow:hidden; margin:12px 0; font-size:13px; }
th { text-align:left; padding:10px 14px; background:rgba(59,130,246,0.08); color:var(--accent); font-weight:600; font-size:11px; text-transform:uppercase; letter-spacing:0.4px; }
td { padding:10px 14px; border-top:1px solid var(--border); color:var(--text2); }
td.num { text-align:right; font-variant-numeric:tabular-nums; }
tr.highlight td { background:rgba(34,197,94,0.08); color:var(--text); font-weight:600; }
.callout { background:var(--surface); border-left:3px solid var(--accent); border-radius:8px; padding:18px 20px; margin:20px 0; }
.callout strong { color:#fff; }
.cta { background:linear-gradient(135deg,#1e293b,#0f172a); border:1px solid var(--border); border-radius:14px; padding:32px; text-align:center; margin:40px 0; }
.cta h3 { font-size:22px; margin-bottom:8px; color:#fff; }
.cta p { color:var(--text2); margin-bottom:20px; }
.peer-list { display:flex; flex-wrap:wrap; gap:8px; margin-top:12px; }
.peer-tag { background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:6px 12px; font-size:13px; }
.peer-tag a { color:var(--text2); }
.source { font-size:12px; color:var(--text3); padding:14px 16px; background:var(--surface); border-radius:10px; border:1px solid var(--border); }
.source a { color:var(--accent); }
footer { border-top:1px solid var(--border); padding:32px 24px; text-align:center; color:var(--text3); font-size:13px; max-width:1100px; margin:60px auto 0; }
footer .links { display:flex; gap:24px; justify-content:center; margin-bottom:12px; }
footer .links a { color:var(--text3); }
"""


def _nav_html() -> str:
    return """
<nav>
  <div class="logo"><a href="/" style="color:inherit;text-decoration:none;"><span>Open</span>RAROC</a></div>
  <div class="links">
    <a href="/banks">All banks</a>
    <a href="/methodology">Methodology</a>
    <a href="/app" class="btn btn-primary" style="padding:8px 18px;">Open the calculator</a>
  </div>
</nav>
"""


def _footer_html() -> str:
    return """
<footer>
  <div class="links">
    <a href="/">Home</a>
    <a href="/banks">All banks</a>
    <a href="/methodology">Methodology</a>
    <a href="/app">Calculator</a>
    <a href="https://github.com/cpoder/raroc-engine">GitHub</a>
  </div>
  <div>OpenRAROC &mdash; Bank data from public Pillar 3 CR6 regulatory filings</div>
</footer>
"""


def _format_bn(eur_billion: float) -> str:
    if eur_billion >= 1000:
        return f"EUR {eur_billion/1000:.1f}tn"
    return f"EUR {eur_billion:.0f}bn"


def _bank_jsonld(profile: BankProfile, slug: str, raroc: float) -> str:
    import json
    data = {
        "@context": "https://schema.org",
        "@type": "FinancialProduct",
        "name": f"{profile.name} corporate credit pricing profile",
        "provider": {
            "@type": "BankOrCreditUnion",
            "name": profile.name,
            "areaServed": profile.country,
        },
        "url": f"https://openraroc.com/banks/{slug}",
        "description": (
            f"{profile.name} corporate credit RAROC profile from Pillar 3 disclosures. "
            f"Cost-to-income {profile.cost_to_income:.1%}, effective tax rate {profile.effective_tax_rate:.1%}, "
            f"average corporate PD {profile.corporate_avg_pd:.2%}, average LGD unsecured {profile.avg_lgd_unsecured:.1%}."
        ),
    }
    return f'<script type="application/ld+json">{json.dumps(data)}</script>'


def render_bank_page(key: str) -> Optional[str]:
    profile = BANK_PROFILES.get(key)
    if not profile:
        return None

    slug = slug_for_key(key)
    metrics = _calc_for_bank(profile)
    ranked = _ranked_banks()
    rank_idx = next((i for i, (k, _, _) in enumerate(ranked) if k == key), 0)
    total = len(ranked)
    rank_position = rank_idx + 1
    raroc_pct = metrics["raroc"] * 100

    # Top 5 + this bank's neighbours
    show_indices = set([0, 1, 2, 3, 4, rank_idx])
    if rank_idx > 0:
        show_indices.add(rank_idx - 1)
    if rank_idx < total - 1:
        show_indices.add(rank_idx + 1)
    show_indices = sorted(show_indices)

    rows_html = []
    for i in show_indices:
        k, p, m = ranked[i]
        cls = ' class="highlight"' if k == key else ""
        link = f'<a href="/banks/{slug_for_key(k)}">{p.name}</a>' if k != key else f"<strong>{p.name}</strong>"
        rows_html.append(
            f'<tr{cls}><td class="num">{i+1}</td><td>{link}</td><td>{p.country}</td>'
            f'<td class="num">{m["raroc"]*100:.2f}%</td><td class="num">{m["min_spread_bp"]:.0f}bp</td></tr>'
        )
    if rank_idx > 6 and (rank_idx - 1) not in show_indices:
        rows_html.insert(5, '<tr><td colspan="5" style="text-align:center;color:var(--text3);font-style:italic;">…</td></tr>')

    # Same-country peer links
    same_country = [
        (k, p) for k, p, _ in ranked
        if p.country == profile.country and k != key
    ][:8]
    peer_links_html = ""
    if same_country:
        peer_links_html = (
            '<div class="peer-list">'
            + "".join(f'<span class="peer-tag"><a href="/banks/{slug_for_key(k)}">{p.name}</a></span>' for k, p in same_country)
            + "</div>"
        )

    # SEO meta
    title = f"{profile.name} RAROC & Credit Pricing Profile | Pillar 3 Data | OpenRAROC"
    description = (
        f"{profile.name} ({profile.country}) corporate credit pricing analysis from Pillar 3 disclosures. "
        f"Cost-to-income {profile.cost_to_income:.1%}, average PD {profile.corporate_avg_pd:.2%}, "
        f"sample RAROC {raroc_pct:.1f}% on a BBB+ EUR 25M term loan. Free interactive comparison tool."
    )
    canonical = f"https://openraroc.com/banks/{slug}"

    jsonld = _bank_jsonld(profile, slug, metrics["raroc"])

    intro_para = (
        f'{profile.name} is a {profile.country}-based bank with approximately '
        f'{_format_bn(profile.corporate_ead_bn)} of corporate credit exposure (EAD) under the '
        f'<strong>{profile.irb_approach}</strong> approach to credit risk capital. The numbers below come '
        f'directly from {profile.name}\'s most recent <a href="/methodology">Pillar 3 CR6 regulatory filings</a> '
        f'and are used to model how this bank prices corporate credit facilities.'
    )

    explainer = (
        f'On a representative <strong>BBB+ rated, 5-year term loan of EUR 25M</strong> at 150bp spread with a 20bp commitment fee, '
        f'<strong>{profile.name}</strong> would generate an estimated RAROC of <strong>{raroc_pct:.2f}%</strong> '
        f'against a typical 12% bank hurdle rate. To hit that hurdle on this exact deal, the bank would need '
        f'a minimum spread of <strong>{metrics["min_spread_bp"]:.0f}bp</strong>. '
    )
    if metrics["raroc"] >= 0.12:
        explainer += "This deal is comfortably above the bank's target return."
    elif metrics["raroc"] >= 0.08:
        explainer += "This deal is below target — the bank would likely push for higher pricing or additional ancillary business."
    else:
        explainer += "This deal is significantly below target — the bank would either reprice it or decline."

    rank_text = (
        f"Out of {total} banks in the OpenRAROC dataset, {profile.name} ranks "
        f"<strong>#{rank_position}</strong> by RAROC on this sample deal."
    )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<meta name="description" content="{description}">
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="article">
<meta property="og:url" content="{canonical}">
<meta property="og:title" content="{profile.name} - RAROC Profile & Credit Pricing">
<meta property="og:description" content="{description}">
<meta property="og:site_name" content="OpenRAROC">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="{profile.name} - RAROC Profile">
<meta name="twitter:description" content="{description}">
{jsonld}
<style>{_PAGE_CSS}</style>
</head>
<body>
{_nav_html()}
<div class="container">
  <div class="crumbs"><a href="/">Home</a> / <a href="/banks">Banks</a> / {profile.name}</div>

  <h1>{profile.name} <span class="country-tag">{profile.country}</span></h1>
  <p class="subtitle">RAROC profile and corporate credit pricing model derived from Pillar 3 disclosures.</p>

  <div class="stat-grid">
    <div class="stat-card">
      <div class="stat-label">Cost-to-income</div>
      <div class="stat-value">{profile.cost_to_income*100:.1f}%</div>
      <div class="stat-sub">Operating efficiency</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Effective tax rate</div>
      <div class="stat-value">{profile.effective_tax_rate*100:.1f}%</div>
      <div class="stat-sub">Applied to RAROC numerator</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Avg corporate PD</div>
      <div class="stat-value">{profile.corporate_avg_pd*100:.2f}%</div>
      <div class="stat-sub">Probability of default</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Avg LGD unsecured</div>
      <div class="stat-value">{profile.avg_lgd_unsecured*100:.1f}%</div>
      <div class="stat-sub">Loss given default</div>
    </div>
  </div>

  <h2>How {profile.name} prices corporate credit</h2>
  <p>{intro_para}</p>

  <table>
    <thead><tr><th>Parameter</th><th>Value</th><th>What it means</th></tr></thead>
    <tbody>
      <tr><td>IRB approach</td><td><strong>{profile.irb_approach}</strong></td><td>How the bank computes risk-weighted assets</td></tr>
      <tr><td>Cost-to-income ratio</td><td>{profile.cost_to_income*100:.1f}%</td><td>Operating cost share of net revenue</td></tr>
      <tr><td>Effective tax rate</td><td>{profile.effective_tax_rate*100:.1f}%</td><td>Applied to RAROC numerator after EL and funding</td></tr>
      <tr><td>Average corporate PD</td><td>{profile.corporate_avg_pd*100:.2f}%</td><td>EAD-weighted probability of default</td></tr>
      <tr><td>Avg LGD (unsecured)</td><td>{profile.avg_lgd_unsecured*100:.1f}%</td><td>Loss share if borrower defaults, no collateral</td></tr>
      <tr><td>Avg LGD (secured)</td><td>{profile.avg_lgd_secured*100:.1f}%</td><td>Loss share with eligible collateral</td></tr>
      <tr><td>Funding spread</td><td>{profile.funding_spread_bp*10000:.0f}bp</td><td>Bank's wholesale funding cost above risk-free</td></tr>
      <tr><td>Corporate EAD</td><td>{_format_bn(profile.corporate_ead_bn)}</td><td>Total exposure at default to corporates</td></tr>
    </tbody>
  </table>

  <h2>Sample RAROC calculation</h2>
  <p>{explainer}</p>

  <table>
    <thead><tr><th>Component</th><th class="num">Value</th></tr></thead>
    <tbody>
      <tr><td>Annual revenue (spread + fees)</td><td class="num">EUR {metrics["revenue"]:,.0f}</td></tr>
      <tr><td>Operating cost</td><td class="num">EUR {metrics["cost"]:,.0f}</td></tr>
      <tr><td>Expected loss (PD × LGD × EAD)</td><td class="num">EUR {metrics["expected_loss"]:,.0f}</td></tr>
      <tr><td>Capital required (FPE)</td><td class="num">EUR {metrics["fpe"]:,.0f}</td></tr>
      <tr><td><strong>RAROC (after tax)</strong></td><td class="num"><strong>{raroc_pct:.2f}%</strong></td></tr>
      <tr><td>Min spread to hit 12% RAROC</td><td class="num">{metrics["min_spread_bp"]:.0f}bp</td></tr>
    </tbody>
  </table>

  <h2>How {profile.name} compares to peers</h2>
  <p>{rank_text}</p>

  <table>
    <thead><tr><th>Rank</th><th>Bank</th><th>Country</th><th class="num">RAROC</th><th class="num">Min spread</th></tr></thead>
    <tbody>
      {''.join(rows_html)}
    </tbody>
  </table>

  <div class="callout">
    <strong>Want to see how {profile.name} prices YOUR portfolio?</strong>
    <p style="margin:8px 0 12px;">Upload a CSV of your existing facilities and OpenRAROC will run the same calculation
    against {profile.name} (and 58 other banks) to show you who's overcharging you and which bank should price your next deal.</p>
    <a href="/app" class="btn btn-primary">Open the calculator</a>
  </div>

  {f'<h2>Other {profile.country} banks</h2>{peer_links_html}' if peer_links_html else ''}

  <h2>Data source</h2>
  <div class="source">
    {profile.source}
    {('<br><br>' + profile.notes) if profile.notes else ''}
    <br><br>
    <em>Confidence: {profile.confidence}</em> &middot;
    <a href="/methodology">Read the full RAROC methodology</a>
  </div>

  <div class="cta">
    <h3>Compare 59 banks side-by-side</h3>
    <p>Free RAROC calculator. Upload your portfolio. See who prices your facilities best.</p>
    <a href="/app" class="btn btn-primary">Open OpenRAROC</a>
  </div>
</div>
{_footer_html()}
</body>
</html>"""
    return page


def render_banks_index() -> str:
    ranked = _ranked_banks()
    total = len(ranked)

    # Group by country
    by_country: Dict[str, List[Tuple[str, BankProfile, dict]]] = {}
    for k, p, m in ranked:
        by_country.setdefault(p.country, []).append((k, p, m))

    # Country counts in alphabetical order
    countries = sorted(by_country.keys())

    sections = []
    for country in countries:
        banks = by_country[country]
        cards = "".join(
            f'<a href="/banks/{slug_for_key(k)}" class="bank-card">'
            f'<div class="bank-name">{p.name}</div>'
            f'<div class="bank-stats">RAROC {m["raroc"]*100:.1f}% &middot; min spread {m["min_spread_bp"]:.0f}bp</div>'
            f'<div class="bank-meta">C/I {p.cost_to_income*100:.0f}% &middot; PD {p.corporate_avg_pd*100:.2f}%</div>'
            f'</a>'
            for k, p, m in banks
        )
        sections.append(f'<h2 id="{country_slug(country)}">{country} <span class="count">({len(banks)})</span></h2><div class="bank-grid">{cards}</div>')

    countries_nav = " &middot; ".join(
        f'<a href="#{country_slug(c)}">{c}</a>' for c in countries
    )

    title = f"All {total} Banks - RAROC Profiles & Pillar 3 Data | OpenRAROC"
    description = (
        f"Browse RAROC profiles for {total} global banks across {len(countries)} countries. "
        "Cost-to-income, PD, LGD, EAD and credit pricing for every bank — all sourced from Pillar 3 regulatory filings."
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<meta name="description" content="{description}">
<link rel="canonical" href="https://openraroc.com/banks">
<meta property="og:type" content="website">
<meta property="og:url" content="https://openraroc.com/banks">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<style>
{_PAGE_CSS}
.bank-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:14px; margin-bottom:24px; }}
@media (max-width:820px) {{ .bank-grid {{ grid-template-columns:repeat(2,1fr); }} }}
@media (max-width:520px) {{ .bank-grid {{ grid-template-columns:1fr; }} }}
.bank-card {{ background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:16px; transition:border-color 0.15s; display:block; color:var(--text); }}
.bank-card:hover {{ border-color:var(--accent); text-decoration:none; }}
.bank-name {{ font-weight:700; font-size:15px; margin-bottom:6px; color:#fff; }}
.bank-stats {{ font-size:12px; color:var(--accent); margin-bottom:3px; }}
.bank-meta {{ font-size:11px; color:var(--text3); }}
.count {{ color:var(--text3); font-weight:400; font-size:16px; }}
.country-nav {{ background:var(--surface); border:1px solid var(--border); border-radius:10px; padding:14px 18px; font-size:13px; margin-bottom:24px; line-height:1.9; }}
.country-nav a {{ color:var(--text2); }}
</style>
</head>
<body>
{_nav_html()}
<div class="container">
  <div class="crumbs"><a href="/">Home</a> / Banks</div>
  <h1>All {total} Banks</h1>
  <p class="subtitle">RAROC profiles and corporate credit pricing data for every bank in the OpenRAROC dataset, sourced from public Pillar 3 disclosures. Click any bank to see its full profile, sample RAROC calculation, and peer ranking.</p>

  <div class="country-nav"><strong style="color:var(--text);">Jump to country:</strong><br>{countries_nav}</div>

  {''.join(sections)}

  <div class="cta">
    <h3>Compare your portfolio across all {total} banks</h3>
    <p>Upload your facilities and OpenRAROC will rank every bank by how well they price your deals.</p>
    <a href="/app" class="btn btn-primary">Open the calculator</a>
  </div>
</div>
{_footer_html()}
</body>
</html>"""
