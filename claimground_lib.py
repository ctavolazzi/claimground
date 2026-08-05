#!/usr/bin/env python3
"""claimground: claim graph first, prose second.  v0.0.1

Engine for building the burden of proof behind one falsifiable sentence.
Phase 1 grounds a claim graph in sources (refutation can only happen here,
before any prose exists). Phase 2 renders prose over a closed graph and
holds every sentence accountable to it.

The LOGIC layer is pure: plain state dict, append-only writes, no I/O.
The CLI operates on a state.json file:

    python3 claimground_lib.py validate  state.json
    python3 claimground_lib.py close     state.json [--record]
    python3 claimground_lib.py plan      state.json [--apply]
    python3 claimground_lib.py fill      state.json <spec_id> <prose.txt>
    python3 claimground_lib.py check     state.json <spec_id> [--accept]
    python3 claimground_lib.py verdict   state.json
    python3 claimground_lib.py render    state.json <out.html>
    python3 claimground_lib.py argdown   state.json <out.argdown>
    python3 claimground_lib.py map       state.json <out.svg>

State schema (all lists append-only; latest record wins):
    nodes     [{id, text}]                       claims; nodes[0] is the root
    edges     [{kind: need|attack, src, dst}]
              [{kind: ground, claim, source, locator, quote?}]
    sources   [{id, ref, url?, bears_on}]
    grades    [{source, grade: LIVE|DEAD|SAYS_OTHERWISE|WALLED, claim?,
                quote?, date?, note?}]
              WALLED: paywalled or robot-blocked. A refusal is not a dead
              citation, and it is never laundered into support: WALLED
              grounds nothing (only LIVE does) but stays on the record.
    holes     [{claim, why}]
    linchpin  [claim_id]          latest wins
    leaves    [claim_id]
    specs     [{id, claims, register, label, target}]
    bindings  [{spec, address}]
    prose     [{address, kind: placeholder|fill, text}]
    trail     [{event, ...}]
    done      [spec_id]
    constraints {banned?: [extra strings], map_threshold?, word_tol?, voice?}
    meta      {slug?, date?, title?}

Grown from the throwaway prototype in prototype/ (its question: does the
two-phase model feel right driven by hand). Stdlib only.
"""

import html
import json
import re
import sys
from datetime import date
from pathlib import Path

VERSION = "0.0.6"

BANNED_DEFAULT = ["\u2014", "man" "ifesto"]  # escaped/split on purpose:
                                             # this source never contains
                                             # its own banned strings
MAP_THRESHOLD_DEFAULT = 0.6
WORD_TOL_DEFAULT = (0.5, 1.6)

STOP = set("""the a an and or of for to in on with is are was were it its
this that who which as at by be but not from over under across their our
your my we you they he she""".split())

ASSERT_STEMS = {"caus", "reduc", "worsen", "increas", "improv", "study",
                "studi", "show", "found", "percent", "accord", "lead",
                "led", "suggest", "cost", "doubl", "halv", "cut", "grow",
                "grew", "fell", "rose", "requir", "prov", "measur"}


# =====================================================================
# LOGIC  (portable, pure, no I/O)
# =====================================================================

def _stem(tok):
    for suf in ("ing", "ed", "es", "s"):
        if tok.endswith(suf) and len(tok) - len(suf) >= 3:
            tok = tok[: -len(suf)]
            break
    if tok.endswith("e") and len(tok) > 3:
        tok = tok[:-1]
    return tok


def tokens(text):
    raw = re.findall(r"[a-z0-9']+", text.lower())
    return {_stem(t) for t in raw if t not in STOP}


def words(text):
    return len(re.findall(r"[A-Za-z0-9']+", text))


def _constraints(state):
    c = state.get("constraints") or {}
    return {"banned": BANNED_DEFAULT + list(c.get("banned", [])),
            "map_threshold": c.get("map_threshold", MAP_THRESHOLD_DEFAULT),
            "word_tol": tuple(c.get("word_tol", WORD_TOL_DEFAULT)),
            "voice": c.get("voice", "plain declarative")}


def node(state, cid):
    return next(n for n in state["nodes"] if n["id"] == cid)


def need_children(state, cid):
    return [e["dst"] for e in state["edges"]
            if e["kind"] == "need" and e["src"] == cid]


def attackers_of(state, cid):
    return [e["dst"] for e in state["edges"]
            if e["kind"] == "attack" and e["src"] == cid]


def ground_edges(state, cid):
    return [e for e in state["edges"]
            if e["kind"] == "ground" and e["claim"] == cid]


def latest_grade(state, sid):
    g = None
    for rec in state["grades"]:
        if rec["source"] == sid:
            g = rec["grade"]
    return g


def latest_grade_rec(state, sid):
    r = None
    for rec in state["grades"]:
        if rec["source"] == sid:
            r = rec
    return r or {}


def floating(state):
    holed = {h["claim"] for h in state["holes"]}
    return [n["id"] for n in state["nodes"]
            if not need_children(state, n["id"])
            and not ground_edges(state, n["id"])
            and n["id"] not in holed]


def need_chain(state):
    if not state["nodes"]:
        return []
    seen, queue = [], [state["nodes"][0]["id"]]
    while queue:
        c = queue.pop(0)
        if c in seen:
            continue
        seen.append(c)
        queue += need_children(state, c)
    return seen


def _need_leaves(state, cid):
    seen, queue, leaves = set(), [cid], []
    while queue:
        c = queue.pop(0)
        if c in seen:
            continue
        seen.add(c)
        kids = need_children(state, c)
        if kids:
            queue += kids
        else:
            leaves.append(c)
    return leaves


def _live_grounded(state, cid):
    return any(latest_grade(state, e["source"]) == "LIVE"
               for e in ground_edges(state, cid))


def fully_grounded(state, cid):
    return all(_live_grounded(state, leaf)
               for leaf in _need_leaves(state, cid))


def _contradicted(state, cid):
    for g in state["grades"]:
        if g["grade"] == "SAYS_OTHERWISE" and g.get("claim") == cid:
            if latest_grade(state, g["source"]) != "DEAD":
                return g["source"]
    return None


def try_close(state):
    """The 6-step rule. Pure read; appends nothing."""
    if not state["nodes"]:
        return ("OPEN", [])
    fl = floating(state)
    if fl:
        return ("OPEN", fl)
    chain = need_chain(state)
    holed = {h["claim"] for h in state["holes"]}
    for cid in chain:
        if cid in holed:
            return ("BROKEN", cid, "ungroundable")
    for cid in chain:
        if _contradicted(state, cid):
            return ("BROKEN", cid, "source contradicts")
    for e in state["edges"]:
        if e["kind"] == "attack":
            target, attacker = e["src"], e["dst"]
            if fully_grounded(state, attacker) and not fully_grounded(state, target):
                return ("BROKEN", target, "attack stands")
    if state["linchpin"]:
        lp = state["linchpin"][-1]
        if not _live_grounded(state, lp):
            return ("BROKEN", lp, "linchpin bare")
    return ("CLOSED",)


def record_refuted(state, claim_id, cause):
    state["trail"].append({"event": "verdict", "verdict": "REFUTED",
                           "claim": claim_id, "cause": cause})


