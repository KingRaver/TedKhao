"""Selenium WebDriver setup + X/Twitter session and posting mechanics.

The only module that drives Selenium directly -- signals/timeline_scraper.py (scraping) and
the eventual Phase 7 bot.py (posting orchestration) go through the functions here rather than
touching Chrome themselves. Session cookies persist between runs via a Chrome user-data-dir
profile (data/browser_profile/, gitignored) so a fresh login isn't needed on every run -- see
docs/SPEC.md's Auth & Permissions section.

X's DOM (the data-testid selectors below) is not a public API and can change without notice.
If scraping/login/posting starts failing, check the live site's DOM before assuming a logic
bug here. Login can also stop short of the password step if X throws in an extra
verification challenge (phone/email confirmation, captcha) -- that's not something this can
script around; running once with headless=False lets a human clear it, after which the
persisted profile keeps the session alive for subsequent headless runs.
"""
import os

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

import config

HOME_URL = "https://x.com/home"
_LOGIN_URL = "https://x.com/i/flow/login"
_PROFILE_DIR = os.path.join("data", "browser_profile")

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
