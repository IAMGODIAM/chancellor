# Census Lane — Tools & Connectors (fixture, miniature)

## 1. Connector census — ~/workspace/custom-connectors/

| # | Directory / connector id | Helpers in bin/ | Purpose (one line, from its own docs) |
|---|---|---|---|
| 1 | custom.legacy-alpha | a.py | Alpha API |
| 2 | custom.beta | b.py | Beta API |
| 3 | custom.gamma | — (bin empty) | Gamma API |

## 2. Tooling census — the fleet's own machinery

| Toolset | Files (total / .py) | Purpose (one line) |
|---|---|---|
| `~/workspace/tools/bin/` | 4 / 2 | Test toolset machinery |

## 3. GitHub state — door-checked this run

### 3a. Connectors vs GitHub

**ON GITHUB — 1 of 3** (all at `E5EnclaveInc/agent-skills`, path `skills/<name>/`, SKILL.md + bin helpers present):
alpha

**HELD — 1 of 3** (see §4): custom.beta — 0 paths in either tree.

**LOCAL-ONLY (gap) — 1 of 3** (0 paths in either tree, NOT on the HELD register):
- **custom.gamma** — doc-only locally (empty bin); no export.

Wiki cross-check: the wiki tree holds no connector docs for any of the 3.

### 3b. Toolsets vs GitHub

| Toolset | State | Evidence |
|---|---|---|
| tools/bin (2 helpers) | **LOCAL-ONLY (gap)** | 0 paths in either tree |

**Bottom line:** of 1 toolsets censused, exactly 0 (none) has a GitHub home.