def plan_passages(state):
    """Auto-cut: main line, one spec per attack subtree, linchpin alone.
    Every node lands in exactly one spec."""
    lp = state["linchpin"][-1] if state["linchpin"] else None
    attack_roots = [e["dst"] for e in state["edges"] if e["kind"] == "attack"]
    attack_subs = []
    for a in attack_roots:
        seen, queue = [], [a]
        while queue:
            c = queue.pop(0)
            if c in seen:
                continue
            seen.append(c)
            queue += need_children(state, c)
        attack_subs.append(seen)
    in_attack = {c for sub in attack_subs for c in sub}
    taken = set()
    specs = []

    def add_spec(claims, label):
        claims = [c for c in claims if c not in taken]
        if not claims:
            return
        taken.update(claims)
        n_src = sum(len(ground_edges(state, c)) for c in claims)
        specs.append({"id": "p%d" % (len(specs) + 1), "claims": claims,
                      "register": "argument", "label": label,
                      "target": 12 * len(claims) + 5 * n_src})

    add_spec([n["id"] for n in state["nodes"]
              if n["id"] not in in_attack and n["id"] != lp], "main line")
    for sub in attack_subs:
        add_spec(sub, "objection")
    if lp:
        add_spec([lp], "linchpin")
    return specs


def materialize(state, specs):
    for sp in specs:
        state["specs"].append(sp)
        addr = "blk%d" % (len(state["bindings"]) + 1)
        state["bindings"].append({"spec": sp["id"], "address": addr})
        placeholder = ("[[passage: %s | %s | ~%dw]]"
                       % (sp["id"],
                          " / ".join(node(state, c)["text"] for c in sp["claims"]),
                          sp["target"]))
        state["prose"].append({"address": addr, "kind": "placeholder",
                               "text": placeholder})
        state["trail"].append({"event": "materialize", "spec": sp["id"],
                               "address": addr})


def _address_of(state, spec_id):
    return next(b["address"] for b in state["bindings"]
                if b["spec"] == spec_id)


def latest_prose(state, addr):
    text = None
    for p in state["prose"]:
        if p["address"] == addr:
            text = p["text"]
    return text


def fill(state, spec_id, text):
    addr = _address_of(state, spec_id)
    state["prose"].append({"address": addr, "kind": "fill", "text": text})
    state["trail"].append({"event": "fill", "spec": spec_id,
                           "words": words(text)})


def mechanical(state, text, target):
    con = _constraints(state)
    recs = []
    w = words(text)
    lo = round(con["word_tol"][0] * target)
    hi = round(con["word_tol"][1] * target)
    recs.append({"check": "words.in_range", "ok": lo <= w <= hi,
                 "detail": "%d words, band %d-%d" % (w, lo, hi)})
    hit = [b for b in con["banned"] if b in text]
    recs.append({"check": "banned.absent", "ok": not hit,
                 "detail": "clean" if not hit else "banned string present"})
    refs = re.findall(r"\[src:([a-z0-9]+)\]", text)
    ids = {s["id"] for s in state["sources"]}
    dangling = [r for r in refs if r not in ids]
    recs.append({"check": "refs.resolve", "ok": not dangling,
                 "detail": "%d pointer(s), %d dangling" % (len(refs), len(dangling))})
    return recs


def extract(text):
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip())
             if s.strip()]
    return [s for s in sents
            if any(ch.isdigit() for ch in s) or '"' in s
            or (tokens(s) & ASSERT_STEMS)]


def map_claims(state, found, claim_ids):
    """Normalized token-overlap MATCH. Returns the unmapped sentences."""
    thr = _constraints(state)["map_threshold"]
    unmapped = []
    for sent in found:
        st_toks = tokens(sent)
        hit = False
        for cid in claim_ids:
            ct = tokens(node(state, cid)["text"])
            if ct and len(ct & st_toks) / len(ct) >= thr:
                hit = True
                break
        if not hit:
            unmapped.append(sent)
    return unmapped


def verdict(state):
    for t in state["trail"]:
        if t.get("event") == "verdict" and t.get("verdict") == "REFUTED":
            return "REFUTED(%s: %s)" % (t["claim"], t["cause"])
    if state["specs"] and all(sp["id"] in state["done"]
                              for sp in state["specs"]):
        return "SUPPORTED"
    return "UNDECIDED"


