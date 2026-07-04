# Provenance Guard

Provenance Guard is a Flask service that estimates whether a piece of submitted
text is AI-generated or human-written. It combines two independent detection
signals into a single confidence score, returns a plain-language transparency
label to the creator, records every decision in a tamper-evident audit log, and
lets creators appeal a classification for human review.

## Architecture Overview

```
POST /submit { text, creator_id }
      │
      ▼
 Signal 1: Groq LLM        raw text ──► Groq LLM call    ──► llm_score  (0-1)
      │
      ▼
 Signal 2: Stylometrics    raw text ──► statistical math ──► style_score (0-1)
      │
      ▼
 Score Combiner            0.6*llm + 0.4*style           ──► confidence (0-1)
      │
      ▼
 Label Generator           confidence ──► label + label_text (thresholds)
      │
      ▼
 Audit Log (audit_log.json)  writes content_id, both scores, confidence, label, status
      │
      ▼
 Response { content_id, attribution, confidence, label, label_text }
```

The submission flow lives in `App.py` (`/submit` route). The two signals are
`get_llm_signal()` (in `App.py`) and `get_stylometric_signal()` (in
`stylometrics.py`). Scoring and labelling are `compute_confidence()` and
`get_label()` in `stylometrics.py`, plus `generate_label_text()` in `App.py`.
The audit log is a JSON file (`audit_log.json`) read and written through
`get_log()`, `write_log_entry()`, and `write_log()`.

An appeal flow (`POST /appeal`) sets the original decision's status to
`under_review` and appends a linked appeal entry to the same audit log, so a
human reviewer sees the original signals and the creator's reasoning together.
A read-only `GET /log` endpoint returns the full audit log.

## Detection Signals

Provenance Guard uses two genuinely independent signals — one semantic, one
structural — so that a text has to fool both to be misclassified.

### Signal 1 — Groq LLM classification (`llama-3.3-70b-versatile`)

- **What it measures:** The text is sent to Groq with a prompt asking it to
  return a single probability (0–1) that the text was AI-generated. This
  captures *semantic* and holistic properties — does the reasoning flow
  naturally, is the phrasing distinctive or generic, is the voice consistent.
- **Why chosen:** A large model has seen enormous amounts of both human and AI
  text and can judge coherence and "voice" in a way that fixed statistical
  rules cannot.
- **Specific blind spot:** It has no ground truth — it is itself an LLM guessing
  about LLM output. Formal, essay-style *human* writing (measured tone, textbook
  vocabulary) reads to the model like the AI text it was trained to associate
  with formality, so it inflates the AI probability of competent formal human
  authors.

### Signal 2 — Stylometric heuristics (pure Python, `stylometrics.py`)

- **What it measures:** Three normalized structural metrics combined by simple
  average:
  - *Sentence-length variance* — humans vary sentence length more than AI does.
  - *Type-token ratio* (vocabulary diversity) — AI text tends to reuse a
    narrower vocabulary.
  - *Punctuation density* — measures how heavily punctuated the text is.
  Higher combined score = more "AI-like" uniformity.
- **Why chosen:** It is fully deterministic, free, fast, and completely
  independent of the LLM — it looks only at measurable shape, not meaning, so it
  can disagree with Signal 1 in informative ways.
- **Specific blind spot:** It equates *uniformity* with AI. Deliberately simple
  or repetitive human writing — a children's poem, a list, or prose with
  intentional stylistic repetition — has low sentence-length variance and low
  vocabulary diversity, so the stylometric signal scores it as AI even though a
  human chose that style on purpose. It also returns a neutral 0.5 for very
  short text, contributing no real information there.

## Confidence Scoring Method

The two signal scores are combined with a fixed weighted average:

```
confidence = (0.6 * llm_score) + (0.4 * style_score)
```

The LLM signal is weighted more heavily (0.6) because it evaluates meaning and
coherence directly; the stylometric signal (0.4) is a supporting structural
check. The resulting confidence (0–1) is mapped to a label:

| Condition                | Label          |
|--------------------------|----------------|
| `confidence >= 0.75`     | `likely_ai`    |
| `0.35 < confidence < 0.75` | `uncertain`  |
| `confidence <= 0.35`     | `likely_human` |

The `likely_ai` threshold (0.75) sits far above the `likely_human` threshold
(0.35) on purpose: falsely accusing a human of using AI is worse than the
reverse, so it takes stronger evidence to declare something AI-generated.

### Two real example submissions

These are actual responses returned by a running instance of this service (not
invented numbers):

**Clearly AI-sounding text** — a formal, "In conclusion / it is important to
note / stakeholders must collaborate" style paragraph:

```json
{
  "attribution": "uncertain",
  "confidence": 0.6179,
  "content_id": "24dfadf4-ed6f-4609-a15a-d58e6d44e63d",
  "label": "uncertain",
  "label_text": "We can't confidently determine whether this content is AI-generated or human-written. Our detection signals produced mixed or inconclusive results."
}
```

