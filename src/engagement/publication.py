"""Publication lifecycle boundary. Browser confirmation is supplied by RC-104."""
import logging

from utils import browser
from utils.browser import PublicationOutcome  # noqa: F401 -- re-exported for existing callers/tests

logger = logging.getLogger(__name__)


def publish(result, memory, session, target_url=None):
    """Submit result via session (a utils.browser.BrowserSession the caller already owns and
    will close on its own lifecycle -- RC-103). This function never launches or quits a
    driver; it only calls session.ensure_ready() so authentication is (re-)verified per the
    session's own throttling, not on every publish() call from scratch."""
    publication_id = result['publication_id']
    # Persist before any external action. A process crash leaves a durable hold.
    memory.transition_publication(publication_id, 'attempted')
    submission_started = False
    try:
        session.ensure_ready()
        submission_started = True
        if target_url:
            outcome = browser.post_reply(session.driver, target_url, result['reply_text'])
        else:
            outcome = browser.post_tweet(session.driver, result['post_text'])
    except Exception as error:
        session.flag_possibly_expired()
        memory.transition_publication(
            publication_id, 'uncertain' if submission_started else 'failed',
            detail=f'{type(error).__name__}: browser operation failed')
        raise
    else:
        # Defensive fallback: browser.post_tweet()/post_reply() always return a
        # PublicationOutcome (RC-104), but a caller/test double that returns None or a
        # malformed outcome must never be read as confirmation.
        if not isinstance(outcome, PublicationOutcome) or outcome.status not in {
            'confirmed', 'failed', 'uncertain'
        } or (outcome.status == 'confirmed' and not (outcome.external_id or outcome.external_url)):
            outcome = PublicationOutcome('uncertain', detail='No publication confirmation evidence')
        memory.transition_publication(publication_id, outcome.status, detail=outcome.detail,
                                      external_id=outcome.external_id, external_url=outcome.external_url)
        logger.info('publication %s: %s', publication_id, outcome.status)
        return outcome
