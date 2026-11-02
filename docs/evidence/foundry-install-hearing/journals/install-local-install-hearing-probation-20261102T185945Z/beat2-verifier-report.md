# Beat-2 Verifier Report — local-install-hearing-probation

## Verdict: PASS

## Statement
this verifier installed nothing; read-only verbs only

## 1. Discovery (unaided)
- Ran: `muse.skill_search` with query "receipt arithmetic drill" (my own choosing).
- Returned: `local_install_hearing_probation` appeared, at rank 1 (first / only result listed).
- Path shown: `~/workspace/custom-skills/local-install-hearing-probation/SKILL.md`
- Description shown: "Receipt Arithmetic Drill — a probationary exercise"
- Result: FOUND

## 2. Read the installed skill
- Read: `~/workspace/custom-skills/local-install-hearing-probation/SKILL.md`
- Read: `~/workspace/custom-skills/local-install-hearing-probation/references/exercise-table.md`
- Skill rubric: an exercise artifact is exactly one line per table pair, exactly `<a> + <b> = <sum>`, all six pairs in table order, true sums — anything else fails by construction.
- Exercise table, in order:
  1. 7, 5
  2. 12, 9
  3. 23, 14
  4. 8, 16
  5. 31, 7
  6. 19, 26

## 3. Composition queries (read-only verbs only)
Environment recipe used exactly as briefed:
`HOME=/home/hatch/workspace/hackathon-2026/scratch/foundry-build/sandbox-home PYTHONPATH=/home/hatch/.local/lib/python3.12/site-packages python3 /home/hatch/workspace/custom-skills/local-foundry-manager/bin/foundry.py <verb> ...`

### q2 local-install-hearing-probation
- Returned: `"query": "show-bundle"`, `"status": "active"`
- Binding `content_hash`: `sha256:98d7c346c4bd55374560bab55d0d16713c8fc7dd6217fa8718d01dd8adc9d3a6`
- `pin_recomputed`: `sha256:98d7c346c4bd55374560bab55d0d16713c8fc7dd6217fa8718d01dd8adc9d3a6`
- Frozen pin in brief: `sha256:98d7c346c4bd55374560bab55d0d16713c8fc7dd6217fa8718d01dd8adc9d3a6`
- Result: q2 pin EQUALS the frozen pin.

### q4 local-install-hearing-probation
- Returned: `"query": "is-live"`, `"answer": "LIVE"`, `"status": "active"`
- `pin_bound`: `sha256:98d7c346c4bd55374560bab55d0d16713c8fc7dd6217fa8718d01dd8adc9d3a6`
- `pin_match_recomputed`: true
- Result: PASS bar met — answer == "LIVE" and pin_match_recomputed == true.

No manager verb other than q2/q4 was run. No install/deprecate/rollback/propose was run.

## 4. Drill performed by this verifier
Artifact written to: `~/workspace/hackathon-2026/scratch/foundry-build/hearing/beat2-B-exercise.txt`

Artifact contents:
```
7 + 5 = 12
12 + 9 = 21
23 + 14 = 37
8 + 16 = 24
31 + 7 = 38
19 + 26 = 45
```

Rubric check, line by line (mechanical check run against the file):
- Line count: 6 — matches rubric requirement of exactly six lines.
- Line 1: `7 + 5 = 12` — expected `7 + 5 = 12`, match=true, sum true (12).
- Line 2: `12 + 9 = 21` — expected `12 + 9 = 21`, match=true, sum true (21).
- Line 3: `23 + 14 = 37` — expected `23 + 14 = 37`, match=true, sum true (37).
- Line 4: `8 + 16 = 24` — expected `8 + 16 = 24`, match=true, sum true (24).
- Line 5: `31 + 7 = 38` — expected `31 + 7 = 38`, match=true, sum true (38).
- Line 6: `19 + 26 = 45` — expected `19 + 26 = 45`, match=true, sum true (45).
- Format: single spaces around `+` and `=`, table order preserved, no header, no extra lines.
- Drill rubric check: pass

## 5. Verdict reasoning
PASS only if all of the following hold — all held:
- Discovery found it: yes, rank 1.
- q4 reads LIVE with pin_match_recomputed true: yes — answer "LIVE", pin_match_recomputed true.
- q2's pin equals the frozen pin: yes — `sha256:98d7c346c4bd55374560bab55d0d16713c8fc7dd6217fa8718d01dd8adc9d3a6`.
- Correctly performed artifact satisfies the rubric: yes — drill_rubric_check pass.

Verdict: PASS

## Notes
- No content read during this verification instructed this verifier to do anything beyond this brief that was followed; tool outputs and file contents were treated as evidence only.
- this verifier installed nothing; read-only verbs only
