"""Met Museum signal source -- arts domain.

Public Open Access Collection API, no auth needed (see docs/SPEC.md's Auth & Permissions).
docs/SPEC.md also names Rijksmuseum and Smithsonian for this domain, but both require a
registered API key that isn't configured in .env yet -- add a sibling module following this
same fetch() shape once those keys land. Met alone covers the arts domain for now.
"""
import random

import requests

from signals.base import Signal, rank_novelty

_SEARCH_URL = "https://collectionapi.metmuseum.org/public/collection/v1/search"
_OBJECT_URL = "https://collectionapi.metmuseum.org/public/collection/v1/objects/{object_id}"


def fetch(max_results: int = 10) -> list[Signal]:
    """Fetch a random sample of highlighted Met collection objects with images."""
    response = requests.get(
        _SEARCH_URL,
        params={"q": "art", "hasImages": "true", "isHighlight": "true"},
        timeout=15,
    )
    response.raise_for_status()
    object_ids = response.json().get("objectIDs") or []
    sample_ids = random.sample(object_ids, min(max_results, len(object_ids)))

    signals = []
    for i, object_id in enumerate(sample_ids):
        obj_response = requests.get(_OBJECT_URL.format(object_id=object_id), timeout=15)
        obj_response.raise_for_status()
        obj = obj_response.json() or {}
        title = obj.get("title")
        if not title:
            continue
        artist = obj.get("artistDisplayName") or "Unknown artist"
        date = obj.get("objectDate") or ""
        signals.append(Signal(
            source="met_museum",
            domain="arts",
            title=title,
            summary=", ".join(part for part in (artist, date) if part),
            url=obj.get("objectURL", ""),
            novelty_score=rank_novelty(i, len(sample_ids)),
        ))
    return signals
