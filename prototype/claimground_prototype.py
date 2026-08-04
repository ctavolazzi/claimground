#!/usr/bin/env python3
"""claimground LOGIC PROTOTYPE. Throwaway.

QUESTION: does the two-phase claim-graph model feel right when driven by hand?
  (a) does grounding-before-prose flow naturally or fight the author?
  (b) does try_close fire BROKEN at the right moments?
  (c) is one-question-at-a-time bearable?
  (d) does the extract-and-map check on prose feel like a real gate or a nuisance?

Run: python3 claimground_prototype.py
Keys: [h] hypothesis [s] source [d] decompose next [g] ground next
      [c] try_close [p] plan [f] fill [k] check fill [x] demo seed
      [t] trail [q] quit

Build rules (prototype skill): stdlib only, single file, memory-only state
(no persistence), FETCH stubbed as a y/n question, no tests, no error
handling beyond runnable, throwaway. The LOGIC section is pure (no I/O);
the TUI section owns every input()/print(). ASK lives in the TUI; logic
functions take answers as arguments. All writes are appends to state
lists; nothing is edited or deleted, latest record wins.
"""

import re

# =====================================================================
# LOGIC  (portable, pure, no I/O)
# =====================================================================

BANNED = ["\u2014", "man" "ifesto"]  # escaped/split: this source never
                                     # contains its own banned strings
MAP_THRESHOLD = 0.6
WORD_TOL = (0.5, 1.6)

STOP = set("""the a an and or of for to in on with is are was were it its
this that who which as at by be but not from over under across their our
your my we you they he she""".split())

ASSERT_STEMS = {"caus", "reduc", "worsen", "increas", "improv", "study",
                "studi", "show", "found", "percent", "accord", "lead",
                "led", "suggest"}


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


def new_state():
    return {"nodes": [], "edges": [], "sources": [], "grades": [],
            "holes": [], "linchpin": [], "leaves": [], "specs": [],
            "bindings": [], "prose": [], "trail": [], "done": []}


# ---- graph writes (append only) ----

def intake(state, text, reader_can_disagree):
    t = text.strip()
    if not t:
        return "REFUSED", "nothing given"
    if "\n" in t:
        return "REFUSED", "one sentence only"
    if len(t) > 300:
        return "REFUSED", "too long to be one claim"
    if not reader_can_disagree:
        return "REFUSED", "topic, not claim"
    cid = "c%d" % (len(state["nodes"]) + 1)
    state["nodes"].append({"id": cid, "text": t})
    state["trail"].append({"event": "intake", "claim": cid, "text": t})
    return "OK", cid


def add_source(state, ref, bears_on):
    sid = "s%d" % (len(state["sources"]) + 1)
    state["sources"].append({"id": sid, "ref": ref, "bears_on": bears_on})
    state["trail"].append({"event": "source", "source": sid, "ref": ref})
    return sid


def _add_claims(state, parent_id, texts, kind):
    ids = []
    for t in texts:
        cid = "c%d" % (len(state["nodes"]) + 1)
        state["nodes"].append({"id": cid, "text": t})
        state["edges"].append({"kind": kind, "src": parent_id, "dst": cid})
        state["trail"].append({"event": kind, "parent": parent_id,
                               "claim": cid, "text": t})
        ids.append(cid)
    return ids


def add_needs(state, claim_id, texts):
    return _add_claims(state, claim_id, texts, "need")


def add_attacks(state, claim_id, texts):
    return _add_claims(state, claim_id, texts, "attack")


def mark_leaf(state, claim_id):
    state["leaves"].append(claim_id)
    state["trail"].append({"event": "leaf", "claim": claim_id})


def mark_linchpin(state, claim_id):
    state["linchpin"].append(claim_id)
    state["trail"].append({"event": "linchpin", "claim": claim_id})


def attach(state, claim_id, source_id, locator):
    state["edges"].append({"kind": "ground", "claim": claim_id,
                           "source": source_id, "locator": locator})
    state["trail"].append({"event": "attach", "claim": claim_id,
                           "source": source_id, "locator": locator})


def grade_record(state, source_id, grade, claim_id=None):
    state["grades"].append({"source": source_id, "grade": grade,
                            "claim": claim_id})
    state["trail"].append({"event": "grade", "source": source_id,
                           "grade": grade, "claim": claim_id})