def validate(state):
    """[{check, ok, detail}] over a hand-built state file."""
    checks = []

    def add(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    for key in ("nodes", "edges", "sources", "grades", "holes", "linchpin",
                "leaves", "specs", "bindings", "prose", "trail", "done"):
        if key not in state:
            state[key] = []
    nids = [n.get("id") for n in state["nodes"]]
    sids = [s.get("id") for s in state["sources"]]
    add("root.exists", bool(nids), "nodes[0] is the hypothesis")
    add("claim_ids.unique", len(nids) == len(set(nids)), "")
    add("source_ids.unique", len(sids) == len(set(sids)), "")
    bad = []
    for e in state["edges"]:
        k = e.get("kind")
        if k in ("need", "attack"):
            if e.get("src") not in nids or e.get("dst") not in nids:
                bad.append("%s edge %s->%s dangles" % (k, e.get("src"), e.get("dst")))
        elif k == "ground":
            if e.get("claim") not in nids or e.get("source") not in sids:
                bad.append("ground edge %s<-%s dangles" % (e.get("claim"), e.get("source")))
            if not (e.get("locator") or "").strip():
                bad.append("ground edge on %s has no locator" % e.get("claim"))
        else:
            bad.append("edge kind %r invalid" % k)
    add("edges.wellformed", not bad, "; ".join(bad[:5]))
    bad = []
    for g in state["grades"]:
        if g.get("source") not in sids:
            bad.append("grade on unknown source %s" % g.get("source"))
        if g.get("grade") not in ("LIVE", "DEAD", "SAYS_OTHERWISE", "WALLED"):
            bad.append("grade %r invalid" % g.get("grade"))
        if g.get("grade") == "SAYS_OTHERWISE" and g.get("claim") not in nids:
            bad.append("SAYS_OTHERWISE must name a claim")
    add("grades.wellformed", not bad, "; ".join(bad[:5]))
    add("linchpin.exists",
        all(c in nids for c in state["linchpin"]),
        state["linchpin"][-1] if state["linchpin"] else "none marked")
    add("root.disagreeable", len(state["nodes"]) == 0 or
        ("\n" not in state["nodes"][0]["text"]
         and len(state["nodes"][0]["text"]) <= 300),
        "one sentence, under 300 chars")
    return checks


# =====================================================================
# RENDER  (state -> one self-contained scannable page + copy-all text)
# =====================================================================

_CSS = """
:root { --ink:#26211c; --paper:#faf8f3; --card:#ffffff; --line:#d8cdb8;
  --muted:#7a6b5d; --accent:#e07b3c; --ok:#0d9488; --bad:#c2410c;
  --mid:#d97706; --mono:'JetBrains Mono',ui-monospace,SFMono-Regular,monospace; }
@media (prefers-color-scheme: dark) {
  :root { --ink:#e8e2d6; --paper:#191613; --card:#211d19; --line:#3c352c;
    --muted:#a2937f; } }
* { box-sizing:border-box; }
html { scroll-behavior:smooth; }
body { margin:0; background:var(--paper); color:var(--ink);
  font:16px/1.65 system-ui,-apple-system,Segoe UI,sans-serif; }
header.top { position:sticky; top:0; display:flex; align-items:center;
  flex-wrap:wrap; gap:8px 12px; padding:10px 20px; background:var(--paper);
  border-bottom:2px solid var(--line); z-index:5; }
.brand { font-family:var(--mono); font-weight:700; letter-spacing:.12em;
  font-size:13px; }
nav.toc { display:flex; gap:12px; flex-wrap:wrap; font:600 11px var(--mono); }
nav.toc a { color:var(--muted); text-decoration:none;
  text-transform:uppercase; letter-spacing:.06em; }
nav.toc a:hover { color:var(--accent); }
.chip { font-family:var(--mono); font-size:12px; font-weight:700;
  padding:3px 10px; border-radius:999px; color:#fff; }
.chip.SUPPORTED { background:var(--ok); }
.chip.REFUTED { background:var(--bad); }
.chip.UNDECIDED { background:var(--mid); }
#copybtn { margin-left:auto; font:600 13px system-ui; padding:6px 14px;
  border:2px solid var(--ink); background:var(--card); color:var(--ink);
  border-radius:6px; cursor:pointer; }
#copybtn:hover { border-color:var(--accent); color:var(--accent); }
main { max-width:76ch; margin:0 auto; padding:28px 20px 80px; }
h1 { font-size:26px; line-height:1.3; margin:8px 0 4px; }
h2 { font-size:15px; letter-spacing:.1em; text-transform:uppercase;
  color:var(--muted); border-bottom:1px solid var(--line);
  padding-bottom:4px; margin:36px 0 14px; }
h3 { font-size:14px; font-family:var(--mono); margin:18px 0 6px; }
.meta { color:var(--muted); font-size:13px; font-family:var(--mono); }
.stats { display:flex; flex-wrap:wrap; gap:10px; margin:16px 0 0; }
.stat { background:var(--card); border:1px solid var(--line);
  border-radius:6px; padding:6px 12px; min-width:88px; }
.stat b { display:block; font:700 15px var(--mono); }
.stat span { font:10.5px var(--mono); color:var(--muted);
  text-transform:uppercase; letter-spacing:.05em; }
.verdict-line { font-size:18px; font-weight:600; }
article.passage { position:relative; background:var(--card);
  border:1px solid var(--line);
  border-left:4px solid var(--accent); border-radius:6px;
  padding:4px 16px 10px; margin:12px 0; }
.pcopy { position:absolute; top:10px; right:12px; font:600 11px var(--mono);
  padding:3px 9px; border:1px solid var(--line); background:var(--paper);
  color:var(--muted); border-radius:5px; cursor:pointer; }
.pcopy:hover { color:var(--accent); border-color:var(--accent); }
article.passage.objection { border-left-color:var(--mid); }
article.passage.linchpin { border-left-color:var(--ok); }
ul.tree { list-style:none; padding-left:0; }
ul.tree ul { list-style:none; padding-left:22px;
  border-left:1px solid var(--line); margin:4px 0 4px 6px; }
ul.tree li { margin:9px 0; }
.claim-line { border-radius:4px; }
.badge-row { display:flex; flex-wrap:wrap; gap:4px; margin:4px 0 0 2px; }
.cid { font-family:var(--mono); font-size:12px; color:var(--muted); }
.badge { font-family:var(--mono); font-size:11px; padding:1px 7px;
  border-radius:4px; border:1px solid var(--line);
  white-space:nowrap; }
a.badge { text-decoration:none; }
.badge-row .badge { margin-left:0; }
.badge.live { color:var(--ok); border-color:var(--ok); }
.badge.dead { color:var(--muted); }
.badge.so, .badge.hole { color:var(--bad); border-color:var(--bad); }
.badge.walled { color:var(--mid); border-color:var(--mid); }
.receipts { margin-top:8px; padding-top:8px; border-top:1px dashed var(--line);
  font:11.5px/1.7 var(--mono); color:var(--muted); }
.receipts b { color:var(--ink); font-weight:600; }
.receipts a { color:inherit; text-decoration:none;
  border-bottom:1px dotted var(--muted); }
.receipts a:hover { color:var(--accent); border-color:var(--accent); }
.gdate { font:11px var(--mono); color:var(--muted); display:block; }
tr:target td { background:rgba(224,123,60,.14); }
li:target > .claim-line { background:rgba(224,123,60,.14); }
:target { scroll-margin-top:80px; }
.mapwrap { overflow-x:auto; margin:8px 0 4px; position:relative;
  left:50%; transform:translateX(-50%); width:min(96vw, 1500px); }
.mapwrap svg { display:block; margin:0 auto; height:auto;
  font-family:var(--mono); }
.map-legend { display:flex; flex-wrap:wrap; gap:14px; margin:2px 0 18px;
  font:11px var(--mono); color:var(--muted); }
.map-legend span { display:inline-flex; align-items:center; gap:5px; }
.lg { display:inline-block; width:18px; height:0;
  border-top:2px solid var(--line); }
.lg.atk { border-top-style:dashed; border-top-color:var(--mid); }
.lg.grd { border-top-style:dotted; border-top-color:var(--ok); }
.lgbox { display:inline-block; width:11px; height:11px; border-radius:3px;
  background:var(--card); border:1.5px solid var(--ok); }
.lgbox.hole { border-color:var(--bad); border-style:dashed; }
.lgbox.root { border-color:var(--accent); }
svg .node rect { fill:var(--card); stroke:var(--line); stroke-width:1.3; }
svg .n-live rect { stroke:var(--ok); }
svg .n-hole rect { stroke:var(--bad); stroke-dasharray:5 3; }
svg .n-attack rect { stroke:var(--mid); }
svg .n-linch rect { stroke-width:2.6; }
svg .n-root rect { stroke:var(--accent); stroke-width:2; }
svg text { fill:var(--ink); font-size:12.5px; }
svg .nid { fill:var(--muted); font-weight:700; font-size:11px; }
svg .e-need { fill:none; stroke:var(--line); stroke-width:1.5; }
svg .e-attack { fill:none; stroke:var(--mid); stroke-width:1.8;
  stroke-dasharray:6 4; }
svg .e-ground { fill:none; stroke-width:1.2; stroke-dasharray:2 4;
  opacity:.6; }
svg .g-live { stroke:var(--ok); }
svg .g-so { stroke:var(--bad); }
svg .g-mid { stroke:var(--muted); }
svg .n-dead rect { stroke:var(--bad); stroke-width:2.6; }
svg .e-dead { stroke:var(--bad); stroke-width:2.2; opacity:1; }
.mapwrap a[data-id], .mapwrap path { transition:opacity .15s ease; }
.mapwrap .dim { opacity:.14; }
svg .schip rect { fill:var(--paper); stroke:var(--line); }
svg .schip.live rect { stroke:var(--ok); }
svg .schip.walled rect { stroke:var(--mid); }
svg .schip.so rect { stroke:var(--bad); }
svg .schip text { fill:var(--muted); font-size:11px; font-weight:700; }
.badge.linch { color:var(--ok); border-color:var(--ok); font-weight:700; }
.badge.attack { color:var(--mid); border-color:var(--mid); font-weight:700; }
table { border-collapse:collapse; width:100%; font-size:14px; }
th, td { text-align:left; padding:7px 10px; border-bottom:1px solid var(--line);
  vertical-align:top; }
th { font-size:11px; letter-spacing:.08em; text-transform:uppercase;
  color:var(--muted); }
td.mono, .mono { font-family:var(--mono); font-size:12.5px; }
blockquote { margin:6px 0 0; padding:2px 12px; border-left:3px solid var(--line);
  color:var(--muted); font-size:13.5px; font-style:italic; }
details { margin:28px 0; }
summary { cursor:pointer; font-weight:600; }
.trailbox { background:var(--card); border:1px solid var(--line);
  border-radius:6px; padding:10px 14px; font:12px/1.9 var(--mono);
  overflow-x:auto; margin-top:10px; }
.tline { white-space:nowrap; }
.tev { display:inline-block; min-width:104px; color:var(--accent);
  font-weight:700; }
.ledger { background:var(--card); border:2px solid var(--bad);
  border-radius:6px; padding:10px 16px; margin:14px 0; }
footer { margin-top:48px; color:var(--muted); font-size:12.5px;
  border-top:1px solid var(--line); padding-top:12px; }
#copytext, .ptext { position:absolute; left:-9999px; top:0; }
a { color:var(--accent); }
@media print {
  header.top { position:static; }
  #copybtn, .pcopy, nav.toc { display:none; }
  :root { --ink:#1a1613; --paper:#fff; --card:#fff; --line:#bbb;
    --muted:#555; }
  article.passage, .trailbox, .stat, .ledger { break-inside:avoid; }
}
"""

_JS = """
async function copyText(ta, btn, label) {
  try { await navigator.clipboard.writeText(ta.value); }
  catch (e) { ta.select(); document.execCommand('copy'); }
  btn.textContent = 'copied';
  setTimeout(() => { btn.textContent = label; }, 1400);
}
document.getElementById('copybtn').addEventListener('click', () =>
  copyText(document.getElementById('copytext'),
           document.getElementById('copybtn'), 'copy page as text'));
document.querySelectorAll('.pcopy').forEach(btn =>
  btn.addEventListener('click', () =>
    copyText(document.getElementById(btn.dataset.target), btn, 'copy')));

// hover layer: light a claim's full chain of custody, dim the rest
const map = document.querySelector('.mapwrap svg');
if (map) {
  const par = {}, kids = {};
  const edges = Array.from(map.querySelectorAll('path[data-kind]'));
  const grounds = edges.filter(e => e.dataset.kind === 'ground');
  edges.forEach(e => {
    if (e.dataset.kind === 'ground') return;
    (par[e.dataset.to] = par[e.dataset.to] || []).push(e.dataset.from);
    (kids[e.dataset.from] = kids[e.dataset.from] || []).push(e.dataset.to);
  });
  const items = Array.from(map.querySelectorAll('a[data-id]'));
  function walk(id, rel, s) {
    if (s.has(id)) return;
    s.add(id);
    (rel[id] || []).forEach(n => walk(n, rel, s));
  }
  function litSet(id, isChip) {
    const s = new Set();
    if (isChip) {
      s.add(id);
      grounds.forEach(g => {
        if (g.dataset.to === id) walk(g.dataset.from, par, s);
      });
    } else {
      walk(id, par, s);
      walk(id, kids, s);
    }
    grounds.forEach(g => { if (s.has(g.dataset.from)) s.add(g.dataset.to); });
    return s;
  }
  function apply(s) {
    items.forEach(el => el.classList.toggle('dim', !s.has(el.dataset.id)));
    edges.forEach(e => e.classList.toggle('dim',
      !(s.has(e.dataset.from) && s.has(e.dataset.to))));
  }
  function clear() {
    items.forEach(el => el.classList.remove('dim'));
    edges.forEach(e => e.classList.remove('dim'));
  }
  items.forEach(el => {
    el.addEventListener('mouseenter', () =>
      apply(litSet(el.dataset.id, el.classList.contains('mapchip'))));
    el.addEventListener('mouseleave', clear);
  });
}
"""


def _esc(s):
    return html.escape(str(s), quote=True)


_BADGE_CLS = {"LIVE": "live", "DEAD": "dead", "SAYS_OTHERWISE": "so",
              "WALLED": "walled"}


def _grade_badges(state, cid):
    # each grounding badge links to its source row; quote rides as a tooltip
    out = []
    for e in ground_edges(state, cid):
        g = latest_grade(state, e["source"]) or "ungraded"
        cls = _BADGE_CLS.get(g, "dead")
        tip = (' title="%s"' % _esc(e["quote"])) if e.get("quote") else ""
        out.append('<a class="badge %s" href="#src-%s"%s>%s @ %s: %s</a>'
                   % (cls, _esc(e["source"]), tip, _esc(e["source"]),
                      _esc(e["locator"]), _esc(g)))
    for h in state["holes"]:
        if h["claim"] == cid:
            why = h["why"] if len(h["why"]) <= 60 else h["why"][:57] + "..."
            out.append('<span class="badge hole" title="%s">HOLE: %s</span>'
                       % (_esc(h["why"]), _esc(why)))
    src = _contradicted(state, cid)
    if src:
        out.append('<a class="badge so" href="#src-%s">%s says otherwise</a>'
                   % (_esc(src), _esc(src)))
    return "".join(out)


def _tree_html(state, cid, is_attack=False):
    # claim text on one line, badges on their own row beneath: scannable,
    # and long badge sets can no longer break mid-sentence
    lp = state["linchpin"][-1] if state["linchpin"] else None
    badges = ""
    if is_attack:
        badges += '<span class="badge attack">ATTACK</span>'
    if cid == lp:
        badges += '<span class="badge linch">LINCHPIN</span>'
    badges += _grade_badges(state, cid)
    kids = "".join(_tree_html(state, k) for k in need_children(state, cid))
    kids += "".join(_tree_html(state, a, True) for a in attackers_of(state, cid))
    sub = "<ul>%s</ul>" % kids if kids else ""
    brow = ('<div class="badge-row">%s</div>' % badges) if badges else ""
    return ('<li id="claim-%s"><div class="claim-line">'
            '<span class="cid">%s</span> %s</div>%s%s</li>'
            % (_esc(cid), _esc(cid), _esc(node(state, cid)["text"]), brow, sub))


def _tree_text(state, cid, indent=0, is_attack=False):
    lp = state["linchpin"][-1] if state["linchpin"] else None
    marks = []
    if is_attack:
        marks.append("ATTACK")
    if cid == lp:
        marks.append("LINCHPIN")
    for e in ground_edges(state, cid):
        marks.append("%s @ %s: %s" % (e["source"], e["locator"],
                                      latest_grade(state, e["source"]) or "ungraded"))
    for h in state["holes"]:
        if h["claim"] == cid:
            marks.append("HOLE: %s" % h["why"])
    line = "%s- %s %s%s" % ("  " * indent, cid, node(state, cid)["text"],
                            ("  [" + "; ".join(marks) + "]") if marks else "")
    lines = [line]
    for k in need_children(state, cid):
        lines += _tree_text(state, k, indent + 1)
    for a in attackers_of(state, cid):
        lines += _tree_text(state, a, indent + 1, True)
    return lines


def _svg_parts(state, links=True):
    """Shared SVG body builder for the argument map. Status is never
    color alone: dash patterns, worded labels, tooltips, and the legend
    carry it too. Returns (width, height, body). With links=True, nodes
    and chips wrap in <a> anchors into the #claim-x / #src-x custody
    anchors; either way they carry data-id / data-kind attributes so the
    hover layer can light a claim's full chain of custody."""
    if not state["nodes"]:
        return 0, 0, ""
    root = state["nodes"][0]["id"]
    layer, order, queue = {root: 0}, [root], [root]
    kids_of = {}
    while queue:
        c = queue.pop(0)
        kids = need_children(state, c) + attackers_of(state, c)
        kids_of[c] = kids
        for k in kids:
            if k not in layer:
                layer[k] = layer[c] + 1
                order.append(k)
                queue.append(k)
    depth = max(layer.values()) + 1
    layers = [[c for c in order if layer[c] == i] for i in range(depth)]
    NW, NH, GX, GY = 196, 58, 14, 62
    width = max(len(l) for l in layers) * (NW + GX) + GX
    src_y = 16 + depth * (NH + GY)
    height = src_y + 46
    pos = {}
    for i, l in enumerate(layers):
        total = len(l) * (NW + GX) - GX
        x0 = (width - total) / 2.0
        for j, c in enumerate(l):
            pos[c] = (x0 + j * (NW + GX), 16 + i * (NH + GY))
    spos = {}
    ns = max(len(state["sources"]), 1)
    for j, s in enumerate(state["sources"]):
        spos[s["id"]] = ((j + 0.5) * width / ns, src_y)
    # kill path: on a BROKEN graph, the dead claim and its chain up to
    # the root render loud, so the cause of death reads as geometry
    res = try_close(state)
    dead_path, dead_edges = set(), set()
    if res[0] == "BROKEN":
        need_par = {e["dst"]: e["src"] for e in state["edges"]
                    if e["kind"] == "need"}
        cur = res[1]
        dead_path.add(cur)
        while cur in need_par:
            dead_edges.add((need_par[cur], cur))
            dead_path.add(need_par[cur])
            cur = need_par[cur]
    parts = []
    attack_pairs = {(e["src"], e["dst"]) for e in state["edges"]
                    if e["kind"] == "attack"}
    for c, kids in kids_of.items():
        for k in kids:
            x1, y1 = pos[c][0] + NW / 2, pos[c][1] + NH
            x2, y2 = pos[k][0] + NW / 2, pos[k][1]
            atk = (c, k) in attack_pairs
            cls = "e-attack" if atk else "e-need"
            if (c, k) in dead_edges:
                cls += " e-dead"
            rel = "is attacked by" if atk else "needs"
            parts.append('<path d="M%.0f %.0f C %.0f %.0f, %.0f %.0f, '
                         '%.0f %.0f" class="%s" data-kind="%s" '
                         'data-from="%s" data-to="%s">'
                         '<title>%s %s %s</title></path>'
                         % (x1, y1, x1, y1 + 22, x2, y2 - 22, x2, y2, cls,
                            "attack" if atk else "need", _esc(c), _esc(k),
                            _esc(c), rel, _esc(k)))
    for e in state["edges"]:
        if e["kind"] != "ground":
            continue
        if e["claim"] not in pos or e["source"] not in spos:
            continue
        x1, y1 = pos[e["claim"]][0] + NW / 2, pos[e["claim"]][1] + NH
        x2, y2 = spos[e["source"]]
        g = latest_grade(state, e["source"])
        gcls = ("g-live" if g == "LIVE" else
                "g-so" if g == "SAYS_OTHERWISE" else "g-mid")
        tip = "%s grounds %s @ %s [%s]" % (e["source"], e["claim"],
                                           e["locator"], g or "ungraded")
        if e.get("quote"):
            tip += ' :: "%s"' % e["quote"]
        parts.append('<path d="M%.0f %.0f C %.0f %.0f, %.0f %.0f, '
                     '%.0f %.0f" class="e-ground %s" data-kind="ground" '
                     'data-from="%s" data-to="%s"><title>%s</title></path>'
                     % (x1, y1, x1, y1 + 26, x2, y2 - 30, x2, y2 - 10, gcls,
                        _esc(e["claim"]), _esc(e["source"]), _esc(tip)))
    holed = {h["claim"] for h in state["holes"]}
    lp = state["linchpin"][-1] if state["linchpin"] else None
    attack_nodes = {d for _, d in attack_pairs}
    for c in order:
        x, y = pos[c]
        cls = "node"
        if c == root:
            cls += " n-root"
        if c in attack_nodes:
            cls += " n-attack"
        if c == lp:
            cls += " n-linch"
        if c in holed:
            cls += " n-hole"
        elif _live_grounded(state, c):
            cls += " n-live"
        text = node(state, c)["text"]
        ws, l1 = text.split(), ""
        while ws and len(l1) + len(ws[0]) + 1 <= 25:
            l1 += ("" if not l1 else " ") + ws.pop(0)
        l2 = " ".join(ws)
        if len(l2) > 23:
            l2 = l2[:20] + "..."
        tag = (" ATTACK" if c in attack_nodes else "") + \
              (" LINCHPIN" if c == lp else "") + \
              (" HOLE" if c in holed else "") + \
              (" DEAD" if c in dead_path and c not in holed else "")
        if c in dead_path:
            cls += " n-dead"
        body = ('<g class="%s"><title>%s</title>'
                '<rect x="%.0f" y="%.0f" width="%d" height="%d" rx="6"/>'
                '<text x="%.0f" y="%.0f"><tspan class="nid">%s%s</tspan>'
                '</text><text x="%.0f" y="%.0f">%s</text>'
                '<text x="%.0f" y="%.0f">%s</text></g>'
                % (cls, _esc(text), x, y, NW, NH, x + 9, y + 16,
                   _esc(c), _esc(tag), x + 9, y + 32, _esc(l1), x + 9,
                   y + 47, _esc(l2)))
        if links:
            parts.append('<a href="#claim-%s" class="mapnode" data-id="%s">'
                         '%s</a>' % (_esc(c), _esc(c), body))
        else:
            parts.append(body)
    for s in state["sources"]:
        x, y = spos[s["id"]]
        g = (latest_grade(state, s["id"]) or "ungraded").lower()
        gcls = {"live": "live", "walled": "walled",
                "says_otherwise": "so"}.get(g, "dead")
        body = ('<g class="schip %s"><title>%s [%s]</title>'
                '<rect x="%.0f" y="%.0f" width="52" height="24" rx="12"/>'
                '<text x="%.0f" y="%.0f" text-anchor="middle">%s</text></g>'
                % (gcls, _esc(s["ref"]), g.upper(), x - 26, y, x, y + 16,
                   _esc(s["id"])))
        if links:
            parts.append('<a href="#src-%s" class="mapchip" data-id="%s">'
                         '%s</a>' % (_esc(s["id"]), _esc(s["id"]), body))
        else:
            parts.append(body)
    return width, height, "".join(parts)


def _svg_map(state):
    """The in-report argument map: shared parts + worded legend."""
    width, height, body = _svg_parts(state, links=True)
    if not body:
        return ""
    legend = ('<div class="map-legend">'
              '<span><span class="lg"></span>needs</span>'
              '<span><span class="lg atk"></span>attacks</span>'
              '<span><span class="lg grd"></span>grounded in</span>'
              '<span><span class="lgbox root"></span>hypothesis</span>'
              '<span><span class="lgbox"></span>live-grounded</span>'
              '<span><span class="lgbox hole"></span>hole</span>'
              '<span>chips: sources (hover to light a chain, click to '
              'walk it)</span></div>')
    # natural pixel size, never scaled down: the column is 76ch but the
    # map breaks out full-bleed and scrolls instead of shrinking its type
    return ('<div class="mapwrap"><svg viewBox="0 0 %d %d" '
            'style="width:%dpx" role="img" aria-label="argument map">'
            '%s</svg></div>%s'
            % (width, height, width, body, legend))


# Standalone export palette: FogSift-family status colors re-stepped for
# a warm paper surface (all >= 4.5:1 on #faf8f3), since the report's CSS
# variables do not travel with a bare .svg file.
_MAP_LIGHT_CSS = """
 text { fill:#3a312b; font-size:12.5px; }
 .nid { fill:#7a6b5d; font-weight:700; font-size:11px; }
 .node rect { fill:#ffffff; stroke:#b8a88a; stroke-width:1.3; }
 .n-live rect { stroke:#0f766e; }
 .n-hole rect { stroke:#bd2436; stroke-dasharray:5 3; }
 .n-attack rect { stroke:#b45309; }
 .n-linch rect { stroke-width:2.6; }
 .n-root rect { stroke:#c2410c; stroke-width:2; }
 .n-dead rect { stroke:#bd2436; stroke-width:2.6; }
 .e-need { fill:none; stroke:#b8a88a; stroke-width:1.5; }
 .e-attack { fill:none; stroke:#b45309; stroke-width:1.8;
   stroke-dasharray:6 4; }
 .e-dead { stroke:#bd2436; stroke-width:2.2; }
 .e-ground { fill:none; stroke-width:1.2; stroke-dasharray:2 4;
   opacity:.7; }
 .g-live { stroke:#0f766e; }
 .g-so { stroke:#bd2436; }
 .g-mid { stroke:#7a6b5d; }
 .schip rect { fill:#faf8f3; stroke:#b8a88a; }
 .schip.live rect { stroke:#0f766e; }
 .schip.walled rect { stroke:#b45309; }
 .schip.so rect { stroke:#bd2436; }
 .schip text { fill:#7a6b5d; font-size:11px; font-weight:700; }
 .maplegend { fill:#7a6b5d; font-size:11px; }
"""


def map_svg_standalone(state):
    """Print-ready standalone map: light palette, no anchors, legend as
    an in-SVG text row. Drops into a document or slide as-is."""
    width, height, body = _svg_parts(state, links=False)
    if not body:
        return ""
    legend = ('<text x="12" y="%d" class="maplegend">solid: needs / '
              'dashed: attacks / dotted: grounded in / chips: sources / '
              'labels: ATTACK, LINCHPIN, HOLE, DEAD</text>' % (height + 16))
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" '
            'font-family="ui-monospace,Menlo,Consolas,monospace">'
            '<style>%s</style><rect width="100%%" height="100%%" '
            'fill="#faf8f3"/>%s%s</svg>'
            % (width, height + 30, _MAP_LIGHT_CSS, body, legend))


