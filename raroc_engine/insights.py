"""Long-form pillar content (insights articles).

These are evergreen, comprehensive articles that target high-intent queries
and serve as link-worthy assets for backlink building (HN, LinkedIn, etc.).
"""

from typing import Dict, List, Optional

from .bank_pages import PAGE_CSS, nav_html, footer_html


# ── Article registry ─────────────────────────────────────────────────

ARTICLES: Dict[str, dict] = {
    "read-pillar-3-disclosures": {
        "title": "How to Read Bank Pillar 3 Disclosures to Negotiate Better Corporate Loan Pricing",
        "description": (
            "A practical guide for corporate treasurers: how to extract a bank's true cost of "
            "lending from their Pillar 3 regulatory filings — and use it as leverage in your "
            "next credit negotiation. With a worked example."
        ),
        "published": "2026-04-07",
        "reading_time": "12 min read",
    },
}


def all_article_slugs() -> List[str]:
    return list(ARTICLES.keys())


def render_article(slug: str) -> Optional[str]:
    meta = ARTICLES.get(slug)
    if not meta:
        return None
    body_fn = _ARTICLE_BODIES.get(slug)
    if not body_fn:
        return None
    body = body_fn()

    canonical = f"https://openraroc.com/insights/{slug}"

    import json
    article_jsonld = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": meta["title"],
        "description": meta["description"],
        "datePublished": meta["published"],
        "dateModified": meta["published"],
        "author": {"@type": "Organization", "name": "OpenRAROC"},
        "publisher": {"@type": "Organization", "name": "OpenRAROC", "url": "https://openraroc.com"},
        "url": canonical,
        "mainEntityOfPage": {"@type": "WebPage", "@id": canonical},
    }

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{meta["title"]} | OpenRAROC</title>
<meta name="description" content="{meta["description"]}">
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="article">
<meta property="og:url" content="{canonical}">
<meta property="og:title" content="{meta["title"]}">
<meta property="og:description" content="{meta["description"]}">
<meta property="og:site_name" content="OpenRAROC">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{meta["title"]}">
<meta name="twitter:description" content="{meta["description"]}">
<script type="application/ld+json">{json.dumps(article_jsonld)}</script>
<style>
{PAGE_CSS}
.article {{ max-width:760px; }}
.article h2 {{ font-size:24px; margin-top:42px; }}
.article h3 {{ font-size:18px; margin:28px 0 10px; color:#fff; }}
.article p {{ font-size:16px; line-height:1.75; margin-bottom:18px; }}
.article ul, .article ol {{ margin:0 0 18px 28px; color:var(--text2); }}
.article li {{ margin-bottom:8px; line-height:1.7; }}
.article blockquote {{ border-left:3px solid var(--accent); padding:6px 18px; margin:24px 0; color:var(--text); font-style:italic; background:var(--surface); border-radius:6px; }}
.article code {{ background:var(--surface); padding:2px 6px; border-radius:4px; font-size:14px; color:var(--accent); }}
.article .meta {{ color:var(--text3); font-size:13px; margin-bottom:8px; }}
</style>
</head>
<body>
{nav_html()}
<div class="container article">
  <div class="crumbs"><a href="/">Home</a> / <a href="/insights">Insights</a> / Article</div>
  <div class="meta">{meta["published"]} &middot; {meta["reading_time"]}</div>
  <h1>{meta["title"]}</h1>
  {body}

  <div class="cta">
    <h3>Want to skip the spreadsheet?</h3>
    <p>OpenRAROC does this calculation for 59 banks automatically. Upload your portfolio and see who's overcharging you.</p>
    <a href="/app" class="btn btn-primary">Open the calculator</a>
  </div>
</div>
{footer_html()}
</body>
</html>"""


# ── Article bodies ───────────────────────────────────────────────────

def _body_pillar_3():
    return """
<p>Most corporate treasurers accept the spread their relationship bank quotes them. They might shop the deal to two or three other banks, take the lowest number, and call it done. That's how you leave money on the table.</p>

<p>Here's the secret: every bank that lends to corporates publishes a regulatory filing called the <strong>Pillar 3 disclosure</strong>. Buried in those filings is everything you need to estimate the bank's <em>true</em> internal cost of lending to you &mdash; their probability-of-default model, their loss-given-default assumptions, their cost-to-income ratio, their effective tax rate. From that, you can compute the minimum spread that bank must charge you to hit its internal hurdle rate.</p>

<p>That number is your negotiating floor. Anything above it is the bank's margin. Everything in this article is built on public data &mdash; no insider information needed.</p>

<h2>What is a Pillar 3 disclosure?</h2>

<p>Under the Basel framework, banks must hold capital against their risk-weighted assets. Pillar 1 sets the minimum capital ratios. Pillar 2 covers the supervisory review process. <strong>Pillar 3</strong> is the public disclosure requirement: every bank above a certain size must publish detailed information about its risk profile so that investors and counterparties can assess it.</p>

<p>For your purposes, the Pillar 3 report is gold. It contains hundreds of standardised tables (called templates) covering credit risk, market risk, operational risk, liquidity, and capital. The one you care about is the <strong>CR6 template</strong>.</p>

<h2>The CR6 template, decoded</h2>

<p>CR6 is the table that breaks down the bank's credit risk exposures by exposure class, by IRB approach, and by PD band. For corporate lending, you want the row labelled "Corporates &mdash; Other" (sometimes split between A-IRB and F-IRB).</p>

<p>What you'll find in that row:</p>

<ul>
  <li><strong>EAD</strong> (Exposure at Default): the total euro/dollar amount the bank has lent to non-financial corporates, weighted for off-balance-sheet commitments.</li>
  <li><strong>Average PD</strong> (Probability of Default): the EAD-weighted probability that any given corporate borrower will default in the next 12 months. Typically 0.5%-5% depending on the portfolio mix.</li>
  <li><strong>Average LGD</strong> (Loss Given Default): the percentage of the exposure the bank expects to lose if a borrower defaults. For unsecured corporate lending, usually 30-45%.</li>
  <li><strong>Risk-weighted assets (RWA)</strong>: the regulatory capital base for this portfolio.</li>
  <li><strong>Number of obligors</strong>: how many borrowers the bank has, useful for spotting concentration.</li>
</ul>

<p>Together, PD, LGD, and EAD let you compute the bank's <strong>expected loss</strong>: <code>EL = PD × LGD × EAD</code>. That's the steady-state credit cost the bank prices into every loan.</p>

<h3>Where to find the file</h3>

<p>Every European bank publishes its Pillar 3 disclosure on its investor relations website, usually as a PDF (often 100+ pages). Look for filenames like <code>pillar-3-2025.pdf</code> or <code>additional-pillar-3-disclosures.pdf</code>. They're updated semi-annually for large banks and annually for smaller ones.</p>

<p>The European Banking Authority's <a href="https://www.eba.europa.eu/regulation-and-policy/transparency-and-pillar-3">Pillar 3 Data Hub</a> centralises these disclosures from late 2025 onwards. Until that's fully populated, the bank's own website is the canonical source.</p>

<h2>Cost-to-income and tax rate (the rest of the puzzle)</h2>

<p>CR6 gives you the credit risk side of the equation. To compute RAROC you also need:</p>

<ul>
  <li><strong>Cost-to-income ratio</strong>: from the bank's annual report or quarterly results. Operating expenses divided by net banking income. European banks run anywhere from 38% (UniCredit) to 70% (Deutsche Bank, Commerzbank). This determines how much overhead the bank loads onto each loan.</li>
  <li><strong>Effective tax rate</strong>: also from the annual report. Income tax expense divided by pre-tax profit. Typically 20-30% in Europe. This is applied to the after-cost return.</li>
  <li><strong>Funding cost</strong>: how expensive is the bank's wholesale funding above risk-free? You can approximate this from the bank's senior unsecured bond spreads. Usually 10-25bp for investment-grade European banks.</li>
</ul>

<h2>Putting it together: the RAROC formula</h2>

<p>The simplified RAROC formula a bank uses to evaluate your deal is:</p>

<blockquote>
RAROC = (1 &minus; Tax Rate) × [ (Revenue &minus; Operating Cost &minus; Funding Cost &minus; Expected Loss) / Capital Required + Risk-Free Rate ]
</blockquote>

<p>Where:</p>

<ul>
  <li><strong>Revenue</strong> = your spread × drawn × maturity + commitment fees + upfront fees</li>
  <li><strong>Operating cost</strong> = revenue × cost-to-income ratio (the C/I ratio you pulled from the annual report)</li>
  <li><strong>Funding cost</strong> = funding spread × exposure</li>
  <li><strong>Expected loss</strong> = PD × LGD × EAD (your individual deal's contribution)</li>
  <li><strong>Capital required</strong> = RWA × bank capital ratio (typically 10.5% for a fully-loaded CET1 + buffers)</li>
</ul>

<p>The bank's internal hurdle rate is usually 10-15% (12% is the European norm). If your deal generates RAROC above that hurdle, the bank makes economic profit. Below it, the bank is losing money on a risk-adjusted basis &mdash; even if the loan looks profitable on a cash basis.</p>

<h2>A worked example</h2>

<p>Suppose you're negotiating a EUR 25M, 5-year unsecured term loan with a major European bank. You're rated BBB+. The bank quotes you 175bp over EURIBOR plus a 25bp commitment fee.</p>

<p>From the bank's most recent Pillar 3 CR6 template, you find:</p>

<ul>
  <li>Average corporate PD: 1.5%</li>
  <li>Average LGD unsecured: 40%</li>
  <li>Cost-to-income: 60%</li>
  <li>Effective tax rate: 25%</li>
  <li>Funding spread: 15bp</li>
</ul>

<p>You apply the standard Basel III formula for RWA on a BBB+ rated corporate exposure (PD = 0.20%, LGD = 40%, M = 5 years), and you get a risk weight of about 80%. So RWA on EUR 25M is EUR 20M, and capital required is EUR 20M × 10.5% = EUR 2.1M.</p>

<p>Annual revenue: 175bp × 25M = EUR 437,500 in spread, plus 25bp × 5M of commitment = EUR 12,500. Total EUR 450,000.</p>

<p>Operating cost: EUR 450,000 × 60% = EUR 270,000.</p>

<p>Funding: 15bp × 25M = EUR 37,500.</p>

<p>Expected loss: 0.20% × 40% × 25M = EUR 20,000.</p>

<p>Net pre-tax profit: 450,000 &minus; 270,000 &minus; 37,500 &minus; 20,000 = EUR 122,500.</p>

<p>RAROC: 75% × (122,500 / 2,100,000 + risk-free rate of 3.25%) = 75% × (5.83% + 3.25%) = <strong>6.81%</strong>.</p>

<p>That's well below the bank's 12% hurdle. <strong>The bank is overcharging itself relative to its own capital cost.</strong> You have room to push for a tighter spread.</p>

<p>To hit a 12% RAROC, the bank actually needs about 235bp of spread on this deal &mdash; meaning the 175bp quote is already discounted vs the bank's internal floor. But here's the key: knowing the bank's true cost lets you understand <em>why</em> they offered 175bp (relationship discount) and gives you a defensible counter-position when they push back.</p>

<h2>How to use this in negotiations</h2>

<p>Walk into the room with three numbers:</p>

<ol>
  <li><strong>The bank's minimum spread</strong> for your specific deal at their internal hurdle rate.</li>
  <li><strong>The competing bank's minimum spread</strong> for the same deal, computed the same way.</li>
  <li><strong>The actual spread you've been quoted.</strong></li>
</ol>

<p>You'll often discover that the bank's quote is 30-80bp above what their own model justifies. That gap is the relationship premium &mdash; or, less charitably, the lazy-treasurer premium. Either way, it's negotiable.</p>

<p>Banks respect counterparties who understand their economics. Showing up with a Pillar 3 analysis tells them: this borrower is sophisticated, this borrower has alternatives, this borrower will not accept your default quote. Often the spread comes down without you ever having to threaten to switch banks.</p>

<h2>Limitations</h2>

<p>Pillar 3 disclosures are aggregate figures for the bank's entire corporate portfolio. The PD they report is the EAD-weighted average across all corporates &mdash; including some BB-rated names that pull the number up. For a BBB+ borrower, the bank's internal PD for you is typically lower than the portfolio average. So your true minimum spread is usually a bit tighter than the back-of-envelope calculation suggests.</p>

<p>The cost-to-income ratio reflects the whole bank, not the corporate banking division specifically. Investment banking is more expensive to run than retail; a bank with a heavy IB business has a higher C/I than its corporate lending arm in isolation.</p>

<p>The risk weight you use for your deal depends on whether the bank is on the standardised approach or IRB. F-IRB uses regulatory LGD; A-IRB uses the bank's own LGD model. Pillar 3 tells you which approach the bank uses.</p>

<p>None of these limitations invalidate the exercise &mdash; they're just refinements. The first-pass calculation gets you 80% of the way to a useful negotiating number.</p>

<h2>The shortcut</h2>

<p>The above is the manual approach. It takes 30-60 minutes per bank if you know what you're doing, plus an hour or two of one-time setup to find the right templates and build the spreadsheet.</p>

<p>OpenRAROC does this for 59 banks automatically. Every Pillar 3 number is already extracted, kept up to date, and plugged into a Basel III RAROC calculator. You upload your portfolio, and the tool tells you what minimum spread each bank needs on each of your facilities. <a href="/app">Try it free</a> &mdash; it works on 4 banks in the free tier and all 59 in the EUR 49/year Pro tier.</p>

<p>Either way: the next time your relationship bank quotes you a spread, you'll know whether they're being fair.</p>
"""


_ARTICLE_BODIES = {
    "read-pillar-3-disclosures": _body_pillar_3,
}


def render_insights_index() -> str:
    cards = ""
    for slug, meta in ARTICLES.items():
        cards += f"""
<a href="/insights/{slug}" class="article-card">
  <div class="article-meta">{meta["published"]} &middot; {meta["reading_time"]}</div>
  <h3>{meta["title"]}</h3>
  <p>{meta["description"]}</p>
</a>
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Insights &mdash; Corporate Treasury & Bank Pricing | OpenRAROC</title>
<meta name="description" content="Practical guides for corporate treasurers on bank pricing, RAROC calculation, Pillar 3 analysis, and negotiating credit facilities.">
<link rel="canonical" href="https://openraroc.com/insights">
<style>
{PAGE_CSS}
.article-card {{ display:block; background:var(--surface); border:1px solid var(--border); border-radius:14px; padding:24px 28px; margin-bottom:18px; color:var(--text); transition:border-color 0.15s; }}
.article-card:hover {{ border-color:var(--accent); text-decoration:none; }}
.article-card h3 {{ font-size:20px; margin:6px 0 10px; color:#fff; }}
.article-card p {{ color:var(--text2); margin:0; font-size:14px; }}
.article-meta {{ color:var(--text3); font-size:12px; }}
</style>
</head>
<body>
{nav_html()}
<div class="container">
  <div class="crumbs"><a href="/">Home</a> / Insights</div>
  <h1>Insights</h1>
  <p class="subtitle">Practical guides for corporate treasurers on bank pricing, RAROC, and credit negotiations.</p>
  {cards}
</div>
{footer_html()}
</body>
</html>"""
