#!/usr/bin/env python3
"""FM-3 procedural score for the Sealing Desk pull-apart film — v2.

Pure Python stdlib. Reads timeline.json (the same file the composition
builder reads — one timeline, both crafts) and synthesizes the score from
the film's own event list: one tick per authored explode step (pitched by
group), eight jewel chimes, the great key's clunk, the tamper crack, the
break stamps, the reset mirrored home, the seal strike.

v2 architecture: bed and cues are synthesized as separate stems, then
balanced by measurement — BS.1770-4 (K-weighting, gated integrated) is
implemented in-engine; the solver picks stem gains hitting -14.0 LUFS
with true peak (4x interp estimate) <= -2.3 dBFS, leaving the encode
read-back as the measure of record. Deterministic: seeded noise.
"""
import json, math, random, struct, wave
from array import array
from pathlib import Path

HERE = Path(__file__).resolve().parent
TL = json.loads((HERE / "timeline.json").read_text())
SR = 48000
DUR = TL["total_duration"]
N = int(DUR * SR)
rng = random.Random(20261104)

def zeros(): return array("f", bytes(4 * N))
BED = (zeros(), zeros())
CUE = (zeros(), zeros())

def pan_gains(pan):
    a = pan * math.pi / 4 + math.pi / 4
    return math.cos(a), math.sin(a)

def add_sine(buf, t0, dur, f0, f1, peak, tau=None, pan=0.0):
    i0 = int(t0 * SR); n = int(dur * SR)
    gl, gr = pan_gains(pan)
    ph = 0.0
    for j in range(n):
        i = i0 + j
        if i >= N: break
        x = j / SR
        f = f0 + (f1 - f0) * (x / dur if dur else 0)
        ph += 2 * math.pi * f / SR
        env = math.exp(-x / tau) if tau else (0.5 - 0.5 * math.cos(2 * math.pi * x / dur))
        v = peak * env * math.sin(ph)
        buf[0][i] += v * gl; buf[1][i] += v * gr

def add_noise(buf, t0, dur, peak, lp=0.2, hp=False, tau=None, pan=0.0, seed=1):
    r = random.Random(seed)
    i0 = int(t0 * SR); n = int(dur * SR)
    gl, gr = pan_gains(pan)
    y = 0.0; prev = 0.0
    for j in range(n):
        i = i0 + j
        if i >= N: break
        x = j / SR
        w = r.uniform(-1, 1)
        y += lp * (w - y)
        # lp path: one-pole output is small -> scale up; hp path: difference
        # of near-raw noise is already full-scale -> scale down
        v = (y - prev) * 0.45 if hp else y * 2.4
        prev = y
        env = math.exp(-x / tau) if tau else (0.5 - 0.5 * math.cos(2 * math.pi * x / dur))
        s = peak * env * v
        buf[0][i] += s * gl; buf[1][i] += s * gr

def tick(buf, t, pitch, peak=0.20, pan=0.0):
    add_sine(buf, t, 0.055, pitch, pitch * 0.82, peak, tau=0.016, pan=pan)
    add_noise(buf, t, 0.012, peak * 0.35, lp=0.55, tau=0.004, pan=pan, seed=int(t * 1000) + 7)

def thump(buf, t, peak=0.5, f=68):
    add_sine(buf, t, 0.34, f, 44, peak, tau=0.10)
    add_noise(buf, t, 0.03, peak * 0.2, lp=0.3, tau=0.008, seed=int(t * 977) + 3)

def chime(buf, t, freq, peak=0.15, pan=0.0):
    add_sine(buf, t, 1.1, freq, freq, peak, tau=0.34, pan=pan)
    add_sine(buf, t, 1.1, freq * 2, freq * 2, peak * 0.30, tau=0.20, pan=pan)
    add_sine(buf, t, 1.1, freq * 3, freq * 3, peak * 0.10, tau=0.11, pan=pan)

def crack(buf, t, peak=0.34):
    add_noise(buf, t, 0.10, peak, lp=0.85, hp=True, tau=0.028, seed=62)
    add_sine(buf, t, 0.30, 2413, 2380, peak * 0.32, tau=0.07)
    add_sine(buf, t, 0.24, 3120, 3090, peak * 0.20, tau=0.05)
    thump(buf, t, peak * 0.7, 60)

GROUP_PITCH = {"A": 180, "B": 240, "C": 320, "D": 420, "E": 500, "F": 300,
               "G": 380, "H": 460, "I": 640, "J": 720, "K": 700, "L": 150}
JEWEL_FREQS = [880, 1046, 1175, 1319, 1568, 1760, 2093, 2349]