def to_argdown(state):
    """Export the graph as Argdown (export only, no round-trip).
    NUANCE, documented: Argdown's '+' means support; claimground's need
    edge means NECESSARY CONDITION. '-' matches attack exactly."""
    root = state["nodes"][0]
    holed = {h["claim"] for h in state["holes"]}
    lp = state["linchpin"][-1] if state["linchpin"] else None
    lines = ["===",
             "title: %s" % json.dumps(root["text"][:80]),
             "subTitle: claimground v%s export, verdict %s"
             % (VERSION, verdict(state)),
             "===", "",
             "/* Export only. Argdown's '+' means support; claimground's",
             "   need edge means NECESSARY CONDITION. '-' = attack, exact",
             "   match. Source receipts ride in {braces} metadata. */", ""]

    def meta(cid):
        gs = ground_edges(state, cid)
        if not gs:
            return ""
        rs = ", ".join('"%s @ %s [%s]"'
                       % (e["source"], e["locator"],
                          latest_grade(state, e["source"]) or "ungraded")
                       for e in gs)
        return " {sources: [%s]}" % rs

    def tags(cid):
        t = ""
        if cid == lp:
            t += " #linchpin"
        if cid in holed:
            t += " #hole"
        if cid in state["leaves"]:
            t += " #leaf"
        return t

    def emit(cid, depth, marker):
        pad = "  " * depth
        lines.append("%s%s[%s]: %s%s%s"
                     % (pad, marker, cid, node(state, cid)["text"],
                        tags(cid), meta(cid)))
        for k in need_children(state, cid):
            emit(k, depth + 1, "+ ")
        for a in attackers_of(state, cid):
            emit(a, depth + 1, "- ")

    emit(root["id"], 0, "")
    return "\n".join(lines) + "\n"


