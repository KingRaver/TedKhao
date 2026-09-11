"""Manual test harness: prove utils/browser.py's WebDriver setup and BrowserSession (RC-103)
actually work against real Chrome, and surface (without hard-asserting) what's reachable
against the live X site.

Uses plain asserts for the parts within this codebase's control (Chrome launches headless,
navigates, quits cleanly) -- not pytest, no automated suite exists yet (Phase 9). The
X-specific check only ever calls BrowserSession.ensure_ready()'s read-only is_logged_in()
check -- never log_in(), post_tweet(), or post_reply() -- so running this harness never
touches a real account, even once credentials are configured. Run with:

    python tests/manual_test_browser.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import config  # noqa: E402
from utils import browser  # noqa: E402
from utils.browser import BrowserSession, SessionPaused  # noqa: E402


def test_driver_launches_headless() -> None:
    driver = browser.get_driver()
    try:
        driver.get("https://example.com")
        assert "Example" in driver.title, f"unexpected title: {driver.title!r}"
    finally:
        driver.quit()
    print("  headless Chrome launch + navigate + quit: OK")


def test_session_reachability_and_login_state() -> None:
    session = BrowserSession()
    try:
        try:
            session.ensure_ready()
            print("  BrowserSession authenticated against the persisted profile")
        except SessionPaused:
            print("  BrowserSession reached x.com/home but found no authenticated session "
                  "(expected until a real login happens -- see resume_manual_login())")
    finally:
        session.close()


def main() -> None:
    print("RC-103 browser session smoke test")
    test_driver_launches_headless()

    if not config.TWITTER_USERNAME or not config.TWITTER_PASSWORD:
        print(
            "\nTWITTER_USERNAME/TWITTER_PASSWORD not set in .env -- skipping the X "
            "reachability check. log_in()/post_tweet()/post_reply() touch a real account "
            "and should be exercised deliberately once credentials exist, not from an "
            "automated harness."
        )
        return

    test_session_reachability_and_login_state()
    print("\nAll browser checks that don't touch a real account passed.")


if __name__ == "__main__":
    main()
