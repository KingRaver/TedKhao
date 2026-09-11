"""X/Twitter timeline scraping -- conversation-driven signal source (docs/SPEC.md).

Implements the same fetch() -> list[Signal] shape as every other module in signals/
(src/signals/base.py) -- nothing downstream needs to know this source is Selenium-based
rather than an HTTP API call. The other sources take no arguments; this one takes an injected
`utils.browser.BrowserSession` instead of creating its own driver, since RC-103 makes the
orchestrator the sole owner of the browser -- bot.py adapts this into a zero-arg callable
(`functools.partial(timeline_scraper.fetch, session)`) before treating it like the others.
Domain classification reuses engagement.content_analyzer.analyze_post()'s domain_guess rather
than duplicating keyword matching here; posts that guess as 'general' (no clear tech/history/
arts signal) are dropped since Signal.domain is only ever one of those three elsewhere in the
codebase.

Requires an authenticated session -- see utils/browser.py's BrowserSession.ensure_ready().
Reuses the caller's driver rather than opening/closing its own, so repeated fetches across
cycles don't relaunch Chrome.
"""
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from engagement.content_analyzer import analyze_post
from signals.base import Signal, rank_novelty
from utils import browser
from utils.browser import BrowserSession

_TWEET_ARTICLE = (By.CSS_SELECTOR, 'article[data-testid="tweet"]')
_TWEET_TEXT = (By.CSS_SELECTOR, '[data-testid="tweetText"]')
_TWEET_PERMALINK = (By.CSS_SELECTOR, 'a[href*="/status/"] time')


def fetch(session: BrowserSession, max_results: int = 10) -> list[Signal]:
    """Scrape the current home timeline into Signals, newest/topmost first, using session's
    already-owned driver. Caller is responsible for session lifecycle (start()/close())."""
    session.ensure_ready()
    driver = session.driver
    driver.get(browser.HOME_URL)
    WebDriverWait(driver, 20).until(EC.presence_of_element_located(_TWEET_ARTICLE))
    articles = driver.find_elements(*_TWEET_ARTICLE)[:max_results]

    raw = []
    for article in articles:
        text_elements = article.find_elements(*_TWEET_TEXT)
        if not text_elements:
            continue
        text = text_elements[0].text.strip()
        if not text:
            continue
        permalink_elements = article.find_elements(*_TWEET_PERMALINK)
        url = ""
        if permalink_elements:
            anchor = permalink_elements[0].find_element(By.XPATH, "..")
            url = anchor.get_attribute("href") or ""
        raw.append((text, url))

    signals = []
    for i, (text, url) in enumerate(raw):
        domain = analyze_post(text)["domain_guess"]
        if domain == "general":
            continue
        signals.append(Signal(
            source="x_timeline",
            domain=domain,
            title=text[:120],
            summary=text,
            url=url,
            novelty_score=rank_novelty(i, len(raw)),
        ))
    return signals
