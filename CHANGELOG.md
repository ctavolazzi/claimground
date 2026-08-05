# Changelog

## 0.0.3 (2026-08-04)

Report usability, all in service of the custody walk:

- Clickable chain of custody: claim ids and source ids cross-link
  everywhere (receipts, tree badges, objections, sources table, dead-claim
  ledger), with target highlighting, so sentence to claim to source to
  locator is literally walkable in the page.
- Stats strip under the hypothesis: leaves live, holes, source grades,
  objections answered, linchpin status. Also in the plain-text copy.
- Per-passage copy buttons (passage text plus its receipts).
- Grounding badges carry the exact quote as a tooltip.
- Argument tree: claim text and badges on separate lines.
- Styled trail (event names highlighted) replacing the raw pre block.
- Section nav in the sticky header; print stylesheet (light palette,
  controls hidden, no mid-card page breaks).

## 0.0.2 (2026-08-04)

Custody fixes from the first real runs (see FIXES-0.0.2.md): WALLED
grade, per-passage receipts, grade dates and notes displayed, tree
hole-badge truncation.

## 0.0.1 (2026-08-04)

First engine: pure append-only logic layer, CLI (validate / close / plan /
fill / check / verdict / render), self-contained HTML report with
copy-page-as-text. Grown from the throwaway terminal prototype.

## 0.0.4 (2026-08-04)

Visualizations:

- Inline SVG argument map in every report: hypothesis at top, needs and
  attacks layered below, source chips along the bottom, ground edges
  colored by grade. Every node and chip links into the same #claim / #src
  custody anchors, so the map is a third entry point into the walk.
  Status is never color alone: dash patterns, worded labels (ATTACK,
  LINCHPIN, HOLE), full-text tooltips, and a worded legend. Validated
  against the dataviz palette checks; the rust/amber adjacency relies on
  documented secondary encoding (patterns plus labels), per status-palette
  rules.
- Argdown export: `argdown state.json out.argdown` serializes the graph
  for Argdown's VS Code argument-map tooling. Export only; the file
  header documents the semantic nuance (Argdown '+' is support,
  claimground's need edge is a necessary condition). Both real runs ship
  with argument.argdown files.
