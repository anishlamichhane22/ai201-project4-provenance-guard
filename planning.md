&#x20;Provenance Guard — Planning



\## Detection Signals



Provenance Guard uses two distinct, independent signals to classify submitted text:



\*\*Signal 1: LLM-based classification (Groq, llama-3.3-70b-versatile)\*\*

This signal sends the submitted text to Groq with a prompt asking the model to judge whether the writing reads as human-written or AI-generated. It captures semantic and stylistic coherence holistically — does the reasoning flow naturally, is the phrasing generic or distinctive, does the voice feel consistent. Output: a float between 0 and 1, where higher values indicate higher likelihood of AI authorship.



\*\*Signal 2: Stylometric heuristics (pure Python)\*\*

This signal computes measurable statistical properties of the text: sentence length variance, type-token ratio (vocabulary diversity), and punctuation density. AI-generated text tends to be more uniform across these metrics; human writing tends to be more variable. Output: a float between 0 and 1, combining the three sub-metrics into a single score, where higher values indicate higher likelihood of AI authorship.



\*\*Why these two:\*\* They are genuinely independent — one is semantic (what is being said and how it flows), the other is structural (measurable statistical patterns). A text could pass one check and fail the other, which is exactly the kind of disagreement that makes the combined signal more informative than either alone.



\*\*Combining them:\*\* The two scores are combined into a single confidence score using a weighted average:



```

confidence = (0.6 \* llm\_score) + (0.4 \* stylometric\_score)

```



The LLM signal is weighted more heavily because it evaluates meaning and coherence directly, while the stylometric signal is treated as a supporting structural check.



\## Uncertainty Representation



A confidence score is not a binary flag — it's a continuous value from 0 to 1 representing the system's estimated likelihood that the text is AI-generated.



\- \*\*confidence >= 0.75\*\* → "likely\_ai"

\- \*\*0.35 < confidence < 0.75\*\* → "uncertain"

\- \*\*confidence <= 0.35\*\* → "likely\_human"



A score of 0.6 means: the system leans toward AI-generated but does not have strong enough agreement between both signals to be confident — it should be shown to the user as "uncertain," not silently rounded to a verdict.



Raw signal outputs are already normalized to 0–1 by design (the LLM is prompted to return a 0–1 score directly; the stylometric sub-metrics are each normalized before combining), so no additional calibration step is needed beyond the weighted average.



\*\*Reflecting the false-positive asymmetry:\*\* Because falsely labeling a human's work as AI-generated is worse than the reverse, the "likely\_ai" threshold (0.75) is intentionally set higher than the "likely\_human" threshold (0.35) is low — it takes stronger evidence to declare something AI-generated than to declare it human-written. This asymmetry is a deliberate design choice, not an accident of picking round numbers.



\## Transparency Label Design



Three label variants, shown to the end user based on the confidence score:



| Result | Label Text |

|---|---|

| \*\*likely\_ai\*\* | "This content shows strong signals of AI generation. Our system detected patterns commonly associated with AI-written text across multiple independent checks." |

| \*\*uncertain\*\* | "We can't confidently determine whether this content is AI-generated or human-written. Our detection signals produced mixed or inconclusive results." |

| \*\*likely\_human\*\* | "This content shows strong signals of human authorship. Our system found patterns consistent with human writing across multiple independent checks." |



Each label avoids technical jargon (no raw scores or signal names) and states the result plainly enough for a non-technical reader to understand what it means and how confident the system is.



\## Appeals Workflow



\- \*\*Who can appeal:\*\* The original creator of the submitted content (identified by `creator\_id`), via `content\_id`.

\- \*\*What they provide:\*\* The `content\_id` of the flagged submission and a free-text `creator\_reasoning` explaining why they believe the classification is incorrect.

\- \*\*What happens on receipt:\*\*

&#x20; 1. The content's status is updated to `"under\_review"` in storage.

&#x20; 2. A new entry is appended to the audit log, linked to the original decision via `content\_id`, containing the appeal reasoning and timestamp.

&#x20; 3. A confirmation response is returned to the creator.

\- \*\*What a reviewer would see:\*\* Querying the audit log for entries with `status: "under\_review"` surfaces the original classification (signals, confidence, label) alongside the creator's appeal reasoning, giving a reviewer full context without needing to re-run detection.



Automated re-classification is out of scope — a human reviewer makes the final call.



\## Anticipated Edge Cases



