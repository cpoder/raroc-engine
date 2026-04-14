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
