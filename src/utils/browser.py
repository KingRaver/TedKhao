"""Selenium WebDriver setup + X/Twitter session and posting mechanics.

The only module that drives Selenium directly -- signals/timeline_scraper.py (scraping) and
bot.py (posting orchestration) go through the functions here rather than touching Chrome
themselves. Session cookies persist between runs via a Chrome user-data-dir profile
(data/browser_profile/, gitignored) so a fresh login isn't needed on every run -- see
docs/SPEC.md's Auth & Permissions section.

RC-103: `BrowserSession` is the ownership boundary -- one driver, launched once by the
orchestrator (bot.py) and reused across every timeline fetch, post, and reply for the life of
the process, rather than each operation launching and quitting its own. Timer-loop cycles in
the resident loop (`python bot.py`, no `--once`) share the same session across cycles; `--once`
starts one, uses it for that single cycle, and closes it on exit -- see bot.py's module
docstring. get_driver()/log_in()/is_logged_in()/post_tweet()/post_reply() below remain the
low-level primitives BrowserSession composes; call them directly only from a manual harness
(tests/manual_test_browser.py) or resume_manual_login(), never from per-action code paths.

X's DOM (the data-testid selectors below) is not a public API and can change without notice.
If scraping/login/posting starts failing, check the live site's DOM before assuming a logic
bug here. Login can also stop short of the password step if X throws in an extra
verification challenge (phone/email confirmation, captcha) -- that's not something this can
script around; resume_manual_login() opens a visible browser for a human to clear it, after
which the persisted profile keeps the session alive for subsequent headless runs.
"""
import logging
import os

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

import config

try:
    import fcntl
except ImportError:  # pragma: no cover -- POSIX-only; project targets macOS (CLAUDE.md).
    fcntl = None

logger = logging.getLogger("tedkhao.browser")

HOME_URL = "https://x.com/home"
_LOGIN_URL = "https://x.com/i/flow/login"
_PROFILE_DIR = os.path.join("data", "browser_profile")
_LOCK_PATH = os.path.join(_PROFILE_DIR, ".profile_lock")

_USERNAME_INPUT = (By.CSS_SELECTOR, 'input[autocomplete="username"]')
_PASSWORD_INPUT = (By.CSS_SELECTOR, 'input[name="password"]')
_LOGIN_BUTTON = (By.CSS_SELECTOR, '[data-testid="LoginForm_Login_Button"]')
_SIDENAV_ACCOUNT = (By.CSS_SELECTOR, '[data-testid="SideNav_AccountSwitcher_Button"]')
_COMPOSE_TEXTAREA = (By.CSS_SELECTOR, '[data-testid="tweetTextarea_0"]')
_POST_BUTTON = (By.CSS_SELECTOR, '[data-testid="tweetButtonInline"]')


def get_driver(headless: bool = True) -> webdriver.Chrome:
    """Launch a Chrome WebDriver with a persistent profile so an X session survives between
    runs. Caller owns the returned driver's lifecycle -- quit() it when done."""
    os.makedirs(_PROFILE_DIR, exist_ok=True)

    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument(f"--user-data-dir={os.path.abspath(_PROFILE_DIR)}")
    options.add_argument("--window-size=1280,1600")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    return webdriver.Chrome(options=options)


def is_logged_in(driver: webdriver.Chrome) -> bool:
    """Best-effort check against the persisted profile's current session."""
    driver.get(HOME_URL)
    try:
        WebDriverWait(driver, 10).until(
            lambda d: d.find_elements(*_SIDENAV_ACCOUNT) or d.find_elements(*_USERNAME_INPUT)
        )
    except TimeoutException:
        return False
    return bool(driver.find_elements(*_SIDENAV_ACCOUNT))