def work_across_record(state, source_id, claim_id, relation, locator=None):
    # ACH rule: evidence tests everything it touches, attacks included
    if relation == "support":
        attach(state, claim_id, source_id, locator)
    elif relation == "contradict":
        grade_record(state, source_id, "SAYS_OTHERWISE", claim_id)


def declare_hole(state, claim_id, why):
    state["holes"].append({"claim": claim_id, "why": why})
    state["trail"].append({"event": "hole", "claim": claim_id, "why": why})


def record_refuted(state, claim_id, cause):
    state["trail"].append({"event": "verdict", "verdict": "REFUTED",
                           "claim": claim_id, "cause": cause})


# ---- graph reads (pure) ----

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


def floating(state):
    # no need-edge out, no attached source, no declared hole
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


def candidates_for(state, claim_id):
    ct = tokens(node(state, claim_id)["text"])
    return [s for s in state["sources"] if tokens(s["bears_on"]) & ct]


# ---- stage 2: composition (pure) ----

def plan_passages(state):
    """Simple auto-cut: main line, one spec per attack subtree, linchpin
    alone. Every node lands in exactly one spec. Author reorders in TUI."""
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

    def add_spec(claims, register, label):
        claims = [c for c in claims if c not in taken]
        if not claims:
            return
        taken.update(claims)
        n_src = sum(len(ground_edges(state, c)) for c in claims)
        specs.append({"id": "p%d" % (len(specs) + 1), "claims": claims,
                      "register": register, "label": label,
                      "target": 12 * len(claims) + 5 * n_src})

    add_spec([n["id"] for n in state["nodes"]
              if n["id"] not in in_attack and n["id"] != lp],
             "argument", "main line")
    for sub in attack_subs:
        add_spec(sub, "argument", "objection")
    if lp:
        add_spec([lp], "argument", "linchpin")
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


def brief(state, spec, constraints):
    """Assembled fresh, never stored."""
    claims = []
    for cid in spec["claims"]:
        srcs = [{"ref": next(s["ref"] for s in state["sources"]
                             if s["id"] == e["source"]),
                 "locator": e["locator"]}
                for e in ground_edges(state, cid)]
        claims.append({"id": cid, "text": node(state, cid)["text"],
                       "sources": srcs})
    neighbors = [latest_prose(state, b["address"]) for b in state["bindings"]
                 if b["spec"] != spec["id"]]
    return {"claims": claims, "register": spec["register"],
            "target": spec["target"], "neighbors": neighbors,
            "constraints": constraints,
            "address": _address_of(state, spec["id"])}


def fill(state, spec_id, text):
    addr = _address_of(state, spec_id)
    state["prose"].append({"address": addr, "kind": "fill", "text": text})
    state["trail"].append({"event": "fill", "spec": spec_id,
                           "words": words(text)})


def mechanical(state, text, target):
    recs = []
    w = words(text)
    lo, hi = round(WORD_TOL[0] * target), round(WORD_TOL[1] * target)
    recs.append({"check": "words.in_range", "ok": lo <= w <= hi,
                 "detail": "%d words, band %d-%d" % (w, lo, hi)})
    hit = [b for b in BANNED if b in text]
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
    found = []
    for s in sents:
        assertive = (any(ch.isdigit() for ch in s) or '"' in s
                     or (tokens(s) & ASSERT_STEMS))
        if assertive:
            found.append(s)
    return found


def map_claims(state, found, claim_ids):
    """Normalized token-overlap MATCH. Returns the unmapped sentences."""
    unmapped = []
    for sent in found:
        st_toks = tokens(sent)
        hit = False
        for cid in claim_ids:
            ct = tokens(node(state, cid)["text"])
            if ct and len(ct & st_toks) / len(ct) >= MAP_THRESHOLD:
                hit = True
                break
        if not hit:
            unmapped.append(sent)
    return unmapped


def mark_done(state, spec_id, records, n_extracted):
    state["done"].append(spec_id)
    state["trail"].append({"event": "spec_done", "spec": spec_id,
                           "checks": len(records), "extracted": n_extracted})


def verdict(state):
    for t in state["trail"]:
        if t.get("event") == "verdict" and t.get("verdict") == "REFUTED":
            return "REFUTED(%s: %s)" % (t["claim"], t["cause"])
    if state["specs"] and all(sp["id"] in state["done"]
                              for sp in state["specs"]):
        return "SUPPORTED"
    return "UNDECIDED"


# ---- demo seed (logic-level; the standing-desk example) ----

