---
name: claimground
description: Build the burden of proof for a claim. Decomposes one falsifiable hypothesis into a claim graph, grounds every leaf in real sources with exact locators, closes or breaks the graph BEFORE any prose exists, then writes prose that answers to the graph. Outputs a scannable self-contained HTML report with a copy-page-as-text button. Use when the user invokes /claimground, asks to validate a hypothesis with sources, build a burden of proof, stress-test a claim before publishing it, or wants a well-researched write-up whose every sentence traces to a receipt.
---

# claimground

Claim graph first, prose second. The engine lives at
`~/Code/claimground/claimground_lib.py` (repo: github.com/ctavolazzi/claimground).
You are the author driving it: you make the small judgments (what a claim
needs, whether a source says a thing, where exactly); the engine makes the
mechanical ones (close, word bands, banned strings, claim-to-graph mapping).

## Contract

- **Input:** whatever the user gives after /claimground, or the thing under
  discussion in chat: a claim, a draft, a belief, a business assumption.
- **Output:** a run directory `~/Code/claimground-runs/<slug>/` containing
  `state.json` (the graph, resumable) and `report.html` (the deliverable),
  the report opened in the browser, and a chat summary that leads with the
  verdict. The report page has a "copy page as text" button that copies a
  clean plain-text version of the entire report for use in other programs.

## Pipeline

**0. Intake.** Distill the input to ONE falsifiable sentence: no newline,
under 300 chars, something a reader could disagree with. "AI is changing
things" dies here. If the input is a topic, propose the sharpest falsifiable
version, state the reframe in chat, and proceed. Only ask the user when two
materially different hypotheses are both plausible readings.

**1. Decompose.** Two questions per claim, one claim at a time:
"what must be true for this to hold?" (need edges) and "what is the
strongest case this is false?" (attack edges; attacks get grounded too).
A claim is a leaf when a single source at a single locator could settle it.
Mark the linchpin: the leaf that, if it fell, takes the root with it.
Write the graph directly into `state.json` (schema is in the lib docstring),
then run `validate`.

**2. Ground.** This is the research phase and the reason the run has value.
Use WebSearch and WebFetch to find REAL sources. Discipline:

- Every ground edge carries a `locator` (section, page, table, quoted
  passage position) and, when possible, a short exact `quote`.
- Grade honestly after fetching: LIVE (says what the claim says), DEAD
  (unreachable), SAYS_OTHERWISE (says the opposite; name the claim).
- Work-across (the ACH rule): after attaching a source, test it against
  every other claim it could plausibly touch, ATTACKS INCLUDED. Evidence
  is never allowed to testify for one side only.
- Cannot ground a leaf? Either decompose it smaller or declare a hole with
  an honest why. NEVER fabricate a source, a locator, or a quote. A hole
  is the honest move and the engine prices it correctly.

**3. Close.** `python3 ~/Code/claimground/claimground_lib.py close state.json --record`.
BROKEN means REFUTED and the run ends here, before any prose: render the
report anyway (the dead-claim ledger IS the deliverable) and tell the user
what killed it. REFUTED is a terminal success state, not a failure.
Cause "ungroundable" reads as: the claim could not carry its burden of proof.

**4. Compose** (only reachable from CLOSED). `plan --apply` cuts passages;
objections and the linchpin always get their own passage and ship with the
work. Write each passage's prose (voice per `constraints.voice`; the engine
bans the em dash and the m-word), save it to a temp file, then
`fill state.json <spec> <file>` and `check state.json <spec> --accept`.
An unmapped sentence has exactly two futures: cut it from the prose, or
ground it into the graph FIRST (add the claim + source, re-close, refill).
Fix named failures; never loop blindly.

**5. Render and report.** `render state.json report.html`, then `open` it.
Chat summary leads with the verdict, then: the linchpin and what holds it,
which objections stand answered, what single new piece of evidence would
flip the verdict, and the run path. Keep it short; the page carries detail.

## House rules

- No em dashes anywhere; never the m-word (mechanically enforced in prose,
  but hold the line in chat and report text too).
- The verdict is settled by the graph, not by the prose or by you.
- UNDECIDED beats padded support. Say what is missing.
- Log the run to empirica when available: `finding-log` with the verdict,
  hypothesis, and run path; impact scaled to what the verdict changes.

## Quick CLI reference

```
LIB=~/Code/claimground/claimground_lib.py
python3 $LIB validate state.json          # sanity-check the hand-built graph
python3 $LIB close    state.json --record # CLOSED | OPEN(floating) | BROKEN -> REFUTED
python3 $LIB plan     state.json --apply  # cut + bind passages (needs CLOSED)
python3 $LIB fill     state.json p1 prose.txt
python3 $LIB check    state.json p1 --accept
python3 $LIB verdict  state.json
python3 $LIB render   state.json report.html
```
