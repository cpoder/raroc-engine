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
from .bank_commentary import generate_commentary
from .seo_helpers import (
    article_jsonld,
    breadcrumb_jsonld,
    credenda_cta_url,
    credenda_ref,
    faq_jsonld,
    faq_html,
    howto_jsonld,
    FAQ_CSS,
    last_updated_html,
    data_last_updated,
    data_last_updated_iso,
)


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

PAGE_CSS = """
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


def nav_html() -> str:
    return """
<nav>
  <div class="logo"><a href="/" style="color:inherit;text-decoration:none;"><span>Open</span>RAROC</a></div>
  <div class="links">
    <a href="/banks">Banks</a>
    <a href="/insights">Insights</a>
    <a href="/methodology">Methodology</a>
    <a href="/app" class="btn btn-primary" style="padding:8px 18px;">Open the calculator</a>
  </div>
</nav>
"""


def footer_html() -> str:
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


def format_bn(eur_billion: float) -> str:
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
        "dateModified": data_last_updated_iso(),
    }
    return f'<script type="application/ld+json">{json.dumps(data)}</script>'


def _build_bank_faqs(profile: BankProfile, metrics: dict, rank: int, total: int, country_rank, n_country: int):
    """Return list of (question, answer_text) tuples for this bank."""
    faqs = [
        (
            f"What is {profile.name}'s average corporate PD?",
            (
                f"{profile.name} discloses an EAD-weighted average corporate probability of default "
                f"of {profile.corporate_avg_pd*100:.2f}% in its most recent Pillar 3 CR6 table, "
                f"covering roughly EUR {profile.corporate_ead_bn:.0f}bn of corporate credit exposure."
            ),
        ),
        (
            f"How much spread does {profile.name} need on a BBB+ EUR 25M 5-year term loan?",
            (
                f"On that standardised facility, {profile.name} requires a minimum spread of "
                f"approximately {metrics['min_spread_bp']:.0f}bp to reach a 12% RAROC hurdle, "
                f"given its disclosed cost-to-income of {profile.cost_to_income*100:.1f}%, "
                f"effective tax rate of {profile.effective_tax_rate*100:.1f}%, and "
                f"{profile.irb_approach} IRB designation."
            ),
        ),
        (
            f"Which IRB approach does {profile.name} use for corporate credit?",
            (
                f"{profile.name} reports corporate credit RWA under the {profile.irb_approach} "
                f"approach. This determines whether internal LGD models or supervisory LGDs apply, "
                f"and directly affects the capital required on each facility."
            ),
        ),
        (
            f"How does {profile.name} rank versus peers on RAROC?",
            (
                f"Out of {total} banks tracked by OpenRAROC, {profile.name} ranks #{rank} on the "
                f"standardised BBB+ term-loan calculation used across every bank profile."
                + (
                    f" Within {profile.country} specifically, it ranks #{country_rank} of {n_country}."
                    if country_rank and n_country > 1
                    else ""
                )
            ),
        ),
        (
            f"Where does OpenRAROC get {profile.name}'s data?",
            (
                f"Every number on this page is extracted from {profile.name}'s own public filings: "
                f"{profile.source}. No estimates, no proxies. Source confidence: {profile.confidence}."
            ),
        ),
    ]
    return faqs


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
    same_country_full = [
        (k, p, m) for k, p, m in ranked
        if p.country == profile.country and k != key
    ]
    same_country = same_country_full[:8]
    peer_links_html = ""
    if same_country:
        peer_links_html = (
            '<div class="peer-list">'
            + "".join(f'<span class="peer-tag"><a href="/banks/{slug_for_key(k)}">{p.name}</a></span>' for k, p, _ in same_country)
            + "</div>"
        )

    # Compare-page links (2–3 most relevant pairs: same-country top-EAD peers)
    compare_candidates = sorted(same_country_full, key=lambda r: -r[1].corporate_ead_bn)[:3]
    compare_links_html = ""
    if compare_candidates:
        compare_links_html = (
            '<div class="peer-list">'
            + "".join(
                f'<span class="peer-tag"><a href="/compare/{slug}-vs-{slug_for_key(k)}">'
                f'{profile.name} vs {p.name}</a></span>'
                for k, p, _ in compare_candidates
            )
            + "</div>"
        )

    # Commentary + FAQ
    country_peers_all = [(k, p, m) for k, p, m in ranked if p.country == profile.country]
    commentary_html = generate_commentary(key, profile, metrics, ranked, country_peers_all)
    country_rank = None
    n_country = len(country_peers_all)
    if n_country > 1:
        sorted_country = sorted(country_peers_all, key=lambda r: -r[2]["raroc"])
        country_rank = next((i for i, (k, _, _) in enumerate(sorted_country) if k == key), 0) + 1
    faqs = _build_bank_faqs(profile, metrics, rank_position, total, country_rank, n_country)
    faq_block = faq_html(faqs, heading=f"Frequently asked questions about {profile.name}")
    faq_ld = faq_jsonld(faqs)
    breadcrumb_ld = breadcrumb_jsonld([
        ("Home", "https://openraroc.com/"),
        ("Banks", "https://openraroc.com/banks"),
        (profile.name, f"https://openraroc.com/banks/{slug}"),
    ])

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
        f'{format_bn(profile.corporate_ead_bn)} of corporate credit exposure (EAD) under the '
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
{faq_ld}
{breadcrumb_ld}
<meta property="article:modified_time" content="{data_last_updated_iso()}">
<style>{PAGE_CSS}{FAQ_CSS}</style>
</head>
<body>
{nav_html()}
<div class="container">
  <div class="crumbs"><a href="/">Home</a> / <a href="/banks">Banks</a> / {profile.name}</div>

  <h1>{profile.name} <span class="country-tag">{profile.country}</span></h1>
  <p class="subtitle">RAROC profile and corporate credit pricing model derived from Pillar 3 disclosures.</p>
  {last_updated_html()}

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

  <h2>What makes {profile.name}'s book distinctive</h2>
  {commentary_html}

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
      <tr><td>Corporate EAD</td><td>{format_bn(profile.corporate_ead_bn)}</td><td>Total exposure at default to corporates</td></tr>
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

  {f'<h2>Compare {profile.name} to peers</h2>{compare_links_html}' if compare_links_html else ''}

  {faq_block}

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
{footer_html()}
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
{PAGE_CSS}
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
{nav_html()}
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
{footer_html()}
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════════
# Transactional pages (Task 3.9)
# ═══════════════════════════════════════════════════════════════════
#
# These pages sit one level below /banks/{slug} and answer a specific
# buyer-intent question for a single bank:
#
#   /banks/{slug}/renegotiate-rcf       — "Renegotiate your {bank} RCF"
#   /banks/{slug}/term-loan-fair-price  — "Is your {bank} term loan fairly priced?"
#
# Each page reuses the bank's Pillar 3 numbers and runs a fresh sample
# RAROC deal that matches the intent (revolver versus amortising term
# loan), so the answer is data-grounded rather than copy-spun. The
# conversion is always Credenda (the App), reached through a ref-tagged
# CTA so the funnel can be measured (D-0032).


# ── Cross-bank cohort benchmark for one sample deal ──────────────────

@lru_cache(maxsize=8)
def _cohort_for_deal(sample_deal_key: str) -> Tuple[float, float, float, int]:
    """Compute P25/P50/P75/N min-spread across all banks for a sample deal.

    ``sample_deal_key`` is one of the registry keys in ``_SAMPLE_DEALS``
    so the result is cacheable and the function can be called per
    bank-page render without re-running 59 calculators every time.
    """
    deal = _SAMPLE_DEALS[sample_deal_key]
    spreads_bp: List[float] = []
    for key, profile in BANK_PROFILES.items():
        try:
            repo = Repository()
            cfg = EngineConfig(
                regime="basel3",
                bank_tax_rate=profile.effective_tax_rate,
                funding_cost_bp=profile.funding_spread_bp,
            )
            calc = RAROCCalculator(repo, cfg)
            solve = calc.solve_spread(RAROCInput(**deal), target_raroc=cfg.target_raroc)
            spreads_bp.append(float(solve["solved_spread_bp"]))
        except Exception:
            continue
    n = len(spreads_bp)
    if n == 0:
        return (0.0, 0.0, 0.0, 0)
    spreads_bp.sort()

    def _pct(p: float) -> float:
        # linear-interpolation quantile, no numpy dependency in callers
        if n == 1:
            return spreads_bp[0]
        k = (n - 1) * p
        lo = int(k)
        hi = min(lo + 1, n - 1)
        frac = k - lo
        return spreads_bp[lo] + (spreads_bp[hi] - spreads_bp[lo]) * frac

    return (_pct(0.25), _pct(0.50), _pct(0.75), n)


def _calc_for_sample(profile: BankProfile, sample_deal_key: str) -> dict:
    """Run a named sample deal against one bank's parameters."""
    deal = _SAMPLE_DEALS[sample_deal_key]
    repo = Repository()
    cfg = EngineConfig(
        regime="basel3",
        bank_tax_rate=profile.effective_tax_rate,
        funding_cost_bp=profile.funding_spread_bp,
    )
    calc = RAROCCalculator(repo, cfg)
    inp = RAROCInput(**deal)
    out = calc.calculate(inp)
    solve = calc.solve_spread(RAROCInput(**deal), target_raroc=cfg.target_raroc)
    return {
        "raroc": out.raroc,
        "revenue": out.revenue,
        "cost": out.cost,
        "expected_loss": out.average_loss,
        "fpe": out.fpe,
        "exposure": out.exposure,
        "min_spread_bp": float(solve["solved_spread_bp"]),
    }