def demo_seed(broken):
    st = new_state()
    _, c1 = intake(st, "Standing desks reduce back pain for office workers",
                   True)
    s1 = add_source(st, "Agarwal 2018 systematic review",
                    "standing desks back pain sitting office")
    s2 = add_source(st, "NIOSH posture guidance page",
                    "alternating posture standing spinal load")
    s3 = add_source(st, "ergonomics field report 2015",
                    "standing all day pain feet")
    c2, c3 = add_needs(st, c1, [
        "Prolonged sitting worsens back pain",
        "Alternating sitting and standing reduces spinal load"])
    (c4,) = add_attacks(st, c1, ["Standing all day causes its own pain"])
    for c in (c2, c3, c4):
        mark_leaf(st, c)
    mark_linchpin(st, c3)
    attach(st, c2, s1, "p.4, pooled effect")
    grade_record(st, s1, "LIVE")
    attach(st, c3, s2, "section 2, load table")
    if broken:
        grade_record(st, s2, "SAYS_OTHERWISE", c3)   # source says the opposite
    else:
        grade_record(st, s2, "LIVE")
    attach(st, c4, s3, "para 3")
    grade_record(st, s3, "LIVE")
    return st


# =====================================================================
# TUI  (throwaway shell; owns every input/print; ASK lives here)
# =====================================================================

CONSTRAINTS = {"banned": "the em dash; the m-word",
               "voice": "plain declarative; second person allowed"}


def _marks(st, cid):
    m = []
    if st["linchpin"] and st["linchpin"][-1] == cid:
        m.append("LINCHPIN")
    if cid in st["leaves"]:
        m.append("leaf")
    for h in st["holes"]:
        if h["claim"] == cid:
            m.append("HOLE(%s)" % h["why"])
    for e in ground_edges(st, cid):
        m.append("%s@%s:%s" % (e["source"], e["locator"],
                               latest_grade(st, e["source"]) or "ungraded"))
    src = _contradicted(st, cid)
    if src:
        m.append("SAYS_OTHERWISE<%s" % src)
    if cid in floating(st):
        m.append("FLOATING")
    return " [" + "; ".join(m) + "]" if m else ""


def _render_claim(st, cid, indent, tag):
    print("%s%s%s %s%s" % ("  " * indent, tag, cid,
                           node(st, cid)["text"], _marks(st, cid)))
    for k in need_children(st, cid):
        _render_claim(st, k, indent + 1, "")
    for a in attackers_of(st, cid):
        _render_claim(st, a, indent + 1, "!ATTACK ")


def render(st):
    print("\033[2J\033[H", end="")
    v = verdict(st)
    if v.startswith("REFUTED"):
        phase = "TERMINAL: " + v
    elif st["specs"]:
        phase = "PHASE 2: COMPOSE (graph is closed; prose answers to it)"
    else:
        phase = "PHASE 1: GRAPH (no prose until the graph closes)"
    print("== claimground prototype ==  %s" % phase)
    print()
    if st["nodes"]:
        _render_claim(st, st["nodes"][0]["id"], 0, "")
    else:
        print("(no hypothesis yet; press h, or x for the demo seed)")
    print()
    res = try_close(st)
    if res[0] == "OPEN":
        detail = ", ".join(res[1]) if res[1] else "no claims yet"
        print("close-state: OPEN (floating: %s)" % detail)
    elif res[0] == "BROKEN":
        print("close-state: BROKEN(%s, %s)" % (res[1], res[2]))
    else:
        print("close-state: CLOSED")
    if st["sources"]:
        print("sources: " + "; ".join(
            "%s=%s" % (s["id"], s["ref"]) for s in st["sources"]))
    if st["specs"]:
        parts = []
        for sp in st["specs"]:
            state_str = ("done" if sp["id"] in st["done"] else
                         "filled" if any(p["kind"] == "fill" and
                                         p["address"] == _address_of(st, sp["id"])
                                         for p in st["prose"]) else "stub")
            parts.append("%s(%s:%s)" % (sp["id"], sp["label"], state_str))
        print("passages: " + "  ".join(parts))
    if st["trail"]:
        print("trail tail:")
        for t in st["trail"][-4:]:
            print("  " + ", ".join("%s=%s" % kv for kv in t.items()))
    print()
    print("[h]ypothesis [s]ource [d]ecompose [g]round [c]lose [p]lan "
          "[f]ill [k]check [x]seed [t]rail [q]uit")


def read_prose():
    print("prose (end with a blank line):")
    lines = []
    while True:
        ln = input()
        if not ln.strip():
            break
        lines.append(ln)
    return " ".join(lines)


