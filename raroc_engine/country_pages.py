"""Country aggregator pages: ranks all banks in a given country.

Each page targets queries like "best banks France corporate lending",
"UK bank Pillar 3 RAROC", "German bank credit pricing".
"""

from typing import Dict, List, Optional, Tuple

from .banks import BANK_PROFILES, BankProfile
from .bank_pages import (
    PAGE_CSS,
    nav_html,
    footer_html,
    slug_for_key,
    country_slug,
    format_bn,
    _ranked_banks,
)
from .seo_helpers import (
    breadcrumb_jsonld,
    faq_jsonld,
    faq_html,
    FAQ_CSS,
    last_updated_html,
    data_last_updated_iso,
)


def all_country_slugs() -> List[str]:
    countries = set()
    for p in BANK_PROFILES.values():
        countries.add(country_slug(p.country))
    return sorted(countries)


def country_for_slug(slug: str) -> Optional[str]:
    for p in BANK_PROFILES.values():
        if country_slug(p.country) == slug:
            return p.country
    return None


def render_country_page(country: str) -> Optional[str]:
    ranked = _ranked_banks()
    in_country = [(k, p, m) for k, p, m in ranked if p.country == country]
    if not in_country:
        return None

    n = len(in_country)
    slug = country_slug(country)

    # Aggregates
    avg_ci = sum(p.cost_to_income for _, p, _ in in_country) / n
    avg_pd = sum(p.corporate_avg_pd for _, p, _ in in_country) / n
    avg_lgd = sum(p.avg_lgd_unsecured for _, p, _ in in_country) / n
    total_ead = sum(p.corporate_ead_bn for _, p, _ in in_country)
    avg_raroc = sum(m["raroc"] for _, _, m in in_country) / n
    cheapest = min(in_country, key=lambda r: r[2]["min_spread_bp"])
    most_expensive = max(in_country, key=lambda r: r[2]["min_spread_bp"])

    # Table rows
    rows_html = []
    for i, (k, p, m) in enumerate(in_country, 1):
        rows_html.append(
            f'<tr><td class="num">{i}</td>'
            f'<td><a href="/banks/{slug_for_key(k)}">{p.name}</a></td>'
            f'<td class="num">{p.cost_to_income*100:.1f}%</td>'
            f'<td class="num">{p.corporate_avg_pd*100:.2f}%</td>'
            f'<td class="num">{p.avg_lgd_unsecured*100:.1f}%</td>'
            f'<td class="num">{format_bn(p.corporate_ead_bn)}</td>'
            f'<td class="num"><strong>{m["raroc"]*100:.2f}%</strong></td>'
            f'<td class="num">{m["min_spread_bp"]:.0f}bp</td></tr>'
        )

    title = f"Corporate Banking in {country}: RAROC Comparison of {n} Banks | OpenRAROC"
    description = (
        f"How {n} {country} banks price corporate credit facilities, ranked by RAROC. "
        f"Average cost-to-income {avg_ci*100:.0f}%, average PD {avg_pd*100:.2f}%, "
        f"total corporate EAD {format_bn(total_ead)}. Real Pillar 3 data, free comparison tool."
    )
    canonical = f"https://openraroc.com/countries/{slug}"

    intro = (
        f"OpenRAROC tracks <strong>{n} banks headquartered in {country}</strong> with a combined corporate "
        f"credit exposure of {format_bn(total_ead)}. The average {country} bank in our dataset has a "
        f"cost-to-income ratio of <strong>{avg_ci*100:.1f}%</strong> and an average corporate probability of "
        f"default of <strong>{avg_pd*100:.2f}%</strong>. On a representative BBB+ EUR 25M 5-year term loan, "
        f"these banks generate an average RAROC of <strong>{avg_raroc*100:.2f}%</strong>."
    )

    # Schema.org helpers
    faqs = [
        (
            f"How many banks in {country} does OpenRAROC cover?",
            (
                f"OpenRAROC tracks {n} banks headquartered in {country}, with a combined corporate "
                f"credit exposure of {format_bn(total_ead)} reported in their most recent Pillar 3 "
                f"CR6 disclosures."
            ),
        ),
        (
            f"Which {country} bank has the tightest corporate credit pricing?",
            (
                f"On a representative BBB+ EUR 25M 5-year term loan, {cheapest[1].name} requires the "
                f"lowest minimum spread to clear a 12% RAROC hurdle ({cheapest[2]['min_spread_bp']:.0f}bp), "
                f"making it the cheapest lender in the {country} cohort on that specific deal."
            ),
        ),
        (
            f"What is the average cost-to-income ratio of {country} banks?",
            (
                f"The {n} {country} banks in the dataset report an average cost-to-income ratio of "
                f"{avg_ci*100:.1f}% and an EAD-weighted average corporate probability of default of "
                f"{avg_pd*100:.2f}%."
            ),
        ),
        (
            f"How is RAROC calculated for {country} banks?",
            (
                "Each bank is priced on the same BBB+ EUR 25M 5-year term loan, using its own "
                "disclosed cost-to-income, effective tax rate, funding spread, and IRB-approach "
                "PD/LGD parameters. See the methodology page for the full formula."
            ),
        ),
    ]
    faq_block = faq_html(faqs, heading=f"FAQ: corporate banking in {country}")
    faq_ld = faq_jsonld(faqs)
    breadcrumb_ld = breadcrumb_jsonld([
        ("Home", "https://openraroc.com/"),
        ("Banks", "https://openraroc.com/banks"),
        (country, f"https://openraroc.com/countries/{slug}"),
    ])

    insights = (
        f'<p>On the standard sample deal, <a href="/banks/{slug_for_key(cheapest[0])}"><strong>{cheapest[1].name}</strong></a> '
        f'is the cheapest lender in {country}, requiring just <strong>{cheapest[2]["min_spread_bp"]:.0f}bp</strong> '
        f'to hit a 12% RAROC hurdle. The most expensive is '
        f'<a href="/banks/{slug_for_key(most_expensive[0])}"><strong>{most_expensive[1].name}</strong></a> '
        f'at <strong>{most_expensive[2]["min_spread_bp"]:.0f}bp</strong> &mdash; '
        f'a difference of <strong>{most_expensive[2]["min_spread_bp"] - cheapest[2]["min_spread_bp"]:.0f}bp</strong> '
        f'on the same deal. For a EUR 25M facility, that&apos;s '
        f'EUR {(most_expensive[2]["min_spread_bp"] - cheapest[2]["min_spread_bp"]) * 25_000_000 / 10000:,.0f} per year '
        f'in interest expense.</p>'
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<meta name="description" content="{description}">
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="website">
<meta property="og:url" content="{canonical}">
<meta property="og:title" content="Corporate Banking in {country}: RAROC Comparison">
<meta property="og:description" content="{description}">
<meta property="og:site_name" content="OpenRAROC">
{faq_ld}
{breadcrumb_ld}
<meta property="article:modified_time" content="{data_last_updated_iso()}">
<style>{PAGE_CSS}{FAQ_CSS}</style>
</head>
<body>
{nav_html()}
<div class="container">
  <div class="crumbs"><a href="/">Home</a> / <a href="/banks">Banks</a> / {country}</div>
  <h1>Corporate Banking in {country}</h1>
  <p class="subtitle">RAROC profiles and pricing benchmarks for {n} {country} banks, sourced from Pillar 3 disclosures.</p>
  {last_updated_html()}

  <div class="stat-grid">
    <div class="stat-card">
      <div class="stat-label">Banks tracked</div>
      <div class="stat-value">{n}</div>
      <div class="stat-sub">Headquartered in {country}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Total corporate EAD</div>
      <div class="stat-value">{format_bn(total_ead)}</div>
      <div class="stat-sub">Combined exposure</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Avg cost-to-income</div>
      <div class="stat-value">{avg_ci*100:.1f}%</div>
      <div class="stat-sub">Operating efficiency</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Avg corporate PD</div>
      <div class="stat-value">{avg_pd*100:.2f}%</div>
      <div class="stat-sub">Probability of default</div>
    </div>
  </div>

  <h2>Overview</h2>
  <p>{intro}</p>

  <h2>Cheapest vs most expensive in {country}</h2>
  {insights}

  <h2>All {n} banks ranked by RAROC</h2>
  <p>RAROC computed on a representative BBB+ rated, 5-year, EUR 25M term loan at 150bp spread. Click any bank for its full profile.</p>
  <table>
    <thead><tr>
      <th>#</th><th>Bank</th><th class="num">C/I</th><th class="num">Avg PD</th>
      <th class="num">LGD</th><th class="num">EAD</th><th class="num">RAROC</th><th class="num">Min spread</th>
    </tr></thead>
    <tbody>
      {''.join(rows_html)}
    </tbody>
  </table>

  <div class="callout">
    <strong>Negotiating with a {country} bank?</strong>
    <p style="margin:8px 0 12px;">Upload your portfolio and OpenRAROC will run the same calculation on your real
    facilities, showing exactly which {country} bank should price your next deal best.</p>
    <a href="/app" class="btn btn-primary">Compare your portfolio</a>
  </div>

  <h2>Other countries</h2>
  <div class="peer-list">
    {''.join(_other_country_links(country))}
  </div>

  {faq_block}
</div>
{footer_html()}
</body>
</html>"""


def _other_country_links(current_country: str) -> List[str]:
    seen = set()
    out = []
    ranked = _ranked_banks()
    for _, p, _ in ranked:
        if p.country == current_country or p.country in seen:
            continue
        seen.add(p.country)
        out.append(f'<span class="peer-tag"><a href="/countries/{country_slug(p.country)}">{p.country}</a></span>')
    return out