# ── Sample deals (one per intent) ───────────────────────────────────
#
# Both shapes are "representative mid-corp" so that a CFO clicking
# through can recognise their own term sheet without us pretending to
# price it. The numbers are stylised but conservative.

_SAMPLE_DEALS: Dict[str, dict] = {
    "rcf_bbb_50m_5y": dict(
        product_type="mlt_credit",
        operation="Sample BBB+ Revolver",
        bank="",
        average_drawn=25_000_000,        # 50% drawn on a 50M RCF
        average_volume=50_000_000,
        initial_maturity=60,
        residual_maturity=60,
        spread=0.0175,                   # 175bp drawn margin
        commitment_fee=0.0030,           # 30bp commitment
        flat_fee=0,
        participation_fee=0,
        upfront_fee=0,
        user_cost=None,
        rating="BBB+",
        confirmed=True,
        global_grr=0,
        collateral_stress_value=0,
    ),
    "term_loan_bbb_25m_5y": dict(
        product_type="mlt_credit",
        operation="Sample BBB+ Term Loan",
        bank="",
        average_drawn=25_000_000,
        average_volume=25_000_000,
        initial_maturity=60,
        residual_maturity=60,
        spread=0.0150,                   # 150bp
        commitment_fee=0,                # term loans don't carry a commitment fee
        flat_fee=0,
        participation_fee=0,
        upfront_fee=0,
        user_cost=None,
        rating="BBB+",
        confirmed=True,
        global_grr=0,
        collateral_stress_value=0,
    ),
}


