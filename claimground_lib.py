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

State schema (all lists append-only; latest record wins):
    nodes     [{id, text}]                       claims; nodes[0] is the root
    edges     [{kind: need|attack, src, dst}]
              [{kind: ground, claim, source, locator, quote?}]
    sources   [{id, ref, url?, bears_on}]
    grades    [{source, grade: LIVE|DEAD|SAYS_OTHERWISE, claim?, quote?}]
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

VERSION = "0.0.1"

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
        if g.get("grade") not in ("LIVE", "DEAD", "SAYS_OTHERWISE"):
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
body { margin:0; background:var(--paper); color:var(--ink);
  font:16px/1.65 system-ui,-apple-system,Segoe UI,sans-serif; }
header.top { position:sticky; top:0; display:flex; align-items:center;
  gap:12px; padding:10px 20px; background:var(--paper);
  border-bottom:2px solid var(--line); z-index:5; }
.brand { font-family:var(--mono); font-weight:700; letter-spacing:.12em;
  font-size:13px; }
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
.verdict-line { font-size:18px; font-weight:600; }
article.passage { background:var(--card); border:1px solid var(--line);
  border-left:4px solid var(--accent); border-radius:6px;
  padding:4px 16px 10px; margin:12px 0; }
article.passage.objection { border-left-color:var(--mid); }
article.passage.linchpin { border-left-color:var(--ok); }
ul.tree { list-style:none; padding-left:0; }
ul.tree ul { list-style:none; padding-left:22px;
  border-left:1px solid var(--line); margin:4px 0 4px 6px; }
ul.tree li { margin:7px 0; }
.cid { font-family:var(--mono); font-size:12px; color:var(--muted); }
.badge { font-family:var(--mono); font-size:11px; padding:1px 7px;
  border-radius:4px; border:1px solid var(--line); margin-left:6px;
  white-space:nowrap; }
.badge.live { color:var(--ok); border-color:var(--ok); }
.badge.dead { color:var(--muted); }
.badge.so, .badge.hole { color:var(--bad); border-color:var(--bad); }
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
pre.trail { background:var(--card); border:1px solid var(--line);
  border-radius:6px; padding:12px; font:12px/1.7 var(--mono);
  overflow-x:auto; }
.ledger { background:var(--card); border:2px solid var(--bad);
  border-radius:6px; padding:10px 16px; margin:14px 0; }
footer { margin-top:48px; color:var(--muted); font-size:12.5px;
  border-top:1px solid var(--line); padding-top:12px; }
