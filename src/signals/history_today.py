"""Wikipedia "On this day" signal source -- history domain.

Public REST API, no auth needed (see docs/SPEC.md's Auth & Permissions). Pulls today's
historical anniversaries -- the reliable Anniversary-phase fallback described in
docs/SPEC.md's Phase taxonomy. Wikimedia's usage policy asks for a descriptive
User-Agent identifying the client, hence the header below.
"""
from datetime import datetime, timezone

import requests

from signals.base import Signal, rank_novelty

_API_URL = "https://en.wikipedia.org/api/rest_v1/feed/onthisday/events/{month}/{day}"
_USER_AGENT = "TedKhao/0.1 (signal ingestion; https://github.com/KingRaver/TedKhao)"


def fetch(max_results: int = 10) -> list[Signal]:
    """Fetch today's "on this day" historical events, most significant first."""
    now = datetime.now(timezone.utc)
    url = _API_URL.format(month=f"{now.month:02d}", day=f"{now.day:02d}")
    response = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=15)
    response.raise_for_status()

    events = (response.json().get("events") or [])[:max_results]

    signals = []
    for i, event in enumerate(events):
        text = (event.get("text") or "").strip()
        if not text:
            continue
        page = (event.get("pages") or [{}])[0]
        title = f"{event.get('year', '?')}: {text}"
        page_url = ((page.get("content_urls") or {}).get("desktop") or {}).get("page", "")
        signals.append(Signal(
            source="wikipedia_otd",
            domain="history",
            title=title,
            summary=(page.get("extract") or "").strip(),
            url=page_url,
            novelty_score=rank_novelty(i, len(events)),
        ))
    return signals