# ── Intent registry ─────────────────────────────────────────────────

TRANSACTIONAL_INTENTS: Dict[str, dict] = {
    "renegotiate-rcf": {
        "slug": "renegotiate-rcf",
        "sample_deal_key": "rcf_bbb_50m_5y",
        "product_label": "revolving credit facility (RCF)",
        "product_short": "RCF",
        "deal_caption": (
            "EUR 50M BBB+ revolving credit facility, 5-year tenor, "
            "50% average utilisation (EUR 25M drawn), 175bp drawn margin, 30bp commitment fee."
        ),
        "title": "Renegotiate your {bank} RCF: spread benchmark from Pillar 3 data | OpenRAROC",
        "h1": "Renegotiate your {bank} RCF",
        "subtitle": (
            "Where the bank's fair-price floor actually sits — and how much room "
            "you have to push on spread and commitment fee."
        ),
        "intent_kicker": "Renegotiation",
        "meta_description": (
            "Renegotiating a {bank} revolver? See the fair-price floor on a benchmark "
            "BBB+ RCF using {bank}'s own Pillar 3 numbers. Free engine, instant assessment."
        ),
        "intro_para": (
            "{bank} prices revolvers off a small number of public inputs — cost-to-income, "
            "effective tax rate, average corporate PD, LGD bands, and IRB approach. "
            "Plug those into the RAROC equation against a benchmark BBB+ RCF and you get the "
            "spread + commitment-fee combination the bank actually needs to clear its hurdle. "
            "If your facility is meaningfully above that floor, you have room to renegotiate."
        ),
        "mechanic_para": (
            "RCF pricing has two moving parts: the drawn margin and the commitment fee on the "
            "undrawn portion. Banks calibrate them jointly so that, at an expected utilisation, "
            "the combined revenue clears their RAROC hurdle. When utilisation falls below "
            "underwriting assumption, the commitment fee becomes the load-bearing part of the "
            "price. Renegotiation conversations almost always need to touch both — pushing only "
            "on drawn margin while the commitment fee stays high leaves money on the table."
        ),
        "cta_headline": "Get the fair-price floor on your {bank} RCF in 90 seconds",
        "cta_body": (
            "Paste your term sheet into Credenda's Term-Sheet Doctor. It re-runs the OpenRAROC "
            "engine against {bank}'s Pillar 3 numbers, scores the deal P25/P50/P75 across the "
            "peer cohort, and flags every clause that's worth pushing back on."
        ),
        "cta_button": "Open Term-Sheet Doctor",
        "howto_steps": [
            ("Read the bank's fair-price floor",
             "Use the sample RAROC calculation below — it shows the minimum spread {bank} "
             "needs on a benchmark BBB+ EUR 50M RCF to clear its 12% RAROC hurdle, given its "
             "disclosed cost-to-income and tax rate."),
            ("Compare against your existing pricing",
             "If your drawn margin + commitment fee combination is above this floor, you have "
             "room. The further above P50 you sit on the cohort comparison, the larger the "
             "realistic ask."),
            ("Run your actual term sheet through Credenda's Term-Sheet Doctor",
             "Upload or paste your facility terms. Credenda projects the deal economics from "
             "{bank}'s perspective, returns a Below / At / Above market verdict, and proposes "
             "the specific clauses to renegotiate."),
            ("Open the renegotiation conversation with public numbers",
             "Bring the OpenRAROC calculation and Credenda's verdict to your relationship "
             "banker. Both are sourced from {bank}'s own public filings, so the conversation "
             "stays on solid ground."),
        ],
    },
    "term-loan-fair-price": {
        "slug": "term-loan-fair-price",
        "sample_deal_key": "term_loan_bbb_25m_5y",
        "product_label": "term loan",
        "product_short": "term loan",
        "deal_caption": (
            "EUR 25M BBB+ amortising term loan, 5-year tenor, fully drawn, 150bp spread, "
            "no commitment fee."
        ),
        "title": "Is your {bank} term loan fairly priced? Pillar 3 benchmark | OpenRAROC",
        "h1": "Is your {bank} term loan fairly priced?",
        "subtitle": (
            "An independent spread benchmark on a BBB+ EUR 25M 5-year term loan, "
            "derived from {bank}'s own Pillar 3 disclosures."
        ),
        "intent_kicker": "Pricing check",
        "meta_description": (
            "Wondering if your {bank} term loan is at, above or below market? Use {bank}'s "
            "Pillar 3 numbers to derive the fair spread floor on a benchmark BBB+ 5-year "
            "term loan. Free OpenRAROC engine."
        ),
        "intro_para": (
            "Term-loan pricing is simpler than revolver pricing: one spread, no commitment "
            "fee, no utilisation-curve noise. That makes the fair-price question crisp. "
            "{bank} needs the deal to clear its RAROC hurdle, and the inputs that determine "
            "that — cost-to-income, effective tax rate, average corporate PD, LGD bands — "
            "are all public. The number you see below is the spread the bank actually needs."
        ),
        "mechanic_para": (
            "When the market quotes 'a 150bp deal' on a BBB+ name, that's a starting point. "
            "Whether 150bp is fair depends on the lender — a bank with higher funding cost or "
            "a heavier cost-to-income ratio needs more spread to clear the same hurdle. A "
            "fair-price benchmark anchored on {bank}'s own disclosures cuts through the "
            "noise. If your facility sits below P50 on the cohort, you're priced sharply. "
            "Above P75, the bank is over-earning on you."
        ),
        "cta_headline": "Get a fair-price verdict on your {bank} term loan in 90 seconds",
        "cta_body": (
            "Upload or paste your term-sheet into Credenda's Term-Sheet Doctor. It returns "
            "a Below / At / Above market verdict, the exact spread that would put you on "
            "the P50 line, and the specific clauses worth renegotiating before signing."
        ),
        "cta_button": "Open Term-Sheet Doctor",
        "howto_steps": [
            ("Look up the bank's fair-price floor below",
             "The sample RAROC calculation shows the minimum spread {bank} needs on a "
             "benchmark BBB+ 25M 5-year term loan to clear its 12% hurdle, using its own "
             "disclosed inputs."),
            ("Locate your facility on the cohort distribution",
             "P25 / P50 / P75 across all banks tells you where the market sits. If your "
             "spread is at the bank's floor, you're priced sharply; closer to P75 means "
             "you're paying for the bank's profitability."),
            ("Run your actual term sheet through Credenda's Term-Sheet Doctor",
             "Drop the PDF in. Credenda extracts the terms, re-runs the engine against "
             "{bank}, and returns a verdict plus a list of clauses worth pushing back on."),
            ("Use the verdict in the term-sheet conversation",
             "Whether the verdict is Above or Below market, the underlying numbers come "
             "from {bank}'s public filings. Bring them to your relationship banker as the "
             "anchor for the conversation."),
        ],
    },
}


