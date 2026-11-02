# Supervision cadence: match `--cadence` to the agent

`chancellor supervise` decides that a living agent is **stalled** when
its newest signed checkpoint is older than the configured stale
threshold:

```text
stale threshold = cadence × missed
```

The CLI exposes those settings as `--cadence SECONDS` and
`--missed N`; the corresponding `chancellor.supervise.SupervisorConfig`
fields are `cadence_s` and `missed`. The defaults are a 60-second
cadence and 3 missed intervals, for a 180-second stale threshold.

**Cadence means the interval between the agent's signed audit
checkpoints** — the writes to `<agent-log>.checkpoints.jsonl`. It does
not mean the agent's task, segment, token, or polling interval, and it
is not the freshness of any separate progress or state file the agent
may maintain.

## Symptom

A healthy agent can repeatedly draw `stall_anomaly` receipts while:

- its process remains alive;
- its work continues to advance;
- its signed checkpoints continue to appear; and
- its audit chain continues to verify.

The supervisor still does the safe thing: it receipts the anomaly and
does **not** start a second copy. But repeated stall receipts against
an agent whose signed checkpoints are arriving on a slower rhythm are
the signature of a cadence mismatch, not by themselves proof of a hang.

A related start-up symptom is a stall receipt whose
`agent_log_size` is null before the first signed checkpoint exists:
there is not yet a checkpoint whose age can be measured, so the watch
measures the wait from launch.

## Cause

If the agent signs a checkpoint every 505 seconds but the supervisor
is configured with the default 60-second cadence and 3 missed
intervals, the newest checkpoint crosses the 180-second stale
threshold roughly 180 seconds after each write and stays "stale" for
the remaining 325 seconds of the cycle. The supervisor therefore
receipts a stall in most of every checkpoint cycle even though the
agent is healthy and on pace.

The mismatch can also appear immediately after a resume: a relaunched
agent inherits the previous lifetime's newest checkpoint, which may
already be older than the threshold.

## Remedy

Set the cadence to the agent's real signed-checkpoint interval. For
an agent that signs about every 505 seconds:

```bash
chancellor supervise --cadence 505 --missed 3 -- <agent command...>
```

That configuration's stale threshold is 1,515 seconds (505 × 3).
Programmatically, the same setting is:

```python
SupervisorConfig(
    agent_command=[...],
    cadence_s=505,
    missed=3,
)
```

Measure the interval from consecutive signed checkpoints, not from
the agent's work rate. If the interval varies, configure for the
agent's normal checkpoint rhythm and investigate any separate,
genuine stall evidence on its own terms. A cadence advisory does not
prove an agent healthy: a process that has actually stopped signing
checkpoints still crosses the threshold and is still never treated as
dead merely for being stale.

## The supervisor's cadence advisory

The supervisor now names this likely mismatch when the evidence first
supports it. During one `Supervisor.run()` watch, it emits at most
one `cadence_advisory` receipt in its supervision log and one printed
`CADENCE ADVISORY` status line when either case is observed:

1. two consecutive signed checkpoints are farther apart than the
   configured stale threshold; or
2. a watch that began with no signed checkpoint reaches the stale
   threshold still without one (the null-size start-up case).

The receipt and line name the observed figure, the configured cadence
and missed count, the resulting stale threshold, and the remedy above.
The advisory latch is per supervisor run: an agent relaunch inside
that run does not reset it or produce a second advisory. A later
supervisor run is a new watch and may advise again if the mismatch is
still present.

The advisory is diagnostic only. It never gates or blocks a resume,
never escalates, never changes `discriminate()` or any default, and
does not alter the shape of any existing receipt.

## Field case: RUN-9, 2026-11-02

RUN-9 fielded the soak instrument under the shipped defaults —
60-second cadence × 3 missed = a 180-second stale threshold. The
instrument's signed audit checkpoints were measured from its own
checkpoint sidecar at a **505-second interval** (for example,
`log_size` 9 followed by `log_size` 17, 505 seconds later), while its
segments advanced on pace and drift remained zero. Its first signed
checkpoint took about 540 seconds to appear, producing the null-size
start-up receipts as well.

That field case is labeled for what it was: a **staging-measured
cadence mismatch**, not a supervisor defect. The wiring used the
product's own checkpoint path correctly, the detector behaved as
designed, and no adverse action followed any stall receipt. The
remedy for that staging would have been to match `--cadence` to the
instrument's ~505-second signed-checkpoint interval.
