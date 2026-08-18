## Orientation

`README.md` has the repo map, local runtime, and endpoints. Read it rather than re-deriving the layout.

## graphify

A knowledge graph of this repo lives at `graphify-out/`.

- `graphify query "<question>"`, `graphify path "A" "B"`, and `graphify explain "X"` are **local** BFS traversals over `graph.json` — no LLM, token-budgeted (`--budget`, default 2000). Worth reaching for on cross-module "how does X reach Y" questions where grep would need several passes.
- Do **not** read `graphify-out/GRAPH_REPORT.md` (917 KB) or `graph.json` (38 MB) directly. They do not fit in context.
- The graph was last built 2026-07-28 and is stale relative to the working tree. `graphify update .` re-extracts from AST with no API cost.