def all_transactional_intent_slugs() -> List[str]:
    return list(TRANSACTIONAL_INTENTS.keys())


def all_transactional_pages() -> List[Tuple[str, str]]:
    """Return ``(bank_slug, intent_slug)`` for every transactional page."""
    out: List[Tuple[str, str]] = []
    for intent_slug in TRANSACTIONAL_INTENTS:
        for bank_key in BANK_PROFILES:
            out.append((slug_for_key(bank_key), intent_slug))
    return out


def parse_transactional_path(bank_slug: str, intent_slug: str) -> Optional[Tuple[str, dict]]:
    """Resolve ``(bank_slug, intent_slug)`` to ``(bank_key, intent_spec)``.

    Returns ``None`` on either unknown bank or unknown intent — both
    paths the route layer needs to map to a 404.
    """
    bank_key = key_for_slug(bank_slug)
    intent = TRANSACTIONAL_INTENTS.get(intent_slug)
    if bank_key is None or intent is None:
        return None
    return (bank_key, intent)


# ── Transactional FAQ + body ────────────────────────────────────────

def _format_money_eur(amount_eur: float) -> str:
    return f"EUR {amount_eur:,.0f}"


def _verdict_phrase(min_spread_bp: float, cohort_p25: float, cohort_p50: float, cohort_p75: float) -> str:
    """Position the bank's floor against the cohort, for body copy."""
    if min_spread_bp <= cohort_p25:
        return "sits in the bottom quartile of the cohort — {bank} is among the tightest-pricing lenders on this deal"
    if min_spread_bp <= cohort_p50:
        return "is below the median — {bank} prices tighter than half the cohort"
    if min_spread_bp <= cohort_p75:
        return "is above the median — {bank} prices wider than half the cohort, but not punitive"
    return "sits in the top quartile — {bank} needs more spread than three quarters of the cohort to clear its hurdle"


