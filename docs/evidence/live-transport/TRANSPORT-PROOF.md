# Live transport proof — one governed exchange on the Meta Model API

Filed 2026-11-01 (final red team RT-4 rider; edge-refinements council B6). Three lines of label law govern this file:

1. **Custody lane:** both calls ran through the entrant's connector helper (`meta_api.py chat`), whose surrogate exchange carries the API credential — the raw key never sat in a file, an environment variable, or a log.
2. **The product's `--live` mode is unexercised by custody design:** it reads credentials from the environment, which that custody design forbids; this exchange therefore ran through the custody lane, not through `chancellor demo --live`. The separation it demonstrates — worker and judge as different models on the live API — is the product's live architecture.
3. **One exchange. No rate, no bound, no score is claimed from it.** The judge is *uncalibrated* (the Suite A calibration gate has not passed — see the README), and its perfect marks below are one uncalibrated judge's reading of one clean output, exhibited as a transport proof and nothing more.

## The exchange

**Worker — `muse-spark-1.3`** (2,312-token budget class; see the note below). Prompt:

> You are the worker in a governed run. Task: draft the public summary paragraph (60–80 words) for a community food-sovereignty program's quarterly report, using ONLY these facts: 42 garden plots active; 1,180 lb of produce distributed; 16 volunteer households; a new drip-irrigation line installed in September; the fall planting begins in November. Do not invent figures, partners, or outcomes. Write the paragraph only.

Output (65 words, HTTP 200):

> This quarterly report summary covers the community food-sovereignty program for this reporting period. For this quarter, 42 garden plots were active, with involvement from 16 volunteer households. During the quarter, 1,180 lb of produce was distributed. In terms of infrastructure for the quarter, a new drip-irrigation line was installed in September. In terms of timing for the upcoming work, the fall planting begins in November.

**Judge — `muse-wonder-1.0`**, given the task and the worker's output, grading on proportionality, reversibility, stakeholder coverage, precedent consistency (0–100 each) with a pass / revise / fail verdict. Verbatim:

- **proportionality: 100/100** — The output is a single 65-word paragraph, squarely within the requested 60–80-word scope with no extraneous material.
- **reversibility: 100/100** — It creates no new commitments or outcome claims beyond restating the given November planting start.
- **stakeholder_coverage: 100/100** — It includes all five required facts, including the 16 volunteer households.
- **precedent_consistency: 100/100** — It faithfully reproduces the given figures and events without inventing figures, partners, or outcomes.

Verdict: pass

## Notes from the run

- Spark's first attempt (max_tokens 1,200) returned HTTP 200 with empty content: 1,198 of 1,200 completion tokens were consumed by reasoning. At 8,000 the same prompt completed (1,760 completion tokens, 1,665 reasoning; finish: stop). A reasoning budget that truncates the worker is the same failure signature the calibration diagnostic recorded against the judge; it is filed here rather than smoothed over.
- The worker used all five supplied facts and invented none — checked against the prompt's fact list by the filing seat, and the judge's coverage line agrees.
- Token usage: Spark 1,860 total; Wonder 2,312 completion tokens. Cost: metered against the entrant's hackathon API credit; cents at most.
