## REPLICATION.md — the peer-review package, and a defect it caught

Chancellor is built to be checked. The source distribution is the
peer-review package: install it, run the suite it ships, verify the demo's
receipt book cold — everything a reviewer needs is inside the artifact.

Release 1.2.2 broke that contract: its source distribution shipped the test
suite without the files the suite reads, so the artifact could not test
itself — collection died before a single test ran. Nothing was removed; no
`MANIFEST.in` had ever existed, and every test that grew a dependency
outside the package left that dependency behind. The release gates could
not see it — the one gate that runs the suite ran it in the source
checkout, the one place the defect cannot occur.

The catch came from outside — the direction this system is built to be
checked from. Sarah, an independent Muse instance serving a different
principal, installed the published package cold, the way any reviewer
would, and reported it non-functional. The estate's own replication
machinery — a full-product test on a clean machine — measured the same
failure; a Wisdom Council traced it to the root. The repair:

- **1.2.3 is published** — the complete, self-testing artifact: **296
  passed, 1 skipped, 0 failed**, run from the built source distribution
  itself in a clean environment (the one skip is a named environment
  precondition; the full tree run is 297).
- **RS-G10 is now a standing gate**: no release publishes until its shipped
  suite has been executed from the built artifact.
- **1.1.0, 1.2.0, 1.2.1, and 1.2.2 are superseded** — marked so on GitHub, with withdrawal on PyPI to follow. 1.0.0 does not carry the defect and stands.

The first independent reviewer of this package was another agent, working
for someone else — and the mechanism worked exactly as the product
describes: an independent agent, installing the published artifact,
surfacing what the home team's gates could not see. That is the system
working as designed — defects surfaced with receipts, repaired in the
open. Experts err; the question is whether the machinery catches it.
*Try again. Fail again. Fail better.* — Beckett. The full record is in the
1.2.3 release notes and `CHANGELOG.md`.
