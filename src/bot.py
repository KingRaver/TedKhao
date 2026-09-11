"""Thin orchestrator: wires signals -> state engine -> persona -> engagement -> database ->
posting into one cycle, per docs/STRUCTURE.md's design. Coordinates calls into signals/,
persona/, and engagement/ -- if this file starts growing business logic, that logic belongs
in one of those packages instead (see CLAUDE.md's "bot.py stays a thin orchestrator" rule).

Run modes:
    python bot.py --once              one cycle, then exit (for a launchd/cron-style job)
    python bot.py                     runs cycles on a timer loop (CYCLE_INTERVAL_MINUTES)
    python bot.py --live              actually publish to X instead of dry-run generate+persist

Either scheduling approach satisfies docs/SCAFFOLDING.md Phase 7's "timer loop, or launchd
job" item -- --once is the launchd-job shape, the default is the built-in timer loop.
"""
import argparse
import logging
import time
from urllib.parse import urlparse

from engagement.publication import publish
from engagement.post_handler import generate_post
from engagement.reply_handler import generate_reply
from llm_provider import get_provider
from persona.memory import PersonaMemory
from signals import arts_feed, arxiv_feed, hackernews_feed, history_today, timeline_scraper
from signals.base import Signal
import config

logger = logging.getLogger("tedkhao.bot")

_DOMAIN_SIGNAL_SOURCES = [arxiv_feed.fetch, history_today.fetch, hackernews_feed.fetch, arts_feed.fetch]


def fetch_all_signals() -> tuple[list[Signal], list[Signal]]:
    """Fetch the domain signal sources plus the timeline separately (not just pooled together)
    since timeline signals double as reply-candidate discovery in run_reply_cycle() -- fetching
    once here avoids a second Selenium launch for that. Each source is best-effort: one source
    failing (a down API, an unauthenticated timeline fetch) shouldn't sink the whole cycle."""
    domain_signals: list[Signal] = []
    for fetch in _DOMAIN_SIGNAL_SOURCES:
        try:
            domain_signals.extend(fetch())
        except Exception:
            logger.exception("signal source failed: %s", fetch.__module__)

    timeline_signals: list[Signal] = []
    try:
        timeline_signals = timeline_scraper.fetch()
    except Exception:
        logger.exception("timeline fetch failed (needs an authenticated session -- see "
                          "docs/SCAFFOLDING.md Phase 6)")

    return domain_signals, timeline_signals


def _parse_x_post_url(url: str) -> tuple[str | None, str | None]:
    """Extract (author_handle, post_id) from an x.com/<handle>/status/<id> permalink.

    signals.base.Signal has no author field (it's a source-agnostic content shape used by
    every signals/*.py module) so this reads the handle back out of the permalink
    timeline_scraper.py already captures, rather than widening Signal for one caller.
    Returns (None, None) if the URL doesn't match that shape -- a reply target needs both.
    """
    if not url:
        return None, None
    parts = urlparse(url).path.strip("/").split("/")
    if len(parts) >= 3 and parts[1] == "status" and parts[0]:
        return f"@{parts[0]}", parts[2]
    return None, None


def run_post_cycle(provider, memory: PersonaMemory, domain_signals: list[Signal],
                    timeline_signals: list[Signal], live_posting: bool) -> dict:
    result = generate_post(domain_signals + timeline_signals, provider, memory)
    logger.info("post generated: phase=%s register=%s signal=%s chars=%d",
                result["phase"].value, result["register"].value,
                result["signal"].source if result["signal"] else "none",
                len(result["post_text"]))

    if live_posting:
        result['publication_outcome'] = publish(result, memory)

    return result


def run_reply_cycle(provider, memory: PersonaMemory, timeline_signals: list[Signal],
                     live_posting: bool, max_replies: int) -> list[dict]:
    results = []
    for signal in timeline_signals:
        if len(results) >= max_replies:
            break

        author_handle, post_id = _parse_x_post_url(signal.url)
        if not post_id or memory.reply_is_held(post_id):
            continue

        post = {
            "id": post_id,
            "url": signal.url,
            "author_handle": author_handle or "@someone",
            "text": signal.summary or signal.title,
        }
        result = generate_reply(post, provider, memory)
        result["target_url"] = signal.url
        logger.info("reply generated: target=%s register=%s chars=%d",
                    post["author_handle"], result["register"].value, len(result["reply_text"]))

        if live_posting:
            result['publication_outcome'] = publish(result, memory, signal.url)

        results.append(result)

    return results


def run_cycle(provider, memory: PersonaMemory, live_posting: bool, max_replies: int) -> dict:
    domain_signals, timeline_signals = fetch_all_signals()
    post_result = run_post_cycle(provider, memory, domain_signals, timeline_signals, live_posting)
    reply_results = run_reply_cycle(provider, memory, timeline_signals, live_posting, max_replies)
    return {"post": post_result, "replies": reply_results}


def main() -> None:
    parser = argparse.ArgumentParser(description="TedKhao orchestrator")
    parser.add_argument("--once", action="store_true",
                         help="Run a single cycle and exit, instead of looping internally -- "
                              "the shape to invoke from an external launchd/cron job.")
    parser.add_argument("--live", action="store_true",
                         help="Publish generated posts/replies to X. Without this flag, bot.py "
                              "only generates and persists (dry run). Refused if "
                              "TWITTER_USERNAME/TWITTER_PASSWORD aren't set in .env.")
    parser.add_argument("--interval-minutes", type=int, default=config.CYCLE_INTERVAL_MINUTES,
                         help="Minutes between cycles when looping (ignored with --once).")
    parser.add_argument("--max-replies", type=int, default=config.REPLY_MAX_PER_CYCLE,
                         help="Max reply candidates to act on per cycle.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                         format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    live_posting = args.live or config.LIVE_POSTING_ENABLED
    if live_posting and not (config.TWITTER_USERNAME and config.TWITTER_PASSWORD):
        logger.warning("live posting requested but TWITTER_USERNAME/TWITTER_PASSWORD are not "
                        "set in .env -- running in dry-run mode instead.")
        live_posting = False
    logger.info("starting %s (live_posting=%s)", "single cycle" if args.once else "cycle loop",
                live_posting)

    provider = get_provider()
    memory = PersonaMemory()

    if args.once:
        run_cycle(provider, memory, live_posting, args.max_replies)
        return

    while True:
        try:
            run_cycle(provider, memory, live_posting, args.max_replies)
        except Exception:
            logger.exception("cycle failed, will retry after the next scheduled interval")
        time.sleep(args.interval_minutes * 60)


if __name__ == "__main__":
    main()
