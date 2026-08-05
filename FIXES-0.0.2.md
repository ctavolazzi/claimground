# v0.0.2 fix list

Rule: every item here traces to friction actually observed in a run.
No speculative features.

## Shipped in 0.0.2 (observed in the first real run, 2026-08-04)

1. **WALLED grade.** Observed: bls.gov returned HTTP 403 to both WebFetch
   and curl with a browser UA. A refusal is not a dead citation, and it
   must not be laundered into support. WALLED grounds nothing (only LIVE
   does) but stays on the record; the 403 page is archived in the run
   cache as evidence.
2. **Per-passage receipts.** Custody is the product: every prose passage
   now renders an inline receipts block (claim id, source, locator, grade,
   date). Plain-text copy includes them.
3. **Grade dates and notes displayed.** Grade records carry `date` and
   `note`; the sources table and receipts show them, so "grade from the
   fetched artifact, record the access date" is visible, not just stored.
4. **Tree hole-badge truncation.** Observed: a full hole why-text in a
   no-wrap badge overflowed the page edge. Tree badges truncate at 60
   chars; the dead-claim ledger carries the full text.

## Candidates for 0.0.3 (observed, deferred)

5. **Computed-claim node type.** The linchpin was arithmetic over other
   grounded leaves (capex / coverage vs wage x time); no single source can
   settle it at a locator. The workaround (a hole whose why-text does the
   arithmetic from grounded inputs only) is honest but second-class. A
   `computed` node kind whose "source" is a formula over named claim ids
   would make the derivation itself walk-backable.
6. **Argdown export.** Design-session candidate, cheap: one serialization
   function buys the maintained VS Code argument-map rendering. Document
   the lossy nuance: Argdown's `+` means support, ours means
   necessary-condition. Export only, no round-trip.
7. **Judgment-count telemetry.** This run counted judgments manually
   (2 to 4 per leaf) via a trail note. Worth a first-class trail field so
   the ACH judgment-overload failure mode is measured, not remembered.
8. **Cache rawness.** Raw HTML is cached via curl, and every load-bearing
   quote was verified present in the cached bytes this run. But JS-heavy
   pages may not contain their rendered text server-side; a headless-DOM
   dump fallback would close that gap. WebFetch reading digests are not
   themselves archived.
9. **Map threshold on real prose: now measured** (robot-cost-gap run,
   2026-08-04). A deliberate natural-prose probe of p1 had ALL FOUR
   sentences rejected at threshold 0.6 despite carrying every sourced
   number. Observed failure modes: (a) synonym substitution
   (robot/seeder, runs/sells, farms/fields) defeats token overlap;
   (b) sentence fusion, one sentence expressing two claims, fails both
   claims individually; (c) existence-negation sentences ("X does not
   exist") evade the assertive-sentence extractor entirely, passing with
   zero checkable sentences. Net: the gate forces receipt-shaped prose.
   For grant evidence sections that is arguably a feature; for narrative
   writing it is a real cost. Candidate fixes for 0.0.3: per-claim alias
   lists, multi-claim joint mapping for fused sentences, and an
   existence-claim pattern in the extractor. Do not silently lower the
   threshold; it correctly refused paraphrase drift.

   SHIPPED in 0.0.7, all three, plus two new layers: the check is now
   five layers (bytes, extraction, mapping, coverage, custody). Coverage
   fails silent omission of a spec claim; custody fails numerals that do
   not trace to the mapped claim or its source quote (a drifted digit
   previously passed mapping at 0.85 overlap) and quoted strings without
   a recorded source quote. Aliases are author-declared in the graph, so
   every accepted synonym is auditable. Also fixed: the tokenizer kept
   apostrophes through stemming, so "seeder's" never matched "seeder".
   Every layer was negative-controlled before shipping.

## Grounding assist (build-trigger check, per design session)

The DeepTutor-style locator-finding assist does NOT yet earn its build.
This run's pain was source EXISTENCE hunting (five fetches across four
candidate pages to find one groundable sentence about seeding speed), not
locator-finding within long documents. Revisit if a run bogs down inside
a single long PDF.

## Rejected, for the record (design session 2026-08-04)

- memvid: corpus-scale memory engine, wrong scale; its append-only design
  independently validates ours.
- openhuman: GPL-3.0 contamination risk, wrong layer.