# ---------------- bed stem ----------------
BED_POINTS = [(0.0, 0.0), (0.4, 0.55), (4.5, 0.7), (10.5, 1.0), (20.0, 1.0),
              (24.5, 0.85), (24.62, 0.22), (26.5, 0.5), (27.5, 0.8),
              (34.5, 0.65), (38.6, 0.6), (39.0, 0.55), (39.5, 0.0)]
def bed_gain(t):
    for (t0, g0), (t1, g1) in zip(BED_POINTS, BED_POINTS[1:]):
        if t0 <= t <= t1:
            return g0 + (g1 - g0) * (t - t0) / (t1 - t0)
    return 0.0

BED_AMP = 0.14
ns = 0.0
for i in range(N):
    t = i / SR
    g = bed_gain(t) * BED_AMP
    v = (math.sin(2 * math.pi * 55 * t) * 0.9
         + math.sin(2 * math.pi * 82.41 * t + 0.4) * 0.7
         + math.sin(2 * math.pi * 110 * t + 1.1) * 0.5)
    if 10.5 <= t <= 24.5:
        v += math.sin(2 * math.pi * 164.81 * t + 2.0) * 0.28
    ns += 0.06 * (rng.uniform(-1, 1) - ns)
    v += ns * 0.5
    # soft-clip the bed's rare crests (tanh @0.22): RMS nearly unchanged,
    # peak drops ~4 dB — headroom is bought here, not from the cues
    BED[0][i] = 0.22 * math.tanh(v * g * 0.94 / 0.22)
    BED[1][i] = 0.22 * math.tanh(v * g * 1.0 / 0.22)

# ---------------- cue stem (all from timeline.json) ----------------
for t in (0.15, 0.50, 0.85):
    tick(CUE, t, 460, 0.15)
for t in (0.10, 0.45, 0.80):
    thump(CUE, t, 0.18, 70)
tick(CUE, 5.29, 300, 0.09); thump(CUE, 9.04, 0.12, 64)
t0, t1 = TL["tamper"]["comp"]
i0, i1 = int(t0 * SR), int(t1 * SR)
for i in range(i0, i1):
    x = (i - i0) / (i1 - i0)
    v = 0.04 * x * (math.sin(2 * math.pi * 2400 * i / SR) + math.sin(2 * math.pi * 2417 * i / SR))
    CUE[0][i] += v; CUE[1][i] += v
crack(CUE, TL["cues"]["tamper_crack_comp"])
for s in TL["steps_out"]:
    t = s["comp_time"]
    if s["step"] == 23:
        add_sine(CUE, t, 0.20, 120, 96, 0.38, tau=0.06)
        add_sine(CUE, t, 0.30, 1244, 1240, 0.09, tau=0.09)
        tick(CUE, t, 500, 0.16)
    elif 75 <= s["step"] <= 82:
        chime(CUE, t, JEWEL_FREQS[s["step"] - 75], 0.14, pan=(-0.3 if s["step"] % 2 else 0.3))
    elif s["tier"] == 5:
        pass
    else:
        tick(CUE, t, GROUP_PITCH[s["group"]], 0.14, pan=(-0.12 if s["step"] % 2 else 0.12))
add_noise(CUE, 20.458, 4.0, 0.045, lp=0.08, seed=124)
for k in range(16):
    tick(CUE, 22.6 + k * 0.115, 460, 0.09, pan=(-0.2 if k % 2 else 0.2))
thump(CUE, TL["cues"]["hold_thump_comp"], 0.30, 58)
crack(CUE, TL["break"]["dim_start"] + 0.02, 0.38)
for t in TL["break"]["stamps_at"]:
    thump(CUE, t, 0.36, 76)
for s in TL["steps_home"]:
    t = s["comp_time"]
    if 75 <= s["step"] <= 82:
        chime(CUE, t, JEWEL_FREQS[s["step"] - 75] * 0.75, 0.09, pan=(0.3 if s["step"] % 2 else -0.3))
    elif s["tier"] == 5:
        pass
    else:
        tick(CUE, t, GROUP_PITCH[s["group"]] * 0.84, 0.10, pan=(0.12 if s["step"] % 2 else -0.12))
add_noise(CUE, 28.2, 4.6, 0.03, lp=0.08, seed=87)
thump(CUE, TL["cues"]["seal_strike_comp"], 0.52, 55)
add_sine(CUE, TL["cues"]["seal_strike_comp"], 0.9, 1568, 1568, 0.06, tau=0.3)
add_sine(CUE, TL["cues"]["seal_strike_comp"], 0.9, 2093, 2093, 0.05, tau=0.26)
thump(CUE, TL["cues"]["close_card_comp"] + 0.25, 0.2, 62)
chime(CUE, TL["cues"]["seal_ring_comp"], 2093, 0.10)

