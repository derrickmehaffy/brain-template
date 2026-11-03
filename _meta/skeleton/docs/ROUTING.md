# Routing map

This map says which of this brain's skills hands on to which. Every skill is in it, drawn or listed
under `## Not drawn`. The `brain-*` skills are drawn in `_meta/ROUTING-META.md`, which the template
owns; the harness reads both files as one graph, so a diagram here can hand on to
`brain-write-practice` or `brain-retro`.

Draw each diagram as Mermaid inside a `mermaid` code fence, in this dialect, which `_meta/brain lint`
enforces:

- One `flowchart` per section. A node whose id is lowercase is a skill, and its id is the skill's
  name. An id that starts with a capital letter is something else: an entry trigger, a decision, a
  person acting, a store.
- Ids are shared across every diagram in both files: the same id in two diagrams is the same node,
  which is how one diagram continues another.
- Give each node a class when it first appears, from a fixed set: `entry`, `gate`, `work`,
  `optional`, `decision`, `state`, `human`. Write it as `:::gate`.
- `-->` is a call, `-.->` is a call that happens only sometimes, and `|label|` says when. Edges are
  calls, not cross-references: a "Does NOT ... that is X" clause is a boundary, so it is not drawn.
- A gate's class is its phase, and the arrows between gates are layout, not order. Every gate on a
  path runs every time, in any order, and its result is recorded whether or not it found anything.

## Not drawn

A skill that is deliberately not drawn goes here with the reason, so "missing" always means "nobody
drew it".

| Skill | Why it is not drawn |
| --- | --- |