def log_in(driver: webdriver.Chrome) -> None:
    """Runs the X login flow using config.TWITTER_USERNAME/TWITTER_PASSWORD. Does not check
    whether a session already exists first -- see ensure_logged_in() for that."""
    if not config.TWITTER_USERNAME or not config.TWITTER_PASSWORD:
        raise ValueError(
            "TWITTER_USERNAME/TWITTER_PASSWORD are not set. Add them to .env (copy "
            ".env.example first)."
        )

    driver.get(_LOGIN_URL)
    username_input = WebDriverWait(driver, 15).until(
        EC.presence_of_element_located(_USERNAME_INPUT)
    )
    username_input.send_keys(config.TWITTER_USERNAME)
    username_input.send_keys(Keys.RETURN)

    try:
        password_input = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located(_PASSWORD_INPUT)
        )
    except TimeoutException as e:
        raise TimeoutException(
            "Password field never appeared after entering the username -- X may be asking "
            "for extra verification (phone/email/captcha). Run with headless=False once to "
            "clear it by hand; the persisted profile will keep the session for later "
            "headless runs."
        ) from e
    password_input.send_keys(config.TWITTER_PASSWORD)
    password_input.send_keys(Keys.RETURN)

    WebDriverWait(driver, 20).until(
        EC.presence_of_element_located(_SIDENAV_ACCOUNT)
    )


def ensure_logged_in(driver: webdriver.Chrome) -> None:
    """Logs in only if the persisted profile doesn't already carry a valid session."""
    if not is_logged_in(driver):
        log_in(driver)


def post_tweet(driver: webdriver.Chrome, text: str) -> None:
    """Composes and publishes a new top-level post from the home timeline's compose box.
    Caller is responsible for calling ensure_logged_in() first and for enforcing length
    limits (config.POST_MAX_CHARS) before calling this -- it does not re-check either."""
    driver.get(HOME_URL)
    textarea = WebDriverWait(driver, 15).until(
        EC.element_to_be_clickable(_COMPOSE_TEXTAREA)
    )
    textarea.click()
    textarea.send_keys(text)

    post_button = WebDriverWait(driver, 15).until(
        EC.element_to_be_clickable(_POST_BUTTON)
    )
    post_button.click()


def post_reply(driver: webdriver.Chrome, target_post_url: str, text: str) -> None:
    """Replies to the post at target_post_url. Same caller responsibilities as post_tweet()."""
    driver.get(target_post_url)
    textarea = WebDriverWait(driver, 15).until(
        EC.element_to_be_clickable(_COMPOSE_TEXTAREA)
    )
    textarea.click()
    textarea.send_keys(text)

    post_button = WebDriverWait(driver, 15).until(
        EC.element_to_be_clickable(_POST_BUTTON)
    )
    post_button.click()


class SessionPaused(Exception):
    """Raised when an X action needs a human -- no valid session in a headless run, which is
    the same signal X gives for an expired login, a verification challenge, a rate limit, or
    an account warning; this module cannot tell those apart from the DOM alone. Callers must
    not respond by looping log_in() automatically -- pause X actions and let an operator run
    resume_manual_login() (headless=False) to clear it, then resume."""


