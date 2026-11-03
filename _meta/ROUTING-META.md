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
  LEARNED(something worth keeping was learned):::entry --> KIND{what kind}:::decision
  KIND -->|a sequence with judgement| brain-write-skill:::work
  KIND -->|a fact| brain-write-practice:::work
  KIND -->|a query or a tool| brain-write-script:::work
  brain-write-skill -.->|needs a script| brain-write-script
  brain-write-skill --> brain-sync:::work
  brain-write-script --> brain-sync
  brain-write-practice --> brain-sync
  WRONG(a skill went wrong, or work fit no skill):::entry --> brain-retro:::work
  brain-retro -.->|the brain's own skill| brain-write-skill
  brain-retro -.->|a brain-* skill or _meta| brain-upstream:::work
  brain-upstream --> brain-sync
  SETUP(set up, repair or update this brain):::entry --> brain-setup:::work
  brain-setup --> brain-sync
  STALE(behind, or unpushed work):::entry --> brain-sync
  brain-sync --> PUSH(the person decides to push):::human
```

## Not drawn

A meta skill that is deliberately not drawn goes here with the reason, so "missing" always means
"nobody drew it".

| Skill | Why it is not drawn |
| --- | --- |
