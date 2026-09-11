"""RC-104 fake-driver checks for utils.browser's post-submission confirmation: a button click
alone must never produce a confirmed outcome. Covers success (toast with a status permalink),
rejection (an error/confirmation dialog), a genuine timeout with no evidence either way, and a
crash after the click -- each via controlled DOM fixtures on a Mock driver, never real Chrome.

Real X selectors and confirmation behavior remain unverified until RC-110's explicitly
authorized live check -- see utils/browser.py's module docstring.

Included in `venv/bin/python tests/run_offline.py` (RC-101 isolation). Uses plain asserts. Run
standalone with:

    python tests/manual_test_browser_confirmation.py
"""
from pathlib import Path
import sys
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from selenium.common.exceptions import WebDriverException  # noqa: E402

from utils import browser  # noqa: E402
from utils.browser import PublicationOutcome  # noqa: E402


def make_driver(toast_status_link=None, error_dialog_text=None, bare_toast_text=None):
    """A Mock driver whose find_elements() answers only the locators
    _await_submission_outcome() actually queries; find_element() (singular, used by the
    compose/click flow) keeps Mock's default auto-clickable behavior."""
    driver = Mock()
    # find_element() (singular) backs the compose-textarea/post-button click flow via
    # EC.element_to_be_clickable(), which requires is_displayed()/is_enabled() to actually
    # return True (a bare Mock is truthy but fails EC's `== True` check).
    driver.find_element.return_value.is_displayed.return_value = True
    driver.find_element.return_value.is_enabled.return_value = True

    def find_elements(by, selector):
        locator = (by, selector)
        if locator == browser._TOAST_STATUS_LINK and toast_status_link:
            link = Mock()
            link.get_attribute.return_value = toast_status_link
            return [link]
        if locator == browser._ERROR_DIALOG and error_dialog_text is not None:
            dialog = Mock()
            dialog.text = error_dialog_text
            return [dialog]
        if locator == browser._TOAST and (toast_status_link or bare_toast_text is not None):
            toast = Mock()
            toast.text = bare_toast_text or ''
            return [toast]
        return []

    driver.find_elements.side_effect = find_elements
    return driver


def test_post_tweet_confirmed_captures_external_id():
    driver = make_driver(toast_status_link='https://x.com/tedkhao/status/1234567890')
    outcome = browser.post_tweet(driver, 'a fake post')
    assert outcome == PublicationOutcome(
        'confirmed', external_id='1234567890', external_url='https://x.com/tedkhao/status/1234567890')
    assert driver.quit.call_count == 0, 'confirmation must not touch the shared driver''s lifecycle'
    print('  post_tweet() with a toast status permalink confirms and captures the external id: PASS')


def test_post_reply_rejected_is_distinguished_from_timeout():
    driver = make_driver(error_dialog_text='This post could not be sent. Try again.')
    outcome = browser.post_reply(driver, 'https://x.com/someone/status/999', 'a fake reply')
    assert outcome.status == 'failed'
    assert outcome.detail == 'This post could not be sent. Try again.'
    assert outcome.external_id is None and outcome.external_url is None
    print('  post_reply() with an error dialog is confirmed rejection, not a timeout: PASS')


def test_bare_toast_without_permalink_is_uncertain_not_confirmed():
    driver = make_driver(bare_toast_text='Something happened')
    outcome = browser.post_tweet(driver, 'a fake post')
    assert outcome.status == 'uncertain', 'a toast alone is not proof of a successful submission'
    print('  a toast with no status permalink resolves to uncertain, never confirmed: PASS')


def test_timeout_with_no_evidence_is_uncertain():
    driver = make_driver()
    outcome = browser._await_submission_outcome(driver, timeout=0.1)
    assert outcome.status == 'uncertain'
    assert 'No confirmation or rejection observed' in outcome.detail
    assert driver.quit.call_count == 0
    print('  a bounded wait with no confirmation or rejection evidence times out to uncertain, '
          'not failed: PASS')


def test_crash_after_click_propagates_instead_of_reporting_an_outcome():
    driver = make_driver()
    driver.find_element.side_effect = WebDriverException('renderer crashed')
    try:
        browser.post_tweet(driver, 'a fake post')
        raise AssertionError('expected the crash to propagate')
    except WebDriverException:
        pass
    assert driver.quit.call_count == 0, ('a crash after submission is the caller''s (publish()) '
                                          'to classify as uncertain -- browser.py must not quit '
                                          'or otherwise touch the shared driver''s lifecycle')
    print('  a crash after clicking propagates rather than being reported as any outcome, '
          'leaving the shared driver untouched: PASS')


def main():
    print('RC-104 submission confirmation smoke test (fake driver, no real Chrome)')
    test_post_tweet_confirmed_captures_external_id()
    test_post_reply_rejected_is_distinguished_from_timeout()
    test_bare_toast_without_permalink_is_uncertain_not_confirmed()
    test_timeout_with_no_evidence_is_uncertain()
    test_crash_after_click_propagates_instead_of_reporting_an_outcome()
    print('\nAll submission confirmation checks passed.')


if __name__ == '__main__':
    main()