def _build_transactional_faqs(
    profile: BankProfile,
    intent: dict,
    metrics: dict,
    cohort_p25: float,
    cohort_p50: float,
    cohort_p75: float,
    cohort_n: int,
) -> List[Tuple[str, str]]:
    bank = profile.name
    is_rcf = intent["slug"] == "renegotiate-rcf"

    if is_rcf:
        return [
            (
                f"Can I actually renegotiate the spread on a {bank} RCF mid-life?",
                (
                    f"Yes. Most {bank} revolvers include a market-flex clause or an annual "
                    "repricing trigger, and even when they do not, the bank will engage if "
                    "your ancillary business has grown or your credit rating has improved. "
                    "The leverage point in the conversation is showing that the bank's own "
                    "RAROC math clears at a tighter spread + commitment fee combination."
                ),
            ),
            (
                f"How does OpenRAROC know what {bank} needs to charge?",
                (
                    f"Every input — cost-to-income {profile.cost_to_income*100:.1f}%, effective "
                    f"tax rate {profile.effective_tax_rate*100:.1f}%, average corporate PD "
                    f"{profile.corporate_avg_pd*100:.2f}%, LGD bands, IRB approach — comes "
                    f"directly from {bank}'s most recent public Pillar 3 disclosures. The "
                    "engine then runs the same math the bank's own pricing committee runs."
                ),
            ),
            (
                "What's a realistic ask: 10bp? 25bp? more?",
                (
                    f"Depends on where your facility currently sits against the P25 / P50 / "
                    f"P75 of the {cohort_n}-bank cohort on the benchmark RCF below "
                    f"(P25 ≈ {cohort_p25:.0f}bp, P50 ≈ {cohort_p50:.0f}bp, P75 ≈ "
                    f"{cohort_p75:.0f}bp). If your spread is above the P50, asking for "
                    "15-25bp typically lands; above P75, 30-50bp is in scope. Credenda's "
                    "Term-Sheet Doctor reports your exact band."
                ),
            ),
            (
                "Does the commitment fee count as 'spread'?",
                (
                    "Economically yes. At typical RCF utilisation (45-60%), the commitment "
                    "fee delivers roughly half of total revenue per euro of commitment. "
                    "Negotiating drawn margin without simultaneously negotiating the "
                    "commitment fee usually leaves the larger lever untouched."
                ),
            ),
            (
                f"Where does {bank}'s data on this page come from?",
                (
                    f"{profile.source} Source confidence: {profile.confidence}."
                ),
            ),
        ]
    return [
        (
            f"How does {bank}'s 'fair-price floor' get derived?",
            (
                f"{bank} discloses cost-to-income ({profile.cost_to_income*100:.1f}%), "
                f"effective tax rate ({profile.effective_tax_rate*100:.1f}%), corporate PD "
                f"({profile.corporate_avg_pd*100:.2f}%) and LGD bands in its Pillar 3 "
                "filings. OpenRAROC plugs those into the standard RAROC equation against "
                "a benchmark BBB+ term loan and solves for the spread that clears a 12% "
                "hurdle. That is the bank's fair-price floor on this exact deal."
            ),
        ),
        (
            "What does 'fairly priced' mean in practice?",
            (
                f"A {bank} term loan is fairly priced if its spread sits between P25 and "
                f"P50 of the cohort — competitive with the market but still profitable for "
                f"the bank. Below P25 you're getting a friend price (and probably owe the "
                f"bank elsewhere). Above P75, the bank is over-earning on this facility "
                "and there is room to push back."
            ),
        ),
        (
            f"My deal isn't BBB+ / isn't EUR 25M / isn't 5-year — does this still apply?",
            (
                f"The benchmark deal is stylised so the cohort comparison stays apples-to-"
                f"apples across {cohort_n} banks. For your actual deal — different rating, "
                "size, tenor, collateral — Credenda's Term-Sheet Doctor re-runs the same "
                f"engine against {bank} but on your real terms, and tells you exactly where "
                "you sit."
            ),
        ),
        (
            "How do I bring this up with my relationship banker?",
            (
                f"Lead with the public data: \"On {bank}'s own Pillar 3 numbers, a BBB+ EUR "
                "25M 5-year term loan clears the RAROC hurdle at "
                f"{metrics['min_spread_bp']:.0f}bp. Where does my deal land versus that?\" "
                "It's a conversation about the bank's own internal math, not about market "
                "gossip or comparable quotes."
            ),
        ),
        (
            f"Where does {bank}'s data on this page come from?",
            (
                f"{profile.source} Source confidence: {profile.confidence}."
            ),
        ),
    ]


