# Routing map of the meta skills

Which of the `brain-*` skills hands on to which. Every brain ships with these skills and this file;
the template owns it and `_meta/brain update` replaces it, so a brain never edits it. The harness
reads it together with the brain's own `docs/ROUTING.md` as one graph: a diagram there hands on to a
skill drawn here by using its id (`brain-write-practice`, `brain-retro`), without declaring it again.
The brain's `docs/ROUTING.md` describes the dialect, which `_meta/brain lint` enforces.

## The meta skills

```mermaid
flowchart LR
classDef entry fill:#e8eef7,stroke:#5b7aa6,color:#1f2328;
classDef work fill:#eceff3,stroke:#6b7686,color:#1f2328;
classDef decision fill:#efe8f6,stroke:#8061a8,color:#1f2328;
classDef human fill:#f8e6e6,stroke:#a86060,color:#1f2328;
  META_LEARNED(something worth keeping was learned):::entry --> META_KIND{what kind}:::decision
  META_KIND -->|a sequence with judgement| brain-write-skill:::work
  META_KIND -->|a fact| brain-write-practice:::work
  META_KIND -->|a query or a tool| brain-write-script:::work
  brain-write-skill -.->|needs a script| brain-write-script
  brain-write-skill --> brain-sync:::work
  brain-write-script --> brain-sync
  brain-write-practice --> brain-sync
  META_MOD(show something or react inside Claude Code itself):::entry --> brain-write-mod:::work
  brain-write-mod -.->|needs a script| brain-write-script
  brain-write-mod --> brain-sync
  META_WRONG(a skill went wrong, or work fit no skill):::entry --> brain-retro:::work
  brain-retro -.->|a mod went wrong| brain-write-mod
  brain-retro -.->|the brain's own skill| brain-write-skill
  brain-retro -.->|a brain-* skill or _meta| brain-upstream:::work
  brain-upstream --> brain-sync
  META_SETUP(set up, repair or update this brain):::entry --> brain-setup:::work
  brain-setup --> brain-sync
  brain-setup -.->|interview: words that mislead| brain-write-practice
  brain-setup -.->|interview: a system to connect| brain-write-script
  brain-setup -.->|interview: work that recurs| brain-retro
  brain-setup -.->|a hub's routing skill| brain-write-skill
  META_STALE(behind, or unpushed work):::entry --> brain-sync
  brain-sync --> META_PUSH(the person decides to push):::human
```

## Not drawn

A meta skill that is deliberately not drawn goes here with the reason, so "missing" always means
"nobody drew it".

| Skill | Why it is not drawn |
| --- | --- |
