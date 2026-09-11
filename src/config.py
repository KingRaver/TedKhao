"""Configuration and environment loading for TedKhao."""
import os
from dotenv import load_dotenv

load_dotenv()

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")

DATABASE_PATH = os.getenv("DATABASE_PATH", os.path.join("data", "tedkhao.db"))

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")

LOCAL_LLM_BASE_URL = os.getenv("LOCAL_LLM_BASE_URL", "http://localhost:11434/v1")
LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL", "llama3.1")

TWITTER_USERNAME = os.getenv("TWITTER_USERNAME")
TWITTER_PASSWORD = os.getenv("TWITTER_PASSWORD")

REPLY_MAX_CHARS = 275
# Soft target given to the model -- deliberately below the hard limit. Models (especially
# smaller/local ones) generate close to whatever ceiling they're given and frequently overshoot
# it, so asking for a target well under the real limit leaves margin for that overshoot.
REPLY_TARGET_CHARS = 220
REPLY_SHORTEN_ATTEMPTS = 2
RECENT_REGISTER_MEMORY = 3

# Same X/Twitter platform limit as replies, so same margin-below-the-ceiling reasoning applies.
POST_MAX_CHARS = 275
POST_TARGET_CHARS = 220
POST_SHORTEN_ATTEMPTS = 2

# bot.py orchestration cadence/gating. Default interval targets the upper end of docs/SPEC.md's
# "3-6 original posts a day" user story (6 cycles/day @ one post per cycle); reply-candidate
# discovery piggybacks on the same cycle rather than running on its own schedule, since SPEC.md
# doesn't specify a separate reply cadence and one combined interval keeps bot.py simple.
CYCLE_INTERVAL_MINUTES = int(os.getenv("CYCLE_INTERVAL_MINUTES", "240"))
REPLY_MAX_PER_CYCLE = int(os.getenv("REPLY_MAX_PER_CYCLE", "3"))

# Actual posting to X is public and effectively irreversible (see docs/SCAFFOLDING.md Phase 6),
# so it defaults off -- bot.py only generates and persists unless explicitly told to go live via
# --live, and even then bot.py refuses if TWITTER_USERNAME/TWITTER_PASSWORD aren't configured.
LIVE_POSTING_ENABLED = os.getenv("LIVE_POSTING_ENABLED", "false").strip().lower() == "true"
