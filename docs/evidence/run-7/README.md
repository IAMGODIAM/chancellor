# RUN-7 — the 10x evidence run

**[VERIFIED-RESULTS.md](VERIFIED-RESULTS.md)** is the record: the RUN-5 program repeated at 10x volume on the frozen tree `31ea039`, on ten Lambda boxes, collected 2026-11-02 and verified by two independent lanes — a purpose-built recount that imports no product code, and the product's own offline verifier run over every collected log. Governed drift is 0 everywhere it was measured; every figure in the document was recounted from the raw collected outputs, and every bound is printed with its denominator.

Headline: Suite B 56,000 runs — Part A governed **0 / 18,000** (95% upper bound 0.0166%), ungoverned 3,000 / 18,000 on identical fault manifests; Part B drift 0 in all 200 cells; T3 3,000 / 3,000 gates (a 10-box reproduction of the 300-gate instrument, labeled as such in the record); 40 / 40 soaks, 19,200 segments, 1,920 injected faults, drift 0, 18,403 chain entries with 0 breaks, 2,320 checkpoints.

The run card, launch report, raw outputs, and verification data live with the program's war-room record (`lambda-run-7/` in the Final Protocol war room); this folder carries the verified-results document, as the RUN-5 folder carries its report. The README's Results section quotes this document; where any summary and this document disagree, this document governs.
