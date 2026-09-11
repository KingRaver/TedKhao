"""Thin orchestrator: wires signals -> state engine -> persona -> engagement -> database ->
posting into one cycle, per docs/STRUCTURE.md's design. Coordinates calls into signals/,
persona/, and engagement/ -- if this file starts growing business logic, that logic belongs
in one of those packages instead (see CLAUDE.md's "bot.py stays a thin orchestrator" rule).

Run modes:
    python bot.py --once              one cycle, then exit -- the browser it launches (only
                                       if live posting or timeline scraping happens) is closed
                                       with the process; the shape to invoke from an external
                                       launchd/cron job
    python bot.py                     resident timer loop (CYCLE_INTERVAL_MINUTES); a single
                                       browser session launches on first use and stays open
                                       across every cycle until the process exits (Ctrl+C) or
                                       a diagnosed crash forces a bounded relaunch -- RC-103.
                                       Use this mode, not --once on a cron schedule, when you
                                       want the browser to stay open between scheduled cycles.
    python bot.py --live              actually publish to X instead of dry-run generate+persist

If X asks for something a script can't clear -- a login/verification challenge, a rate limit,
an account warning -- the resident loop pauses X actions (browser.SessionPaused) rather than
retrying login automatically; run `python -c "from utils.browser import resume_manual_login as
r; r()"` after stopping this process to clear it by hand, then restart.
"""
import argparse
import logging
import time
from urllib.parse import urlparse

from selenium.common.exceptions import InvalidSessionIdException

from engagement.publication import publish
from engagement.post_handler import generate_post
from engagement.reply_handler import generate_reply
from llm_provider import get_provider
from persona.memory import PersonaMemory
from signals import arts_feed, arxiv_feed, hackernews_feed, history_today, timeline_scraper
from signals.base import Signal
from utils.browser import BrowserSession, SessionPaused
import config

logger = logging.getLogger("tedkhao.bot")

_DOMAIN_SIGNAL_SOURCES = [arxiv_feed.fetch, history_today.fetch, hackernews_feed.fetch, arts_feed.fetch]
# Bounded per-cycle recovery: a single diagnosed browser crash gets one relaunch-and-retry: a
# second crash in the same cycle propagates instead of looping indefinitely.
_MAX_CRASH_RECOVERIES_PER_CYCLE = 1


def _with_crash_recovery(session: BrowserSession, action):
    """Run action() (a zero-arg callable that uses session.driver). On a diagnosed browser
    crash (InvalidSessionIdException -- the driver's underlying session/process is gone, not
    just a slow page or missing selector) replace the driver once and retry; a repeat crash in
    the same call propagates rather than relaunching indefinitely."""
    attempts = 0
    while True:
        try:
            return action()
        except InvalidSessionIdException as error:
            if attempts >= _MAX_CRASH_RECOVERIES_PER_CYCLE:
                raise
            attempts += 1
            session.replace_after_failure(f"{type(error).__name__}: {error}")


def fetch_all_signals(session: BrowserSession | None) -> tuple[list[Signal], list[Signal]]:
    """Fetch the domain signal sources plus the timeline separately (not just pooled together)
    since timeline signals double as reply-candidate discovery in run_reply_cycle() -- sharing
    session avoids a second Selenium launch for that. Every source here, timeline included, is
    best-effort: a down API or a paused/unauthenticated browser session degrades to an empty
    result rather than sinking the whole cycle, so dry-run post generation from domain signals
    alone keeps working with no X session at all. Live posting's own pause behavior is
    separate -- run_post_cycle()/run_reply_cycle() let SessionPaused propagate out of
    publish() itself, since that is the point where actually posting through a paused session
    would matter."""
    domain_signals: list[Signal] = []
    for fetch in _DOMAIN_SIGNAL_SOURCES:
        try:
            domain_signals.extend(fetch())
        except Exception:
            logger.exception("signal source failed: %s", fetch.__module__)

    timeline_signals: list[Signal] = []
    if session is not None:
        try:
            timeline_signals = _with_crash_recovery(session, lambda: timeline_scraper.fetch(session))
        except SessionPaused:
            # A read-only scrape degrading gracefully (post generation still has the domain
            # signals) is not the same stakes as live posting through a paused session --
            # run_post_cycle()/run_reply_cycle() let SessionPaused propagate from publish()
            # itself, which is where "pause X actions" actually needs to stop the cycle.
            logger.warning("skipping timeline fetch -- X session needs a human (see "
                            "utils.browser.resume_manual_login()); continuing this cycle "
                            "without timeline signals")
        except Exception:
            logger.exception("timeline fetch failed (needs an authenticated session)")

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
                    timeline_signals: list[Signal], live_posting: bool,
                    session: BrowserSession | None = None) -> dict:
    if live_posting and session is None:
        raise ValueError("live_posting requires a BrowserSession -- see main()'s session setup")

    result = generate_post(domain_signals + timeline_signals, provider, memory)
    logger.info("post generated: phase=%s register=%s signal=%s chars=%d",
                result["phase"].value, result["register"].value,
                result["signal"].source if result["signal"] else "none",
                len(result["post_text"]))

    if live_posting:
        result['publication_outcome'] = _with_crash_recovery(
            session, lambda: publish(result, memory, session))

    return result


