# claimground prototype (throwaway)

## The question

Does the two-phase claim-graph model feel right when driven by hand?

- (a) does grounding-before-prose flow naturally or fight the author?
- (b) does `try_close` fire BROKEN at the right moments?
- (c) is one-question-at-a-time bearable?
- (d) does the extract-and-map check on prose feel like a real gate or a nuisance?

## Run it

```
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

(fill in after driving it)

- (a)
- (b)
- (c)
- (d)