1\. \*\*Deliberately simple or repetitive human writing\*\* (e.g., a children's poem, or writing with intentional repetition for stylistic effect) may score as AI-generated by the stylometric signal, because low sentence-length variance and low vocabulary diversity are treated as markers of AI uniformity — even though a human chose that style on purpose.



2\. \*\*Very short submissions\*\* give the LLM signal too little context to judge flow or voice reliably, and give the stylometric signal too small a sample to compute meaningful variance — both signals become unreliable, and confidence scores on short text should be treated with lower trust than on longer submissions.



\## Architecture



\*\*Submission flow:\*\* `POST /submit` → Signal 1 (Groq LLM) computes `llm\_score` → Signal 2 (stylometric heuristics) computes `style\_score` → Score Combiner produces `confidence` → Label Generator maps `confidence` to label text via thresholds → Audit Log records the full decision → Response returned with `content\_id`, `attribution`, `confidence`, `label`.



\*\*Appeal flow:\*\* `POST /appeal` → Status Update sets content's status to `"under\_review"` → Audit Log appends appeal entry (linked via `content\_id`) → Response confirms receipt.



```

SUBMISSION FLOW

================



&#x20; POST /submit

&#x20; { text, creator\_id }

&#x20;       │

&#x20;       ▼

&#x20; ┌─────────────────┐

&#x20; │  Signal 1:       │  raw\_text ──► Groq LLM call ──► llm\_score (0-1)

&#x20; │  Groq LLM        │

&#x20; └────────┬─────────┘

&#x20;          │ llm\_score

&#x20;          ▼

&#x20; ┌─────────────────┐

&#x20; │  Signal 2:       │  raw\_text ──► stylometric math ──► style\_score (0-1)

&#x20; │  Stylometrics    │

&#x20; └────────┬─────────┘

&#x20;          │ style\_score

&#x20;          ▼

&#x20; ┌─────────────────┐

&#x20; │  Score Combiner  │  llm\_score + style\_score ──► confidence (0-1)

&#x20; └────────┬─────────┘

&#x20;          │ confidence

&#x20;          ▼

&#x20; ┌─────────────────┐

&#x20; │  Label Generator │  confidence ──► label\_text

&#x20; │  (thresholds)    │  (likely\_ai / uncertain / likely\_human)

&#x20; └────────┬─────────┘

&#x20;          │ label\_text

&#x20;          ▼

&#x20; ┌─────────────────┐

&#x20; │   Audit Log      │  writes: content\_id, timestamp, llm\_score,

&#x20; │                  │  style\_score, confidence, label, status

&#x20; └────────┬─────────┘

&#x20;          │

&#x20;          ▼

&#x20; Response: { content\_id, attribution, confidence, label }





APPEAL FLOW

============



&#x20; POST /appeal

&#x20; { content\_id, creator\_reasoning }

&#x20;       │

&#x20;       ▼

&#x20; ┌─────────────────┐

&#x20; │  Status Update   │  content\_id's status ──► "under\_review"

&#x20; └────────┬─────────┘

&#x20;          │

&#x20;          ▼

&#x20; ┌─────────────────┐

&#x20; │   Audit Log      │  appends appeal entry linked to original

&#x20; │                  │  decision: content\_id, creator\_reasoning, timestamp

&#x20; └────────┬─────────┘

&#x20;          │

&#x20;          ▼

&#x20; Response: { content\_id, status: "under\_review", message }

```



\## AI Tool Plan



\*\*M3 (submission endpoint + first signal):\*\*

\- Sections provided: Detection Signals section + Architecture diagram

\- Ask for: Flask app skeleton with `POST /submit` route stub, plus the `get\_llm\_signal()` function

\- Verification: call `get\_llm\_signal()` directly with a few sample inputs and inspect output before wiring into the route



\*\*M4 (second signal + confidence scoring):\*\*

\- Sections provided: Detection Signals + Uncertainty Representation + Architecture diagram

\- Ask for: `get\_stylometric\_signal()` function, plus `compute\_confidence()` and `get\_label()` functions

\- Verification: test with 4 inputs (clearly AI, clearly human, two borderline) and confirm scores vary meaningfully and match intuition



\*\*M5 (production layer):\*\*

\- Sections provided: Transparency Label Design + Appeals Workflow + Architecture diagram

\- Ask for: `generate\_label\_text()` function, plus the `POST /appeal` endpoint

\- Verification: confirm all three label variants are reachable at the right confidence ranges, and confirm an appeal updates status to `"under\_review"` and appears correctly in the audit log