def run_reply_cycle(provider, memory: PersonaMemory, timeline_signals: list[Signal],
                     live_posting: bool, max_replies: int,
                     session: BrowserSession | None = None) -> list[dict]:
    if live_posting and session is None:
        raise ValueError("live_posting requires a BrowserSession -- see main()'s session setup")

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
            result['publication_outcome'] = _with_crash_recovery(
                session, lambda: publish(result, memory, session, signal.url))

        results.append(result)

    return results


def run_cycle(provider, memory: PersonaMemory, live_posting: bool, max_replies: int,
              session: BrowserSession | None = None) -> dict:
    domain_signals, timeline_signals = fetch_all_signals(session)
    post_result = run_post_cycle(provider, memory, domain_signals, timeline_signals,
                                  live_posting, session)
    reply_results = run_reply_cycle(provider, memory, timeline_signals, live_posting,
                                     max_replies, session)
    return {"post": post_result, "replies": reply_results}


def main() -> None:
    parser = argparse.ArgumentParser(description="TedKhao orchestrator")
    parser.add_argument("--once", action="store_true",
                         help="Run a single cycle and exit, instead of looping internally -- "
                              "the shape to invoke from an external launchd/cron job. The "
                              "browser this cycle opens closes with the process; use the "
                              "resident loop (no --once) to keep it open between cycles.")
    parser.add_argument("--live", action="store_true",
                         help="Publish generated posts/replies to X. Without this flag, bot.py "
                              "only generates and persists (dry run). Refused if "
                              "TWITTER_USERNAME/TWITTER_PASSWORD aren't set in .env.")
    parser.add_argument("--interval-minutes", type=int, default=config.CYCLE_INTERVAL_MINUTES,
                         help="Minutes between cycles when looping (ignored with --once).")
    parser.add_argument("--max-replies", type=int, default=config.REPLY_MAX_PER_CYCLE,
                         help="Max reply candidates to act on per cycle.")
    parser.add_argument("--visible", dest="headless", action="store_false", default=True,
                         help="Run Chrome with a visible window instead of headless. The "
                              "normal path for clearing a login/verification challenge is "
                              "resume_manual_login() run separately (see module docstring), "
                              "not this flag.")
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
    # One session, owned here, for the whole process -- RC-103. run_cycle() never launches or
    # quits its own driver; every cycle (one for --once, every iteration for the resident
    # loop) shares this same browser instead of relaunching Chrome per action.
    session = BrowserSession(headless=args.headless)

    try:
        if args.once:
            try:
                run_cycle(provider, memory, live_posting, args.max_replies, session)
            except SessionPaused:
                logger.error("X session needs a human -- run resume_manual_login() (see this "
                              "module's docstring) to clear it, then retry. Not attempting "
                              "automatic login.")
            return

        while True:
            try:
                run_cycle(provider, memory, live_posting, args.max_replies, session)
            except SessionPaused:
                logger.error("X session needs a human -- pausing X actions until "
                              "resume_manual_login() clears it (see this module's docstring). "
                              "Not retrying login automatically.")
            except Exception:
                logger.exception("cycle failed, will retry after the next scheduled interval")
            time.sleep(args.interval_minutes * 60)
    except KeyboardInterrupt:
        logger.info("interrupted -- shutting down cleanly")
    finally:
        session.close()


if __name__ == "__main__":
    main()
