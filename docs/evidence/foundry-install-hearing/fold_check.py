#!/usr/bin/env python3
"""Independent probation fold for claim F5 — hearing-lane code,
importing NO product code (stdlib json/sys only). Re-implements
the fold directly from SPEC-FOUNDRY-CHANCELLOR §2's text:

- a window opens on capability_probation_opened (window size from
  the entry, default 10 receipted uses);
- inside an open window, a capability_use entry counts one use;
  a graded FAIL, an out_of_permission use, and a pin_drift use are
  strikes; a Decision inside the window carrying the capability_id
  counts one use (a refused one also a strike);
- capability_probation_closed ends the window as standing;
- capability_suspension ends it as suspended.
Prints one JSON object: {capability_id: {standing, uses, strikes}}.
"""
import json
import sys


def fold(entries):
    state = {}
    for e in entries:
        et = e.get("entry_type")
        cid = e.get("capability_id")
        if et == "capability_probation_opened" and cid:
            state[cid] = {"standing": "probation", "uses": 0,
                          "strikes": 0,
                          "window": int(e.get("window_uses") or 10)}
            continue
        cur = state.get(cid) if cid else None
        if cur is None or cur["standing"] != "probation":
            if et == "capability_suspension" and cid in state:
                state[cid]["standing"] = "suspended"
            continue
        if et == "capability_use":
            cur["uses"] += 1
            if (e.get("grade") == "fail" or e.get("out_of_permission")
                    or e.get("pin_drift")):
                cur["strikes"] += 1
        elif et == "decision":
            detail = e.get("detail")
            if isinstance(detail, str):
                try:
                    detail = json.loads(detail)
                except ValueError:
                    detail = {}
            if isinstance(detail, dict) and detail.get("capability_id") == cid:
                cur["uses"] += 1
                if e.get("refusal_state"):
                    cur["strikes"] += 1
        elif et == "capability_probation_closed":
            cur["standing"] = "standing"
        elif et == "capability_suspension":
            cur["standing"] = "suspended"
    return {cid: {"standing": s["standing"], "uses": s["uses"],
                  "strikes": s["strikes"]} for cid, s in state.items()}


if __name__ == "__main__":
    entries = [json.loads(ln) for ln in open(sys.argv[1]) if ln.strip()]
    print(json.dumps(fold(entries), indent=2, sort_keys=True))
