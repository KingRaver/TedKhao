"""Manual test harness: run the real reply pipeline against fake posts and print the output
for human review against VOICE_GUIDE.md.

Not an automated pytest suite -- this is meant to be read by a person deciding whether
TedKhao's voice is working, before any of this touches a real timeline. Run with:

    python tests/manual_test_replies.py [--review-db PATH]
"""
from review_database import review_database

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from engagement.reply_handler import generate_reply  # noqa: E402
from llm_provider import get_provider  # noqa: E402
from persona.memory import PersonaMemory  # noqa: E402

FAKE_POSTS = [
    {
        "id": "fake-1",
        "author_handle": "@some_dev",
        "text": "AI just invented a completely new art movement, nobody talks about how huge this is",
    },
    {
        "id": "fake-2",
        "author_handle": "@curious_reader",
        "text": "is it true that the Library of Alexandria burned down in one fire?",
    },
    {
        "id": "fake-3",
        "author_handle": "@ml_engineer",
        "text": "just found out the James Webb telescope can see light from 13.6 billion years ago",
    },
    {
        "id": "fake-4",
        "author_handle": "@museum_fan",
        "text": "this restoration technique the conservators used on the fresco is absolutely masterful",
    },
    {
        "id": "fake-5",
        "author_handle": "@rando",
        "text": "they just shut down the last physical Blockbuster-style video rental chain in the country",
    },
    {
        "id": "fake-6",
        "author_handle": "@nobody_special",
        "text": "grabbing coffee, nothing interesting happening today",
    },
]


def run_review(db_path: str) -> None:
    try:
        provider = get_provider()
    except ValueError as e:
        print(f"\nCan't run live: {e}\n")
        print("Copy .env.example to .env and fill in ANTHROPIC_API_KEY, then re-run.\n")
        return

    memory = PersonaMemory(db_path=db_path)

    for post in FAKE_POSTS:
        result = generate_reply(post, provider, memory)
        print("=" * 70)
        print(f"POST ({result['post']['author_handle']}): {result['post']['text']}")
        print(f"  topic_tags: {result['analysis']['topic_tags']} | domain: {result['analysis']['domain_guess']}")
        print(f"  register:   {result['register'].value}")
        print(f"REPLY ({len(result['reply_text'])} chars):")
        print(f"  {result['reply_text']}")
        print()

    print("=" * 70)
    print(f"Recent registers used (anti-repetition check): "
          f"{[r.value for r in memory.recent_registers]}")


def main(argv=None) -> None:
    with review_database(argv) as db_path:
        run_review(db_path)


if __name__ == "__main__":
    main()
