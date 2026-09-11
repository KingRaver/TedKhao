"""Hacker News signal source -- technology domain (trending discussion).

Public Firebase API, no auth needed (see docs/SPEC.md's Auth & Permissions). Pulls the
current top stories -- what technologists are actively discussing right now.
"""
import requests

from signals.base import Signal, rank_novelty

_TOP_STORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{item_id}.json"


def fetch(max_results: int = 10) -> list[Signal]:
    """Fetch the current top stories, ranked order."""
    response = requests.get(_TOP_STORIES_URL, timeout=15)
    response.raise_for_status()
    story_ids = response.json()[:max_results]

    signals = []
    for i, story_id in enumerate(story_ids):
        item_response = requests.get(_ITEM_URL.format(item_id=story_id), timeout=15)
        item_response.raise_for_status()
        item = item_response.json() or {}
        title = item.get("title")
        if not title:
            continue
        signals.append(Signal(
            source="hackernews",
            domain="technology",
            title=title,
            summary=f"{item.get('score', 0)} points, {item.get('descendants', 0)} comments",
            url=item.get("url") or f"https://news.ycombinator.com/item?id={story_id}",
            novelty_score=rank_novelty(i, len(story_ids)),
        ))
    return signals