def key_h(st):
    text = input("hypothesis (one falsifiable sentence): ")
    print("you typed: %r" % text.strip())
    ans = input("can a reader disagree with this? y/n: ").strip().lower()
    res, detail = intake(st, text, ans == "y")
    print("%s: %s" % (res, detail))


def key_s(st):
    ref = input("source ref (url / book+page / note): ")
    bo = input("what might it bear on? (a guess, tested later): ")
    sid = add_source(st, ref, bo)
    print("registered %s (inventory only; nothing trusted yet)" % sid)


def _decompose_one(st, cid):
    print("decomposing %s: %s" % (cid, node(st, cid)["text"]))
    needs = []
    while True:
        a = input("what must be true for it to hold? (blank to stop): ").strip()
        if not a:
            break
        needs.append(a)
    add_needs(st, cid, needs)
    attacks = []
    while True:
        a = input("strongest case it is false? (blank to stop): ").strip()
        if not a:
            break
        attacks.append(a)
    add_attacks(st, cid, attacks)
    if not needs and not attacks:
        print("nothing added; it stays as it was")


def key_d(st):
    nxt = next((n["id"] for n in st["nodes"]
                if n["id"] not in st["leaves"]
                and not need_children(st, n["id"])), None)
    if nxt is None:
        if not st["linchpin"]:
            leaves = [c for c in need_chain(st) if c in st["leaves"]]
            if leaves:
                print("every branch ends in a leaf. leaves on the need-chain:")
                for i, c in enumerate(leaves):
                    print("  %d. %s %s" % (i + 1, c, node(st, c)["text"]))
                pick = input("which one, if it fell, takes the whole claim "
                             "with it? number: ").strip()
                mark_linchpin(st, leaves[int(pick) - 1])
                return
        print("nothing left to decompose")
        return
    a = input("could a single source, at a single locator, settle: '%s'? y/n: "
              % node(st, nxt)["text"]).strip().lower()
    if a == "y":
        mark_leaf(st, nxt)
        print("%s is a leaf; it awaits grounding" % nxt)
    else:
        _decompose_one(st, nxt)


def _grade_flow(st, sid, cid):
    r = input("FETCH stub: is %s reachable? y/n: " % sid).strip().lower()
    if r != "y":
        grade_record(st, sid, "DEAD")
        print("graded DEAD")
        return
    o = input("does the text at that spot say what the claim says? "
              "y=yes / o=opposite: ").strip().lower()
    if o == "o":
        grade_record(st, sid, "SAYS_OTHERWISE", cid)
        print("graded SAYS_OTHERWISE against %s" % cid)
    else:
        grade_record(st, sid, "LIVE")
        print("graded LIVE")


def _work_across(st, sid, just_grounded):
    for n in st["nodes"]:
        cid = n["id"]
        if cid == just_grounded:
            continue
        a = input("does it also bear on '%s'? s=support / c=contradict / "
                  "n=no: " % n["text"]).strip().lower()
        if a == "s":
            loc = input("where exactly? locator: ").strip()
            work_across_record(st, sid, cid, "support", loc)
        elif a == "c":
            work_across_record(st, sid, cid, "contradict")


def key_g(st):
    fl = floating(st)
    if not fl:
        print("nothing floating; press c to try to close")
        return
    for i, c in enumerate(fl):
        print("  %d. %s %s" % (i + 1, c, node(st, c)["text"]))
    pick = input("ground which? number (blank = 1): ").strip()
    cid = fl[int(pick) - 1 if pick else 0]
    cands = candidates_for(st, cid) or st["sources"]
    attached = False
    for s in cands:
        a = input("does %s (%s) say this? locator or n: "
                  % (s["id"], s["ref"])).strip()
        if a.lower() == "n" or not a:
            continue
        attach(st, cid, s["id"], a)
        attached = True
        _grade_flow(st, s["id"], cid)
        _work_across(st, s["id"], cid)
        break
    if not attached:
        a = input("no source grounds it. d=decompose smaller / h=admit hole: "
                  ).strip().lower()
        if a == "h":
            declare_hole(st, cid, input("why can't it be grounded? ").strip())
        else:
            _decompose_one(st, cid)