# ── Renderer ────────────────────────────────────────────────────────

def render_transactional_page(bank_key: str, intent_slug: str) -> Optional[str]:
    profile = BANK_PROFILES.get(bank_key)
    intent = TRANSACTIONAL_INTENTS.get(intent_slug)
    if not profile or not intent:
        return None

    bank_slug = slug_for_key(bank_key)
    canonical = f"https://openraroc.com/banks/{bank_slug}/{intent_slug}"
    bank = profile.name
    sample_deal_key = intent["sample_deal_key"]
    metrics = _calc_for_sample(profile, sample_deal_key)
    p25, p50, p75, n_cohort = _cohort_for_deal(sample_deal_key)

    # Where this bank sits in the cohort
    floor_bp = metrics["min_spread_bp"]
    if p50 > 0:
        delta_vs_p50 = floor_bp - p50
    else:
        delta_vs_p50 = 0
    verdict_phrase = _verdict_phrase(floor_bp, p25, p50, p75).format(bank=bank)

    # SEO + JSON-LD blocks
    title = intent["title"].format(bank=bank)
    description = intent["meta_description"].format(bank=bank)
    intro_para = intent["intro_para"].format(bank=bank)
    mechanic_para = intent["mechanic_para"].format(bank=bank)
    cta_headline = intent["cta_headline"].format(bank=bank)
    cta_body = intent["cta_body"].format(bank=bank)
    h1 = intent["h1"].format(bank=bank)
    subtitle = intent["subtitle"].format(bank=bank)
    intent_kicker = intent["intent_kicker"]

    howto_steps = [(name, text.format(bank=bank)) for name, text in intent["howto_steps"]]

    faqs = _build_transactional_faqs(profile, intent, metrics, p25, p50, p75, n_cohort)
    faq_block = faq_html(faqs, heading=f"FAQ — {h1.lower()}")
    faq_ld = faq_jsonld(faqs)
    breadcrumb_ld = breadcrumb_jsonld([
        ("Home", "https://openraroc.com/"),
        ("Banks", "https://openraroc.com/banks"),
        (bank, f"https://openraroc.com/banks/{bank_slug}"),
        (intent_kicker, canonical),
    ])
    article_ld = article_jsonld(headline=h1, description=description, url=canonical)
    howto_ld = howto_jsonld(
        name=h1,
        description=cta_body,
        steps=howto_steps,
    )

    # Conversion CTAs to credenda.io. The first-touch attribution lands
    # on the Credenda landing page; the deep-link CTA goes to the
    # Term-Sheet Doctor directly so the visitor can convert in one click.
    credenda_landing = credenda_cta_url(bank_slug, intent_slug, path="/")
    credenda_doctor = credenda_cta_url(
        bank_slug, intent_slug, path="/modules/term-sheet-doctor"
    )

    # Sample-deal verdict explainer
    raroc_pct = metrics["raroc"] * 100
    if raroc_pct >= 12:
        verdict = "above the bank's 12% hurdle — the deal would be profitable as quoted"
    elif raroc_pct >= 8:
        verdict = "below the bank's 12% hurdle — the bank would likely push for tighter terms"
    else:
        verdict = "well below the bank's 12% hurdle — the bank would either reprice or decline this deal at the stated terms"

    # Cohort positioning line
    cohort_position = (
        f"On this benchmark deal, {bank}'s required spread of {floor_bp:.0f}bp "
        f"{verdict_phrase}."
    )

    # Cross-link strip to related pages
    other_intent_slug = next(
        (s for s in TRANSACTIONAL_INTENTS if s != intent_slug), None
    )
    other_link_html = ""
    if other_intent_slug:
        other_intent = TRANSACTIONAL_INTENTS[other_intent_slug]
        other_h1 = other_intent["h1"].format(bank=bank)
        other_link_html = (
            f'<p style="margin-top:14px;"><a href="/banks/{bank_slug}/{other_intent_slug}">'
            f'{other_h1}</a> &middot; '
            f'<a href="/banks/{bank_slug}">Full {bank} RAROC profile</a></p>'
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
<meta property="og:title" content="{h1}">
<meta property="og:description" content="{description}">
<meta property="og:site_name" content="OpenRAROC">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="{h1}">
<meta name="twitter:description" content="{description}">
{article_ld}
{howto_ld}
{faq_ld}
{breadcrumb_ld}
<meta property="article:modified_time" content="{data_last_updated_iso()}">
<style>{PAGE_CSS}{FAQ_CSS}</style>
</head>
<body>
{nav_html()}
<div class="container">
  <div class="crumbs">
    <a href="/">Home</a> /
    <a href="/banks">Banks</a> /
    <a href="/banks/{bank_slug}">{bank}</a> /
    {intent_kicker}
  </div>

  <div style="display:inline-block;background:rgba(59,130,246,0.12);color:var(--accent);
              padding:4px 12px;border-radius:8px;font-size:12px;font-weight:600;
              text-transform:uppercase;letter-spacing:0.5px;margin-bottom:12px;">
    {intent_kicker}
  </div>
  <h1>{h1}</h1>
  <p class="subtitle">{subtitle}</p>
  {last_updated_html()}

  <p>{intro_para}</p>

  <div class="callout">
    <strong>Benchmark deal used on this page:</strong>
    <p style="margin:6px 0 0;">{intent['deal_caption']}</p>
  </div>

  <h2>{bank}'s fair-price floor on this deal</h2>
  <p>
    Running this benchmark against {bank}'s own Pillar 3 inputs — cost-to-income
    {profile.cost_to_income*100:.1f}%, effective tax rate {profile.effective_tax_rate*100:.1f}%,
    average corporate PD {profile.corporate_avg_pd*100:.2f}%, LGD bands at
    {profile.avg_lgd_unsecured*100:.0f}% unsecured / {profile.avg_lgd_secured*100:.0f}% secured —
    the engine returns a minimum spread of <strong>{floor_bp:.0f}bp</strong> to clear a 12%
    RAROC hurdle. At the deal's stated spread, the RAROC comes out at
    <strong>{raroc_pct:.2f}%</strong> — {verdict}.
  </p>

  <div class="stat-grid">
    <div class="stat-card">
      <div class="stat-label">Fair-price floor</div>
      <div class="stat-value">{floor_bp:.0f}bp</div>
      <div class="stat-sub">Min spread to clear 12% RAROC</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Sample RAROC</div>
      <div class="stat-value">{raroc_pct:.2f}%</div>
      <div class="stat-sub">At the deal's stated spread</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">vs cohort P50</div>
      <div class="stat-value">{('+' if delta_vs_p50 >= 0 else '')}{delta_vs_p50:.0f}bp</div>
      <div class="stat-sub">{n_cohort}-bank cohort median {p50:.0f}bp</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">IRB approach</div>
      <div class="stat-value" style="font-size:18px;">{profile.irb_approach}</div>
      <div class="stat-sub">Drives capital intensity</div>
    </div>
  </div>

  <h2>Why this number matters in a renegotiation</h2>
  <p>{mechanic_para}</p>

  <h2>{bank} versus the cohort</h2>
  <p>{cohort_position}</p>

  <table>
    <thead>
      <tr>
        <th>Cohort statistic</th>
        <th class="num">Min spread (bp)</th>
        <th>Interpretation</th>
      </tr>
    </thead>
    <tbody>
      <tr><td>P25 (cheapest quartile)</td><td class="num">{p25:.0f}bp</td><td>Tightest-pricing banks on this deal</td></tr>
      <tr><td>P50 (cohort median)</td><td class="num">{p50:.0f}bp</td><td>The middle of the market</td></tr>
      <tr><td>P75 (most-expensive quartile)</td><td class="num">{p75:.0f}bp</td><td>Wider than three quarters of peers</td></tr>
      <tr class="highlight"><td><strong>{bank}</strong></td><td class="num"><strong>{floor_bp:.0f}bp</strong></td><td>{verdict_phrase}</td></tr>
    </tbody>
  </table>

  <h2>Sample RAROC breakdown</h2>
  <table>
    <thead><tr><th>Component</th><th class="num">Value</th></tr></thead>
    <tbody>
      <tr><td>Annual revenue (spread + fees)</td><td class="num">{_format_money_eur(metrics['revenue'])}</td></tr>
      <tr><td>Operating cost</td><td class="num">{_format_money_eur(metrics['cost'])}</td></tr>
      <tr><td>Expected loss (PD x LGD x EAD)</td><td class="num">{_format_money_eur(metrics['expected_loss'])}</td></tr>
      <tr><td>Capital required (FPE)</td><td class="num">{_format_money_eur(metrics['fpe'])}</td></tr>
      <tr><td><strong>RAROC (after tax)</strong></td><td class="num"><strong>{raroc_pct:.2f}%</strong></td></tr>
      <tr><td>Min spread to hit 12% RAROC</td><td class="num">{floor_bp:.0f}bp</td></tr>
    </tbody>
  </table>

  <div class="cta">
    <h3>{cta_headline}</h3>
    <p>{cta_body}</p>
    <a href="{credenda_doctor}" class="btn btn-primary" rel="noopener" data-cta="credenda-doctor">
      {intent['cta_button']}
    </a>
    <p style="margin-top:12px;font-size:12px;color:var(--text3);">
      Powered by Credenda &middot;
      <a href="{credenda_landing}" rel="noopener" data-cta="credenda-landing">credenda.io</a>
    </p>
  </div>

  <h2>How to act on this in four steps</h2>
  <ol style="padding-left:20px;color:var(--text2);line-height:1.7;">
    {''.join(f'<li><strong>{name}.</strong> {text}</li>' for name, text in howto_steps)}
  </ol>

  {other_link_html}

  {faq_block}

  <h2>Data source</h2>
  <div class="source">
    {profile.source}
    {('<br><br>' + profile.notes) if profile.notes else ''}
    <br><br>
    <em>Confidence: {profile.confidence}</em> &middot;
    <a href="/methodology">Read the full RAROC methodology</a>
  </div>

  <div class="cta">
    <h3>Run the assessment on your own term sheet</h3>
    <p>Credenda's Term-Sheet Doctor scores any BBB+/-A/AA term sheet against {bank}'s public RAROC profile in under two minutes.</p>
    <a href="{credenda_doctor}" class="btn btn-primary" rel="noopener" data-cta="credenda-doctor-bottom">
      Open Term-Sheet Doctor
    </a>
  </div>
</div>
{footer_html()}
</body>
</html>"""
    return page