def _acquire_profile_lock():
    """Prevent a second process from launching Chrome against the same user-data-dir at the
    same time -- Chrome corrupts/refuses a profile that's already open elsewhere, and two
    processes silently racing the same X session is worse than a clear early failure."""
    if fcntl is None:
        return None
    os.makedirs(_PROFILE_DIR, exist_ok=True)
    handle = open(_LOCK_PATH, "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as e:
        handle.close()
        raise RuntimeError(
            f"Browser profile at {_PROFILE_DIR} is already in use by another process -- only "
            "one process may hold the persistent profile at a time. Stop the other process "
            "(or its BrowserSession) before starting a new one."
        ) from e
    return handle


def _release_profile_lock(handle) -> None:
    if handle is None:
        return
    try:
        fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        handle.close()


class BrowserSession:
    """Owns one Chrome WebDriver across an orchestrator's lifetime (RC-103).

    Construct one per process, call ensure_ready() before each browser-dependent action, pass
    session.driver into post_tweet()/post_reply()/timeline scraping, and close() once on
    deliberate shutdown. Do not call browser.get_driver()/driver.quit() directly once a
    BrowserSession owns the profile -- launch and teardown belong here so a resident loop's
    timer cycles share one authenticated browser instead of relaunching Chrome every action.
    """

    def __init__(self, headless: bool = True):
        self.headless = headless
        self.driver: webdriver.Chrome | None = None
        self._lock_handle = None
        self._auth_verified = False

    def start(self) -> None:
        """Launch the driver if it isn't already running. Idempotent -- safe to call from
        ensure_ready() every cycle without relaunching an already-open browser."""
        if self.driver is not None:
            return
        self._lock_handle = _acquire_profile_lock()
        try:
            self.driver = get_driver(headless=self.headless)
        except Exception:
            _release_profile_lock(self._lock_handle)
            self._lock_handle = None
            raise
        self._auth_verified = False

    def flag_possibly_expired(self) -> None:
        """Mark the session for re-verification on the next ensure_ready() call, instead of
        navigating to the home page and checking auth before every single action. Call this
        after an action fails in a way that could mean the session dropped (not for ordinary
        timeouts/selector misses, which don't imply lost auth)."""
        self._auth_verified = False

    def ensure_ready(self) -> None:
        """Call before every browser-dependent action. Launches the driver on first use and
        re-checks authentication only at startup or after flag_possibly_expired() -- never
        unconditionally -- per RC-103's "avoid repeating login and home-page navigation before
        every action" requirement."""
        if self.driver is None:
            self.start()
        if not self._auth_verified:
            self._check_auth()
            self._auth_verified = True

    def _check_auth(self) -> None:
        if is_logged_in(self.driver):
            return
        if self.headless:
            raise SessionPaused(
                "No authenticated X session in this headless BrowserSession. Run "
                "resume_manual_login() with a visible browser to clear a login/verification "
                "challenge, rate limit, or account warning by hand, then resume -- this will "
                "not retry login automatically."
            )
        log_in(self.driver)

    def replace_after_failure(self, reason: str = "") -> None:
        """Close and relaunch the driver -- reserved for a diagnosed browser-process failure
        (a crashed/invalid WebDriver session), never a per-action reset. The caller decides
        what counts as diagnosed and how many times to retry within one cycle."""
        logger.warning("replacing crashed browser session: %s", reason or "unspecified reason")
        self.close()
        self.start()

    def close(self) -> None:
        """Quit the driver once and release the profile lock. Safe to call more than once."""
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
        _release_profile_lock(self._lock_handle)
        self._lock_handle = None

    def __enter__(self) -> "BrowserSession":
        self.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


def resume_manual_login(headless_session: "BrowserSession | None" = None) -> None:
    """Visible-browser manual-authentication path (RC-103). Close any running headless
    BrowserSession first -- the profile lock only allows one owner -- then run this
    interactively:

        venv/bin/python -c "from utils.browser import resume_manual_login as r; r()"

    Opens a non-headless Chrome window against the same persisted profile, waits for a human
    to clear whatever X is asking for (login, verification challenge, rate-limit notice,
    account warning), and verifies session health before returning -- the resident loop's next
    ensure_ready() picks up the now-valid session rather than re-attempting login itself.
    """
    if headless_session is not None and headless_session.driver is not None:
        raise RuntimeError(
            "Close the running BrowserSession before resume_manual_login() -- the profile "
            "lock only allows one process to hold data/browser_profile/ at a time."
        )
    manual = BrowserSession(headless=False)
    manual.start()
    try:
        manual.driver.get(HOME_URL)
        print("Complete login/verification in the opened Chrome window, then return here.")
        WebDriverWait(manual.driver, 600).until(
            lambda d: d.find_elements(*_SIDENAV_ACCOUNT)
        )
        if not is_logged_in(manual.driver):
            raise SessionPaused("Manual login did not reach an authenticated session.")
        print("Session verified -- the persisted profile is ready for the resident loop.")
    finally:
        manual.close()
