"""arXiv signal source -- technology domain.

Public Atom API, no auth needed (see docs/SPEC.md's Auth & Permissions). Pulls the most
recent submissions across a fixed set of CS/AI categories likely to produce genuine
"a new paper just dropped" material.
"""
import xml.etree.ElementTree as ET

import requests

from signals.base import Signal, rank_novelty

_API_URL = "http://export.arxiv.org/api/query"
_CATEGORIES = ["cs.AI", "cs.CL", "cs.LG"]
_NS = {"atom": "http://www.w3.org/2005/Atom"}


def fetch(max_results: int = 10) -> list[Signal]:
    """Fetch the most recent papers across _CATEGORIES, newest submission first."""
    query = " OR ".join(f"cat:{cat}" for cat in _CATEGORIES)
    response = requests.get(
        _API_URL,
        params={
            "search_query": query,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "max_results": max_results,
        },
        timeout=15,
    )
    response.raise_for_status()

    entries = ET.fromstring(response.content).findall("atom:entry", _NS)

    signals = []
    for i, entry in enumerate(entries):
        title = (entry.findtext("atom:title", default="", namespaces=_NS) or "").strip()
        summary = (entry.findtext("atom:summary", default="", namespaces=_NS) or "").strip()
        url = (entry.findtext("atom:id", default="", namespaces=_NS) or "").strip()
        if not title:
            continue
        signals.append(Signal(
            source="arxiv",
            domain="technology",
            title=" ".join(title.split()),
            summary=" ".join(summary.split()),
            url=url,
            novelty_score=rank_novelty(i, len(entries)),
        ))
    return signals
