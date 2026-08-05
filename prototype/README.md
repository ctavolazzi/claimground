# claimground prototype (throwaway)

## The question

Does the two-phase claim-graph model feel right when driven by hand?

- (a) does grounding-before-prose flow naturally or fight the author?
- (b) does `try_close` fire BROKEN at the right moments?
- (c) is one-question-at-a-time bearable?
- (d) does the extract-and-map check on prose feel like a real gate or a nuisance?

## Run it

```bash
python3 claimground_prototype.py
```

Press `x` to load the standing-desk demo seed. Seed 1 reaches CLOSED
(then `c`, `p`, `f`, `k` walk phase 2); seed 2 hits BROKEN("source
contradicts") the moment you press `c`, before any prose exists. Or start
empty with `h` and drive the whole loop by hand.

Notes: state is memory only (quit and it is gone, on purpose); FETCH is
stubbed as a "reachable? y/n" question; the real system's graph.json and
trail.jsonl design is unaffected by anything here.

## VERDICT

Filled 2026-08-04, after the scripted prototype runs and the first real
run (the Johnny Autoseed cost claim, examples/johnny-autoseed-cost/ in
the repo, REFUTED before prose).

- (a) **Grounding-before-prose flows naturally.** The one place it fought
  the author: a derived comparison (robot cost per bed vs labor cost per
  bed) has no single source at a single locator, because it is arithmetic
  over other grounded leaves. The honest resolution was a hole whose
  why-text does the arithmetic from grounded inputs only. It worked, but
  it wants a first-class "computed claim" node type in a future version.
- (b) **try_close fires BROKEN at the right moment.** In the real run the
  break landed exactly where the money question lived (the linchpin), the
  instant the hole was declared, with zero prose written. The cause label
  "ungroundable" reads correctly as "could not carry its burden of proof."
- (c) **One-question-at-a-time is bearable.** Real run measured 2 to 4
  pointed judgments per leaf. The expensive part was source EXISTENCE
  hunting (five fetches across four candidates to find one groundable
  sentence about seeding speed), not the judgments themselves. The ACH
  graveyard's judgment-overload failure mode did not appear at this scale.
- (d) **The extract-and-map gate is real, not a nuisance,** on prototype
  evidence: the negative control failed on all three axes at once and the
  named-failure output made the fix obvious. Verdict on REAL prose is
  still pending, because the first real run refuted before phase 2.