# ---------------- BS.1770-4 ----------------
PRE_B = [1.53512485958697, -2.69169618940638, 1.19839281085285]
PRE_A = [1.0, -1.69065929318241, 0.73248077421585]
RLB_B = [1.0, -2.0, 1.0]
RLB_A = [1.0, -1.99004745483398, 0.99007225036621]

def kfilter(x):
    y = array("f", bytes(4 * len(x)))
    x1 = x2 = y1 = y2 = 0.0
    for i, s in enumerate(x):
        o = PRE_B[0] * s + PRE_B[1] * x1 + PRE_B[2] * x2 - PRE_A[1] * y1 - PRE_A[2] * y2
        x2, x1, y2, y1 = x1, s, y1, o
        y[i] = o
    z = array("f", bytes(4 * len(x)))
    x1 = x2 = y1 = y2 = 0.0
    for i, s in enumerate(y):
        o = RLB_B[0] * s + RLB_B[1] * x1 + RLB_B[2] * x2 - RLB_A[1] * y1 - RLB_A[2] * y2
        x2, x1, y2, y1 = x1, s, y1, o
        z[i] = o
    return z

def loudness(chans):
    ks = [kfilter(c) for c in chans]
    block = int(0.400 * SR); hop = int(0.100 * SR)
    zs = []
    for st in range(0, N - block + 1, hop):
        z = 0.0
        for c in ks:
            seg = c[st:st + block]
            s = 0.0
            for v in seg: s += v * v
            z += s / block
        zs.append(z)
    def L(zs_):
        m = sum(zs_) / len(zs_)
        return -0.691 + 10 * math.log10(m) if m > 0 else -70.0
    a = [z for z in zs if z > 0 and -0.691 + 10 * math.log10(z) > -70]
    la = L(a)
    r = [z for z in a if -0.691 + 10 * math.log10(z) > la - 10]
    return L(r)

def peak(chans):
    pk = 0.0
    for c in chans:
        for i in range(N - 1):
            a, b = abs(c[i]), abs(c[i + 1])
            m = a if a > b else b
            if m > pk: pk = m
    return pk

Lb = loudness(BED); Lc = loudness(CUE)
Pb = peak(BED); Pc = peak(CUE)
print(f"bed: {Lb:.2f} LUFS, peak {20*math.log10(Pb):.2f} dBFS · cues: {Lc:.2f} LUFS, peak {20*math.log10(Pc):.2f} dBFS")

# solve: cues are peak-limited to -5 dBFS (their energy is small; the bed
# carries the loudness), bed gain from energy sum, exact trim at the end
CEIL = 10 ** (-2.3 / 20)
CUE_CEIL = 10 ** (-4.5 / 20)
cg = min(1.0, CUE_CEIL / Pc)
target_e = 10 ** ((-14.0 + 0.691) / 10)
eb = 10 ** ((Lb + 0.691) / 10); ec = 10 ** ((Lc + 0.691) / 10)
bg2 = (target_e - ec * cg * cg) / eb
bg = math.sqrt(bg2) if bg2 > 0 else 0.3
print(f"solve: bed gain {bg:.3f} ({20*math.log10(bg):+.2f} dB), cue gain {cg:.3f}")

MIX = (array("f", [BED[0][i] * bg + CUE[0][i] * cg for i in range(N)]),
       array("f", [BED[1][i] * bg + CUE[1][i] * cg for i in range(N)]))
lm = loudness(MIX); pm = peak(MIX)
trim = -14.0 - lm
tg = 10 ** (trim / 20)
if pm * tg > CEIL:
    tg = CEIL / pm
    print(f"trim limited by peak: {20*math.log10(tg):+.2f} dB")
else:
    print(f"final trim: {trim:+.2f} dB")
for c in MIX:
    for i in range(N): c[i] *= tg
lf = loudness(MIX); pf = peak(MIX)
print(f"FINAL: {lf:.2f} LUFS · peak {20*math.log10(pf):.2f} dBFS (interp floor est; encode read-back governs)")

out = HERE / "score.wav"
with wave.open(str(out), "wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
    frames = bytearray()
    for i in range(N):
        a = max(-1.0, min(1.0, MIX[0][i])); b = max(-1.0, min(1.0, MIX[1][i]))
        frames += struct.pack("<hh", int(a * 32767), int(b * 32767))
    w.writeframes(bytes(frames))
print("wrote", out, out.stat().st_size, "bytes")
(HERE / "score_report.json").write_text(json.dumps(
    {"integrated_lufs_engine": round(lf, 2), "peak_est_dbfs": round(20 * math.log10(pf), 2),
     "bed_gain": round(bg, 3), "cue_gain": round(cg, 3)}, indent=1))