def render(state, out_path):
    v = verdict(state)
    vclass = v.split("(")[0]
    close_res = try_close(state)
    root = state["nodes"][0] if state["nodes"] else {"id": "?", "text": "(empty)"}
    meta = state.get("meta") or {}
    stamp = meta.get("date") or date.today().isoformat()
    title = meta.get("title") or root["text"]

    # --- stats strip ---
    leaves_all = [n["id"] for n in state["nodes"]
                  if not need_children(state, n["id"])]
    live_leaves = [c for c in leaves_all if _live_grounded(state, c)]
    gcounts = {}
    for s in state["sources"]:
        g = latest_grade(state, s["id"]) or "ungraded"
        gcounts[g] = gcounts.get(g, 0) + 1
    att_edges = [e for e in state["edges"] if e["kind"] == "attack"]
    obj_answered = sum(1 for e in att_edges
                       if fully_grounded(state, e["dst"])
                       and fully_grounded(state, e["src"]))
    lp = state["linchpin"][-1] if state["linchpin"] else None
    lp_status = ("held" if lp and _live_grounded(state, lp)
                 else "bare" if lp else "unset")
    stats = [("%d/%d" % (len(live_leaves), len(leaves_all)), "leaves live"),
             (str(len(state["holes"])), "holes"),
             (" ".join("%d %s" % (n, g) for g, n in sorted(gcounts.items())),
              "sources"),
             ("%d/%d" % (obj_answered, len(att_edges)), "objections answered"),
             (lp_status, "linchpin")]
    stats_html = '<div class="stats">%s</div>' % "".join(
        "<div class='stat'><b>%s</b><span>%s</span></div>" % (_esc(v), _esc(l))
        for v, l in stats)
    stats_txt = "; ".join("%s %s" % (v, l) for v, l in stats)

    # --- passages ---
    passages_html, passages_txt, ptas = [], [], []
    for b in state["bindings"]:
        sp = next(s for s in state["specs"] if s["id"] == b["spec"])
        text = latest_prose(state, b["address"]) or ""
        status = ("accepted" if sp["id"] in state["done"] else "draft")
        cls = sp["label"].replace(" ", "-") if sp["label"] in ("objection", "linchpin") else ""
        paras = "".join("<p>%s</p>" % _esc(p)
                        for p in re.split(r"\n\s*\n", text) if p.strip())
        # custody: every passage carries its receipts inline
        rec_html, rec_txt = [], []
        for cid in sp["claims"]:
            for e in ground_edges(state, cid):
                grec = latest_grade_rec(state, e["source"])
                stampd = (" " + grec["date"]) if grec.get("date") else ""
                rec_html.append("<b><a href='#claim-%s'>%s</a></b> &larr; "
                                "<a href='#src-%s'>%s</a> @ %s [%s%s]"
                                % (_esc(cid), _esc(cid), _esc(e["source"]),
                                   _esc(e["source"]), _esc(e["locator"]),
                                   _esc(grec.get("grade", "ungraded")), stampd))
                rec_txt.append("  %s <- %s @ %s [%s%s]"
                               % (cid, e["source"], e["locator"],
                                  grec.get("grade", "ungraded"), stampd))
            for h in state["holes"]:
                if h["claim"] == cid:
                    rec_html.append("<b><a href='#claim-%s'>%s</a></b> "
                                    "&larr; HOLE: %s"
                                    % (_esc(cid), _esc(cid), _esc(h["why"])))
                    rec_txt.append("  %s <- HOLE: %s" % (cid, h["why"]))
        receipts = ('<div class="receipts">%s</div>' % "<br>".join(rec_html)
                    if rec_html else "")
        head = "%s · %s · %s" % (sp["id"], sp["label"], status)
        pta_id = "pt-%s" % sp["id"]
        ptas.append((pta_id, "\n".join(["[%s]" % head, text]
                                       + (["receipts:"] + rec_txt
                                          if rec_txt else []))))
        passages_html.append(
            '<article class="passage %s" id="passage-%s">'
            '<button class="pcopy" data-target="%s">copy</button>'
            '<h3>%s</h3>%s%s</article>'
            % (cls, _esc(sp["id"]), pta_id, _esc(head), paras, receipts))
        passages_txt += ["[%s]" % head, text]
        if rec_txt:
            passages_txt += ["receipts:"] + rec_txt
        passages_txt.append("")
    if not passages_html:
        note = "No prose. The run ended in phase 1, before composition."
        passages_html = ["<p>%s</p>" % note]
        passages_txt = [note, ""]

    # --- objections ---
    obj_html, obj_txt = [], []
    for e in state["edges"]:
        if e["kind"] != "attack":
            continue
        target, attacker = e["src"], e["dst"]
        fg_a = fully_grounded(state, attacker)
        fg_t = fully_grounded(state, target)
        status = ("STANDS, unanswered" if fg_a and not fg_t else
                  "grounded and answered" if fg_a else "not yet grounded")
        obj_html.append("<li><a class='cid' href='#claim-%s'>%s</a> %s "
                        "<span class='badge %s'>%s</span> "
                        "(against <a href='#claim-%s'>%s</a>)</li>"
                        % (_esc(attacker), _esc(attacker),
                           _esc(node(state, attacker)["text"]),
                           "so" if "STANDS" in status else "live", _esc(status),
                           _esc(target), _esc(target)))
        obj_txt.append("- %s %s [%s] (against %s)"
                       % (attacker, node(state, attacker)["text"], status, target))
    if not obj_html:
        obj_html = ["<li>No objections were registered. That is itself a finding: "
                    "the strongest case against was never written down.</li>"]
        obj_txt = ["(none registered)"]

    # --- sources ---
    src_rows, src_txt = [], []
    for s in state["sources"]:
        g = latest_grade(state, s["id"]) or "ungraded"
        ref = ('<a href="%s">%s</a>' % (_esc(s["url"]), _esc(s["ref"]))
               if s.get("url") else _esc(s["ref"]))
        atts_html, atts_txt = [], []
        for e in state["edges"]:
            if e.get("kind") == "ground" and e.get("source") == s["id"]:
                q = (' <blockquote>"%s"</blockquote>' % _esc(e["quote"])
                     if e.get("quote") else "")
                atts_html.append("<a href='#claim-%s'>%s</a> @ %s%s"
                                 % (_esc(e["claim"]), _esc(e["claim"]),
                                    _esc(e["locator"]), q))
                atts_txt.append("%s @ %s%s"
                                % (e["claim"], e["locator"],
                                   (' :: "%s"' % e["quote"]) if e.get("quote") else ""))
        cls = _BADGE_CLS.get(g, "dead")
        grec = latest_grade_rec(state, s["id"])
        gcell = "<span class='badge %s'>%s</span>" % (cls, _esc(g))
        if grec.get("date"):
            gcell += "<span class='gdate'>graded %s</span>" % _esc(grec["date"])
        if grec.get("note"):
            gcell += "<span class='gdate'>%s</span>" % _esc(grec["note"])
        src_rows.append("<tr id='src-%s'><td class='mono'>%s</td><td>%s</td>"
                        "<td>%s</td><td>%s</td></tr>"
                        % (_esc(s["id"]), _esc(s["id"]), ref, gcell,
                           "<br>".join(atts_html) or "not attached"))
        gtxt = g + ((", graded " + grec["date"]) if grec.get("date") else "")
        if grec.get("note"):
            gtxt += "; " + grec["note"]
        src_txt.append("%s. %s [%s]%s" % (s["id"], s["ref"] +
                       ((" <" + s["url"] + ">") if s.get("url") else ""), gtxt,
                       ("\n    " + "\n    ".join(atts_txt)) if atts_txt else ""))

    # --- dead-claim ledger ---
    ledger_html = ledger_txt = ""
    if close_res[0] == "BROKEN":
        cid, cause = close_res[1], close_res[2]
        detail = []
        for g in state["grades"]:
            if g["grade"] == "SAYS_OTHERWISE" and g.get("claim") == cid:
                detail.append("source %s says otherwise%s"
                              % (g["source"],
                                 (': "%s"' % g["quote"]) if g.get("quote") else ""))
        for h in state["holes"]:
            if h["claim"] == cid:
                detail.append("declared hole: %s" % h["why"])
        ledger_html = ('<div class="ledger"><strong>Dead claim:</strong> '
                       '<a class="cid" href="#claim-%s">%s</a> %s'
                       '<br><strong>Cause:</strong> %s'
                       % (_esc(cid), _esc(cid),
                          _esc(node(state, cid)["text"]), _esc(cause)))
        ledger_html += "".join("<br>%s" % _esc(d) for d in detail) + "</div>"
        ledger_txt = ("DEAD CLAIM: %s %s\nCAUSE: %s\n%s"
                      % (cid, node(state, cid)["text"], cause, "\n".join(detail)))

    # --- trail ---
    trail_lines = ["  ".join("%s=%s" % kv for kv in t.items())
                   for t in state["trail"]]
    trail_html = "".join(
        "<div class='tline'><span class='tev'>%s</span>%s</div>"
        % (_esc(t.get("event", "?")),
           _esc("  ".join("%s=%s" % kv for kv in t.items()
                          if kv[0] != "event")))
        for t in state["trail"])

    # --- verdict sentence ---
    vmap = {"SUPPORTED": "The graph closed: every claim is grounded in a live "
                         "source at a named locator, the objections are grounded "
                         "and answered, and the linchpin holds.",
            "UNDECIDED": "The graph has not closed and has not broken. The burden "
                         "of proof is not yet carried either way.",
            "REFUTED": "The graph broke before any prose was written. Refutation "
                       "here costs research, never a manuscript."}
    vsent = vmap[vclass]
    if close_res[0] == "OPEN" and close_res[1]:
        vsent += " Still floating: %s." % ", ".join(close_res[1])

    tree_html = ("<ul class='tree'>%s</ul>" % _tree_html(state, root["id"])
                 if state["nodes"] else "")
    tree_txt = "\n".join(_tree_text(state, root["id"])) if state["nodes"] else ""

    # --- plain text version (the copy target) ---
    txt = "\n".join([
        "CLAIMGROUND REPORT  (claimground v%s)" % VERSION,
        "Hypothesis: %s" % root["text"],
        "Verdict: %s" % v,
        "Date: %s" % stamp,
        "Status: %s" % stats_txt, "",
        "== VERDICT ==", vsent] +
        ([ledger_txt, ""] if ledger_txt else [""]) + [
        "== THE WORK =="] + passages_txt + [
        "== THE ARGUMENT ==", tree_txt, "",
        "== OBJECTIONS =="] + obj_txt + ["",
        "== SOURCES =="] + src_txt + ["",
        "== TRAIL =="] + trail_lines + ["",
        "Method: claim graph first, prose second. Every claim above traces "
        "to a source at a named locator or is flagged as a hole. "
        "github.com/ctavolazzi/claimground"])

    page = "\n".join([
        "<!-- claimground report v%s -->" % VERSION,
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<title>claimground: %s</title>" % _esc(title[:70]),
        "<style>%s</style></head><body>" % _CSS,
        "<header class='top'><div class='brand'>CLAIMGROUND</div>",
        "<div class='chip %s'>%s</div>" % (vclass, _esc(v)),
        "<nav class='toc'><a href='#sec-verdict'>verdict</a>"
        "<a href='#sec-work'>work</a><a href='#sec-argument'>argument</a>"
        "<a href='#sec-objections'>objections</a>"
        "<a href='#sec-sources'>sources</a><a href='#sec-trail'>trail</a></nav>",
        "<button id='copybtn'>copy page as text</button></header>",
        "<main>",
        "<section><p class='meta'>hypothesis</p><h1>%s</h1>" % _esc(root["text"]),
        "<p class='meta'>%s · %d claims · %d sources · %d trail events</p>"
        % (stamp, len(state["nodes"]), len(state["sources"]), len(state["trail"])),
        stats_html, "</section>",
        "<section id='sec-verdict'><h2>Verdict</h2>"
        "<p class='verdict-line'>%s</p><p>%s</p>%s</section>"
        % (_esc(v), _esc(vsent), ledger_html),
        "<section id='sec-work'><h2>The work</h2>%s</section>"
        % "".join(passages_html),
        "<section id='sec-argument'><h2>The argument</h2>%s%s</section>"
        % (_svg_map(state), tree_html),
        "<section id='sec-objections'><h2>Objections</h2><ul class='tree'>%s</ul>"
        "</section>" % "".join(obj_html),
        "<section id='sec-sources'><h2>Sources</h2><table><tr><th>id</th>"
        "<th>source</th><th>grade</th><th>attached to</th></tr>%s</table>"
        "</section>" % "".join(src_rows),
        "<details id='sec-trail'><summary>Trail (%d events)</summary>"
        "<div class='trailbox'>%s</div></details>"
        % (len(trail_lines), trail_html),
        "<footer>claim graph first, prose second. The verdict was settled by "
        "the graph before any prose existed; the prose answers to it. "
        "Generated by <a href='https://github.com/ctavolazzi/claimground'>"
        "claimground</a> v%s.</footer>" % VERSION,
        "</main>",
        "<textarea id='copytext' readonly>%s</textarea>" % _esc(txt),
        "".join("<textarea class='ptext' id='%s' readonly>%s</textarea>"
                % (_esc(pid), _esc(pt)) for pid, pt in ptas),
        "<script>%s</script>" % _JS,
        "</body></html>"])

    Path(out_path).write_text(page, encoding="utf-8")
    return out_path


