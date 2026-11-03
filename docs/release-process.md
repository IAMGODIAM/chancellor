# The release process — operator's page

One page, for whoever cuts the next release. The machinery exists
because a release once shipped with the previous release's PyPI page:
every surface that repeats the version or the test count is now either
*generated from* the single declaration or *checked against* it, and
the publish pipeline refuses a desync before anything uploads.

## The single declaration

The version lives in exactly one place: `pyproject.toml`,
`[project] version`. Everything else derives or is checked:

- `chancellor.__version__` derives at import (installed metadata, else
  the pyproject beside the source tree, else the `0.0.0+unknown`
  sentinel) — it is never a typed literal again.
- The README's status line, tests line, badge alts, and current
  "What's new" heading live between `<!-- release-sync:… -->` markers
  and are rewritten by the render step only.
- `CITATION.cff` and both badge SVGs are generated whole from
  `tools/templates/`. (`cff-version` in the CITATION file is the CFF
  *schema* version — never the product version.)
- The test count is computed from a green suite run's JUnit XML
  (passing = tests − failures − errors − skipped), never typed.
- `tools/release_surfaces.toml` is the manifest: the line between
  living surfaces and the record. Historical text (BUILD-LOG entries,
  evidence, past changelog entries, attribution sentences) is exempt
  there by name and is never rewritten by this machinery.

## Cutting a release

1. Decide the version (a human call — patch vs minor is a semantic
   claim the machinery has no opinion on) and bump **only**
   `pyproject.toml`.
2. Write the changelog head: `## [X.Y.Z] — YYYY-MM-DD` at the top of
   `CHANGELOG.md`, with the release's prose under it. The words are
   yours; the gate checks only that the head names the declared
   version and that its date equals the CITATION date the render
   produces. (`tools/release_sync.py notes` prints the head entry —
   copy it as the GitHub Release body.)
3. Run the suite and render from its count:
   `python tools/release_sync.py count --junitxml=release-junit.xml`
   then `python tools/release_sync.py render --junitxml=release-junit.xml`.
4. Sanity-check locally: `python tools/release_sync.py check --offline`
   (fast consistency), and review the render diff — it should touch
   only managed surfaces.
5. Commit, tag `vX.Y.Z`, push the tag. The gates workflow runs the
   full Gate A set on the tag push; a failure there stops everything
   before a Release exists.
6. Create the GitHub Release from the tag. Publishing it triggers
   `publish.yml`: **Gate A** re-checks the exact tagged tree
   (tag↔declaration, derived surfaces, changelog head, a fresh suite
   count, the literal scan, the dispatch guard), the distributions
   build, **Gate B** verifies the built wheel and sdist carry the
   declaration and the checked README, and only then does Trusted
   Publishing upload. There is no override: a red gate means fix the
   tree and cut a new tag.
7. After upload, read the PyPI page back. The release-drift watch also
   compares the served page against the tag's tree daily and speaks
   only on drift — silence is the design working.

Manual `workflow_dispatch` of publish.yml is a guarded fallback, not a
shortcut: it requires the dispatch ref to be the release tag and an
`expected_version` input equal to the declaration (check G9). A
dispatch from a branch always fails.

## If a release stops

The gate prints one line per check — `RS-G<n> PASS|FAIL … expected=…
found=…` — in the workflow log and locally from the same command.
The line names the surface and both values; fix the tree (usually:
re-run `render` from a fresh count, or write the changelog head), and
re-tag. Never edit a generated surface by hand to make a line pass:
the next render would expose it, by design.