#copytext { position:absolute; left:-9999px; top:0; }
a { color:var(--accent); }
@media print { header.top button { display:none; } }
"""

_JS = """
document.getElementById('copybtn').addEventListener('click', async () => {
  const btn = document.getElementById('copybtn');
  const txt = document.getElementById('copytext').value;
  try { await navigator.clipboard.writeText(txt); }
  catch (e) {
    const ta = document.getElementById('copytext');
    ta.select(); document.execCommand('copy');
  }
  btn.textContent = 'copied';
  setTimeout(() => { btn.textContent = 'copy page as text'; }, 1500);
});
"""


def _esc(s):
    return html.escape(str(s), quote=True)


def _grade_badges(state, cid):
    out = []
    for e in ground_edges(state, cid):
        g = latest_grade(state, e["source"]) or "ungraded"
        cls = {"LIVE": "live", "DEAD": "dead",
               "SAYS_OTHERWISE": "so"}.get(g, "dead")
        out.append('<span class="badge %s">%s @ %s: %s</span>'
                   % (cls, _esc(e["source"]), _esc(e["locator"]), _esc(g)))
    for h in state["holes"]:
        if h["claim"] == cid:
            out.append('<span class="badge hole">HOLE: %s</span>' % _esc(h["why"]))
    src = _contradicted(state, cid)
    if src:
        out.append('<span class="badge so">%s says otherwise</span>' % _esc(src))
    return "".join(out)


def _tree_html(state, cid, is_attack=False):
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
    return ('<li><span class="cid">%s</span> %s%s%s</li>'
            % (_esc(cid), _esc(node(state, cid)["text"]), badges, sub))


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


def render(state, out_path):
    v = verdict(state)
    vclass = v.split("(")[0]
    close_res = try_close(state)
    root = state["nodes"][0] if state["nodes"] else {"id": "?", "text": "(empty)"}
    meta = state.get("meta") or {}
    stamp = meta.get("date") or date.today().isoformat()
    title = meta.get("title") or root["text"]

    # --- passages ---
    passages_html, passages_txt = [], []
    for b in state["bindings"]:
        sp = next(s for s in state["specs"] if s["id"] == b["spec"])
        text = latest_prose(state, b["address"]) or ""
        status = ("accepted" if sp["id"] in state["done"] else "draft")
        cls = sp["label"].replace(" ", "-") if sp["label"] in ("objection", "linchpin") else ""
        paras = "".join("<p>%s</p>" % _esc(p)
                        for p in re.split(r"\n\s*\n", text) if p.strip())
        passages_html.append(
            '<article class="passage %s"><h3>%s · %s · %s</h3>%s</article>'
            % (cls, _esc(sp["id"]), _esc(sp["label"]), status, paras))
        passages_txt += ["[%s · %s · %s]" % (sp["id"], sp["label"], status),
                         text, ""]
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
        obj_html.append("<li><span class='cid'>%s</span> %s <span class='badge %s'>%s</span> "
                        "(against %s)</li>"
                        % (_esc(attacker), _esc(node(state, attacker)["text"]),
                           "so" if "STANDS" in status else "live", _esc(status),
                           _esc(target)))
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
                atts_html.append("%s @ %s%s" % (_esc(e["claim"]),
                                                _esc(e["locator"]), q))
                atts_txt.append("%s @ %s%s"
                                % (e["claim"], e["locator"],
                                   (' :: "%s"' % e["quote"]) if e.get("quote") else ""))
        cls = {"LIVE": "live", "DEAD": "dead",
               "SAYS_OTHERWISE": "so"}.get(g, "dead")
        src_rows.append("<tr><td class='mono'>%s</td><td>%s</td>"
                        "<td><span class='badge %s'>%s</span></td><td>%s</td></tr>"
                        % (_esc(s["id"]), ref, cls, _esc(g),
                           "<br>".join(atts_html) or "not attached"))
        src_txt.append("%s. %s [%s]%s" % (s["id"], s["ref"] +
                       ((" <" + s["url"] + ">") if s.get("url") else ""), g,
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
                       '<span class="cid">%s</span> %s<br><strong>Cause:</strong> %s'
                       % (_esc(cid), _esc(node(state, cid)["text"]), _esc(cause)))
        ledger_html += "".join("<br>%s" % _esc(d) for d in detail) + "</div>"
        ledger_txt = ("DEAD CLAIM: %s %s\nCAUSE: %s\n%s"
                      % (cid, node(state, cid)["text"], cause, "\n".join(detail)))

    # --- trail ---
    trail_lines = ["  ".join("%s=%s" % kv for kv in t.items())
                   for t in state["trail"]]

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
        "Date: %s" % stamp, "",
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
        "<button id='copybtn'>copy page as text</button></header>",
        "<main>",
        "<section><p class='meta'>hypothesis</p><h1>%s</h1>" % _esc(root["text"]),
        "<p class='meta'>%s · %d claims · %d sources · %d trail events</p></section>"
        % (stamp, len(state["nodes"]), len(state["sources"]), len(state["trail"])),
        "<section><h2>Verdict</h2><p class='verdict-line'>%s</p><p>%s</p>%s</section>"
        % (_esc(v), _esc(vsent), ledger_html),
        "<section><h2>The work</h2>%s</section>" % "".join(passages_html),
        "<section><h2>The argument</h2>%s</section>" % tree_html,
        "<section><h2>Objections</h2><ul class='tree'>%s</ul></section>" % "".join(obj_html),
        "<section><h2>Sources</h2><table><tr><th>id</th><th>source</th>"
        "<th>grade</th><th>attached to</th></tr>%s</table></section>" % "".join(src_rows),
        "<details><summary>Trail (%d events)</summary><pre class='trail'>%s</pre></details>"
        % (len(trail_lines), _esc("\n".join(trail_lines))),
        "<footer>claim graph first, prose second. The verdict was settled by "
        "the graph before any prose existed; the prose answers to it. "
        "Generated by <a href='https://github.com/ctavolazzi/claimground'>"
        "claimground</a> v%s.</footer>" % VERSION,
        "</main>",
        "<textarea id='copytext' readonly>%s</textarea>" % _esc(txt),
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
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
