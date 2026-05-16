"""Shared SEO helpers: FAQ + Breadcrumb JSON-LD, "last updated" dates."""

import json
import os
import datetime as _dt
from functools import lru_cache
from typing import List, Tuple


@lru_cache(maxsize=1)
def data_last_updated() -> str:
    """Return a human-friendly month-year for the bank dataset.

    Derived from the mtime of premium_banks.json (where bank data lives).
    Falls back to today if the file is missing.
    """
    candidates = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "premium_banks.json"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "premium_banks.json"),
    ]
    for path in candidates:
        if os.path.exists(path):
            ts = os.path.getmtime(path)
            return _dt.datetime.fromtimestamp(ts).strftime("%B %Y")
    return _dt.datetime.now().strftime("%B %Y")


@lru_cache(maxsize=1)
def data_last_updated_iso() -> str:
    """ISO-8601 date string of last data update (for schema.org dateModified)."""
    candidates = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "premium_banks.json"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "premium_banks.json"),
    ]
    for path in candidates:
        if os.path.exists(path):
            ts = os.path.getmtime(path)
            return _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    return _dt.datetime.now().strftime("%Y-%m-%d")


def last_updated_html() -> str:
    """Inline HTML snippet showing the last-updated date."""
    return (
        f'<div style="font-size:12px;color:var(--text3);margin-bottom:18px;">'
        f'Last updated: {data_last_updated()} &middot; Data source: public Pillar 3 disclosures'
        f'</div>'
    )


def breadcrumb_jsonld(items: List[Tuple[str, str]]) -> str:
    """Build a BreadcrumbList JSON-LD block.

    items: list of (name, absolute_url) from root to current page.
    """
    data = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": i + 1,
                "name": name,
                "item": url,
            }
            for i, (name, url) in enumerate(items)
        ],
    }
    return f'<script type="application/ld+json">{json.dumps(data)}</script>'


def faq_jsonld(qas: List[Tuple[str, str]]) -> str:
    """Build a FAQPage JSON-LD block. qas: list of (question, answer_text)."""
    data = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": q,
                "acceptedAnswer": {"@type": "Answer", "text": a},
            }
            for q, a in qas
        ],
    }
    return f'<script type="application/ld+json">{json.dumps(data)}</script>'


def faq_html(qas: List[Tuple[str, str]], heading: str = "Frequently asked questions") -> str:
    """Render the FAQ block as visible HTML too (Google wants the text to appear on-page)."""
    items = "".join(
        f'<details class="faq-item"><summary>{q}</summary><div class="faq-answer">{a}</div></details>'
        for q, a in qas
    )
    return (
        f'<h2>{heading}</h2>'
        f'<div class="faq-block">{items}</div>'
    )


FAQ_CSS = """
.faq-block { display:flex; flex-direction:column; gap:10px; margin:12px 0 8px; }
.faq-item { background:var(--surface); border:1px solid var(--border); border-radius:10px; padding:14px 18px; }
.faq-item summary { cursor:pointer; font-weight:600; color:#fff; font-size:15px; list-style:none; }
.faq-item summary::-webkit-details-marker { display:none; }
.faq-item summary::before { content:'+ '; color:var(--accent); margin-right:6px; font-weight:700; }
.faq-item[open] summary::before { content:'- '; }
.faq-item[open] summary { margin-bottom:8px; }
.faq-answer { color:var(--text2); font-size:14px; line-height:1.6; }
"""


# ── Transactional / funnel helpers ──────────────────────────────────
#
# The OpenRAROC programmatic pages are the top of the funnel; the
# Credenda App (credenda.io) is the conversion. Outgoing CTAs use a
# ``?ref=`` parameter so the Credenda landing page can attribute the
# session against its first-touch cookie (see Credenda D-0008,
# ``credenda/landing/routes.py``).
#
# The ref slug format is intentionally readable: ``openraroc-<bank>-<intent>``
# (e.g. ``openraroc-bnp-paribas-renegotiate-rcf``). It is the same shape
# as a UTM source/medium concatenation, but lives in a single key so it
# survives copy/paste and email forwarding.

CREDENDA_BASE_URL = "https://credenda.io"


def credenda_ref(bank_slug: str, intent_slug: str) -> str:
    """Build the ``?ref=`` parameter for a Credenda-bound CTA."""
    return f"openraroc-{bank_slug}-{intent_slug}"


def credenda_cta_url(bank_slug: str, intent_slug: str, path: str = "/") -> str:
    """Absolute URL to Credenda with first-touch attribution attached.

    The landing path defaults to ``/`` because Credenda's attribution
    cookie is set on the landing route (D-0008). Deep-links into Module
    A still work; the cookie just needs a ``/`` visit somewhere in the
    same session.
    """
    sep = "&" if "?" in path else "?"
    return f"{CREDENDA_BASE_URL}{path}{sep}ref={credenda_ref(bank_slug, intent_slug)}"


def howto_jsonld(name: str, description: str, steps: List[Tuple[str, str]]) -> str:
    """Build a HowTo JSON-LD block.

    ``steps`` is a list of (name, text) tuples — each is rendered as a
    schema.org HowToStep. Used on transactional pages so the search
    engine understands the page is an actionable guide, not a marketing
    splash.
    """
    data = {
        "@context": "https://schema.org",
        "@type": "HowTo",
        "name": name,
        "description": description,
        "step": [
            {
                "@type": "HowToStep",
                "position": i + 1,
                "name": step_name,
                "text": step_text,
            }
            for i, (step_name, step_text) in enumerate(steps)
        ],
    }
    return f'<script type="application/ld+json">{json.dumps(data)}</script>'


def article_jsonld(
    *,
    headline: str,
    description: str,
    url: str,
    author: str = "OpenRAROC",
    date_modified: str = "",
) -> str:
    """Build an Article JSON-LD block for transactional / editorial pages."""
    data = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": headline,
        "description": description,
        "author": {"@type": "Organization", "name": author},
        "publisher": {"@type": "Organization", "name": "OpenRAROC"},
        "url": url,
        "dateModified": date_modified or data_last_updated_iso(),
    }
    return f'<script type="application/ld+json">{json.dumps(data)}</script>'