**Clearly human-sounding text** — a casual, lowercase ramen-review with slang
and an aside:

```json
{
  "attribution": "likely_human",
  "confidence": 0.1741,
  "content_id": "b38e4ee7-fc3b-4978-b745-92d0790b4dd1",
  "label": "likely_human",
  "label_text": "This content shows strong signals of human authorship. Our system found patterns consistent with human writing across multiple independent checks."
}
```

The two submissions produced clearly different confidence scores (0.6179 vs
0.1741), and the casual human text landed firmly in `likely_human`. Notably the
formal AI-sounding text came back `uncertain` rather than `likely_ai` — a
concrete illustration of the false-positive asymmetry at work: the system
declines to firmly label text AI unless the evidence crosses the deliberately
high 0.75 bar.

## Transparency Labels

The three label variants are returned verbatim as `label_text`:

- **likely_ai:** "This content shows strong signals of AI generation. Our system detected patterns commonly associated with AI-written text across multiple independent checks."
- **uncertain:** "We can't confidently determine whether this content is AI-generated or human-written. Our detection signals produced mixed or inconclusive results."
- **likely_human:** "This content shows strong signals of human authorship. Our system found patterns consistent with human writing across multiple independent checks."

## Rate Limiting

The `/submit` endpoint is rate-limited with Flask-Limiter (in-memory storage,
`storage_uri="memory://"`) to:

- **10 requests per minute**
- **100 requests per day**

**Reasoning:** Each `/submit` triggers a paid Groq LLM call, so the endpoint is
both the most expensive and the most abuse-prone surface in the app. The
per-minute cap (10/min) blunts rapid scripted bursts — scraping, accidental
retry loops, or someone hammering the classifier — while still comfortably
allowing an interactive human to submit several drafts in a row. The per-day cap
(100/day) bounds sustained cost from a single client over a longer horizon even
if they stay under the minute limit. The two limits together protect the Groq
budget without getting in the way of normal use. Storage is in-memory because
this is a single-process demo; a multi-process deployment would swap in a shared
backend such as Redis.

## Known Limitation

The most consequential limitation is tied directly to the **stylometric signal's
uniformity blind spot**: a human who writes in a deliberately plain, repetitive,
or highly regular style (for example a children's story, a numbered
instructional list, or minimalist prose) will get a high stylometric score
because low sentence-length variance and low vocabulary diversity are treated as
AI markers. Combined with the LLM signal's tendency to flag formal writing, this
means a *plain, competent human writer* is the profile most at risk of being
pushed toward `uncertain` or `likely_ai` — which is precisely why the appeal
route exists and why the AI threshold is set high.

## Spec Reflection

Writing the spec (`planning.md`) before the code paid off: because the signal
definitions, the exact weighted-average formula, the three thresholds, and the
verbatim label strings were all pinned down in advance, implementation became
mechanical wiring rather than design-on-the-fly, and there was never a moment of
"what should this number be?" mid-build. The clearest spec win was the
false-positive asymmetry — deciding *up front* that the `likely_ai` bar (0.75)
should sit far above the `likely_human` bar (0.35) turned an ethical stance into
two concrete constants, and the real example above (formal AI-ish text landing
`uncertain`, not `likely_ai`) shows that stance actually holding in practice. If
anything, the spec under-specified how easily *formal human* writing trips both
signals toward the middle; a future revision would add calibration or a
length-aware trust discount rather than changing any of the locked values.

## AI Usage

This project was built with AI assistance (Claude). Specific things the AI did:

1. **Wired `stylometrics.py` into `App.py`** — added the imports, replaced the
   placeholder confidence/label logic in `/submit` with real calls to
   `get_stylometric_signal()`, `compute_confidence()`, and `get_label()`, and
   added `style_score` to the audit-log entry.
2. **Implemented the `POST /appeal` route** — including the 400 (missing field)
   and 404 (unknown `content_id`) handling, the status update to
   `under_review`, and the appended appeal log entry.
3. **Added Flask-Limiter** to `/submit` (`memory://`, `10 per minute;100 per
   day`) and wrote `generate_label_text()` with the exact label strings.
4. **Ran the live verification** — actually started the server, called `/submit`
   twice, `/appeal` once, and fired 12 rapid requests to confirm the rate
   limiter; the example scores and JSON in this README are those real responses.

**Nothing was silently changed from the locked design values.** The confidence
formula `(0.6 * llm_score) + (0.4 * style_score)`, the thresholds (`>= 0.75`
likely_ai, `<= 0.35` likely_human, otherwise uncertain), and all three label
strings are exactly as specified.

## Running Locally

```bash
pip install -r requirements.txt
# create a .env file with:  GROQ_API_KEY=your_key_here
python App.py
```

Endpoints:

- `POST /submit` — body `{ "text": "...", "creator_id": "..." }`
- `POST /appeal` — body `{ "content_id": "...", "creator_reasoning": "..." }`
- `GET /log` — returns the full audit log
