# Voice Trials

Model-backed generation trials, recorded separately from deterministic tests
(`tests/manual_test_*.py`, run via `tests/run_offline.py`). A prompt-assembly test can prove a
prompt is *built* correctly; it can't prove the model's *output* is factually accurate or
voice-consistent. This file is where that separate, harder-to-automate judgment call gets
recorded, per `docs/REVIEW_CHECKLIST.md`'s Phase 8 (RC-108) evidence requirement.

A single trial run is a data point, not a verdict -- don't treat one bad or one good generation
as proof of anything about the model or the prompt design as a whole. Findings below flag
specific, reproducible failure/success shapes so they can be checked for again in later trials,
not treated as fully resolved or fully damning after one pass.

## Trial 2026-09-11: RC-108 grounding changes, `deepseek-coder-v2:16b`

**Setup:** `LLM_PROVIDER=local`, `LOCAL_LLM_BASE_URL=http://localhost:11434/v1`,
`LOCAL_LLM_MODEL=deepseek-coder-v2:16b` (already downloaded; not pulled for this trial). Real
Ollama calls, no mocks. Two runs:

1. `venv/bin/python tests/manual_test_posts.py` -- the six standard scenarios (Convergence,
   Breakthrough, Anniversary, Excavation, Quiet-with-signal, Quiet-empty-pool).
2. An ad hoc script (not committed -- same "isolated review check" status as the Baseline
   evidence table's pre-remediation reproductions) that pre-confirms one earlier post in a
   temporary database, then calls `generate_post()` 8 times with a fixed technology signal
   across seeds 0-7, to actually exercise the new callback structure with a real model.

**Scope:** this trial targets RC-108's specific changes -- Convergence grounding, the callback
structure, and the no-signal anti-fabrication path. It is not a general voice-quality
certification, and `deepseek-coder-v2:16b` is code-specialized (see `CLAUDE.md`'s Local Model
Testing Notes) -- treat findings about generic prose here as consistent with that known
limitation, not a new discovery about the prompt design itself.

### Convergence grounding (positive)

The Convergence prompt correctly received both signals (arxiv diffusion-model paper + Met
Museum Rembrandt reattribution) and the model's output engaged with the actual connection
between them ("A Rembrandt attribution model deciphers brushstroke secrets to prove
authenticity") rather than talking about only one side, or inventing an unrelated link. It did
not name the two signals as separately as the prompt's "First... Second..." framing invites --
it fused them into one narrative rather than an explicit "X connects to Y" comparison -- a style
note, not a grounding failure.

### Callback structure (positive)

Across 8 seeds against a real pre-confirmed earlier post ("A 1962 spell-checker fit in 64
kilobytes..."), seed 3 selected the callback structure and produced: *"A 1962 spell-checker in a
64KB box used sorted list & binary search; now laughed at for slow vs hash tables. But back
then, it was cutting edge..."* -- it referenced the real confirmed post's actual specifics (year,
size, technique) without inventing new ones. This is the behavior RC-108's gating was meant to
produce: a callback only fires with real content available, and when it does, the model had
real material to work from instead of fabricating what "the earlier post" said.

### No-signal fabrication (unresolved -- matches existing open item)

The empty-pool Quiet scenario produced: *"Have you noticed how medieval artisans developed
methods to match ultramarine long before digital calibration tools?"* -- a specific, invented
historical claim, despite the prompt's explicit instruction not to invent a date, name, number,
or fact when there's no signal to anchor to. RC-108 fixed which *structures* a no-signal prompt
can select (no comparison, no quiet-fact, no ungrounded callback); it does not and cannot make
the model reliably follow a "don't invent" instruction at the generation layer. This is the same
failure mode `CLAUDE.md`'s Current Status section already documents as an open item from Phase
2/4 testing -- this trial reproduces it again on a different model and confirms it is not
resolved. **`CLAUDE.md`'s open voice-quality item stays open; this trial does not justify closing
it.**

### Other observed issue (not in RC-108's scope, noted for later trials)

The Breakthrough scenario's output garbled a specific technical detail from its real signal --
the signal said the replication happened "under ambient pressure," the model's post said "under
hot air pressure" and added an invented "without heating" contrast. This is a faithfulness issue
with a *present* signal (not the no-signal fabrication case above), and out of RC-108's scope
(prompt structure/context contracts, not factual fidelity to a supplied signal) -- flagged here
for whoever next investigates model-output factual accuracy, likely alongside RC-109/RC-110 or a
dedicated follow-up.