def key_c(st):
    res = try_close(st)
    if res[0] == "CLOSED":
        st["trail"].append({"event": "close", "state": "CLOSED"})
        print("CLOSED. the graph holds; the verdict is settled before any "
              "prose. press p to plan passages.")
    elif res[0] == "BROKEN":
        record_refuted(st, res[1], res[2])
        print("BROKEN(%s, %s) -> run ends REFUTED. no prose was ever written."
              % (res[1], res[2]))
    else:
        print("OPEN. still floating: %s" % ", ".join(res[1]))


def key_p(st):
    if st["specs"]:
        print("already planned")
        return
    if try_close(st)[0] != "CLOSED":
        print("graph is not CLOSED; phase 2 is unreachable")
        return
    specs = plan_passages(st)
    for i, sp in enumerate(specs):
        print("  %d. %s [%s] claims=%s ~%dw" %
              (i + 1, sp["id"], sp["label"], ",".join(sp["claims"]),
               sp["target"]))
    order = input("reading order, e.g. 2,1,3 (Enter = as listed): ").strip()
    if order:
        specs = [specs[int(i) - 1] for i in order.split(",")]
    materialize(st, specs)
    print("placeholders written; %d passages bound" % len(specs))


def _next_spec(st, needs_fill):
    for sp in st["specs"]:
        if sp["id"] in st["done"]:
            continue
        has_fill = any(p["kind"] == "fill" and
                       p["address"] == _address_of(st, sp["id"])
                       for p in st["prose"])
        if needs_fill == has_fill:
            return sp
    return None


def key_f(st):
    sp = _next_spec(st, needs_fill=False) or _next_spec(st, needs_fill=True)
    if sp is None:
        print("every passage is done")
        return
    b = brief(st, sp, CONSTRAINTS)
    print("BRIEF for %s [%s], register=%s, target ~%dw, at %s"
          % (sp["id"], sp["label"], b["register"], b["target"], b["address"]))
    print("claims to express, verbatim:")
    for c in b["claims"]:
        recs = "; ".join("%s @ %s" % (s["ref"], s["locator"])
                         for s in c["sources"]) or "no receipts"
        print("  %s: %s  (%s)" % (c["id"], c["text"], recs))
    print("constraints: %s | voice: %s"
          % (b["constraints"]["banned"], b["constraints"]["voice"]))
    fill(st, sp["id"], read_prose())
    print("filled %s; press k to check it" % sp["id"])


def key_k(st):
    sp = _next_spec(st, needs_fill=True)
    if sp is None:
        print("no filled, unchecked passage")
        return
    text = latest_prose(st, _address_of(st, sp["id"]))
    recs = mechanical(st, text, sp["target"])
    found = extract(text)
    unmapped = map_claims(st, found, sp["claims"])
    for r in recs:
        print("  %s %s: %s" % ("ok " if r["ok"] else "FAIL",
                               r["check"], r["detail"]))
    print("  extracted %d checkable sentence(s)" % len(found))
    for s in unmapped:
        print("  UNMAPPED: %r (cut it, or ground it into the graph first)" % s)
    if all(r["ok"] for r in recs) and not unmapped:
        mark_done(st, sp["id"], recs, len(found))
        print("passage %s accepted" % sp["id"])
    else:
        print("redo %s: the named failures above, not a counted attempt"
              % sp["id"])


def key_x(_st):
    w = input("seed 1 (reaches CLOSED) or 2 (hits BROKEN)? ").strip()
    st = demo_seed(broken=(w == "2"))
    print("standing-desk example loaded (seed %s)" % w)
    return st


def key_t(st):
    for t in st["trail"]:
        print("  " + ", ".join("%s=%s" % kv for kv in t.items()))


def final_output(st):
    print("\n==== THE WORK ====")
    if st["bindings"]:
        for b in st["bindings"]:
            print("\n[%s]\n%s" % (b["spec"], latest_prose(st, b["address"])))
    else:
        print("(no prose; the run never reached phase 2)")
    print("\n==== THE RECORD ====")
    key_t(st)
    print("\n==== VERDICT: %s ====" % verdict(st))


def main():
    st = new_state()
    handlers = {"h": key_h, "s": key_s, "d": key_d, "g": key_g, "c": key_c,
                "p": key_p, "f": key_f, "k": key_k, "x": key_x, "t": key_t}
    while True:
        render(st)
        k = input("key> ").strip().lower()
        if k == "q":
            final_output(st)
            return
        h = handlers.get(k)
        if h is None:
            print("unknown key")
        else:
            out = h(st)
            if out is not None:
                st = out
        input("[Enter] ")


if __name__ == "__main__":
    main()