# =====================================================================
# CLI
# =====================================================================

def _load(path):
    state = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("nodes", "edges", "sources", "grades", "holes", "linchpin",
                "leaves", "specs", "bindings", "prose", "trail", "done"):
        state.setdefault(key, [])
    return state


def _save(path, state):
    Path(path).write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")


def _out(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 1
    cmd, path = argv[1], argv[2]
    state = _load(path)
    rest = argv[3:]

    if cmd == "validate":
        checks = validate(state)
        _out({"ok": all(c["ok"] for c in checks), "checks": checks})
    elif cmd == "close":
        res = try_close(state)
        if res[0] == "BROKEN" and "--record" in rest:
            already = any(t.get("event") == "verdict" for t in state["trail"])
            if not already:
                record_refuted(state, res[1], res[2])
                _save(path, state)
        _out({"state": res[0], "detail": list(res[1:])})
    elif cmd == "plan":
        if state["specs"]:
            _out({"error": "already planned"})
            return 1
        if try_close(state)[0] != "CLOSED":
            _out({"error": "graph is not CLOSED; phase 2 is unreachable"})
            return 1
        specs = plan_passages(state)
        if "--apply" in rest:
            materialize(state, specs)
            _save(path, state)
        _out({"applied": "--apply" in rest, "specs": specs})
    elif cmd == "fill":
        spec_id, prose_file = rest[0], rest[1]
        fill(state, spec_id, Path(prose_file).read_text(encoding="utf-8").strip())
        _save(path, state)
        _out({"filled": spec_id})
    elif cmd == "check":
        spec_id = rest[0]
        sp = next(s for s in state["specs"] if s["id"] == spec_id)
        text = latest_prose(state, _address_of(state, spec_id))
        recs = mechanical(state, text, sp["target"])
        found = extract(text)
        unmapped = map_claims(state, found, sp["claims"])
        ok = all(r["ok"] for r in recs) and not unmapped
        if ok and "--accept" in rest and spec_id not in state["done"]:
            state["done"].append(spec_id)
            state["trail"].append({"event": "spec_done", "spec": spec_id,
                                   "checks": len(recs), "extracted": len(found)})
            _save(path, state)
        _out({"ok": ok, "records": recs, "extracted": len(found),
              "unmapped": unmapped,
              "accepted": ok and "--accept" in rest})
    elif cmd == "verdict":
        _out({"verdict": verdict(state)})
    elif cmd == "render":
        out = render(state, rest[0])
        _out({"written": str(out), "verdict": verdict(state)})
    elif cmd == "argdown":
        Path(rest[0]).write_text(to_argdown(state), encoding="utf-8")
        _out({"written": rest[0], "note": "export only; '+' means support "
              "in Argdown but necessary-condition in claimground"})
    elif cmd == "map":
        Path(rest[0]).write_text(map_svg_standalone(state), encoding="utf-8")
        _out({"written": rest[0], "note": "standalone light-palette SVG, "
              "print-ready"})
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
