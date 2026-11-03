# Routing map of the template

Which of the template's own skills (`template-*`) hands on to which. They never ship: a brain gets
the skeleton's `docs/ROUTING.md`, never this file. Sessions here also use the shipped `brain-*`
skills on the template itself; those are drawn in `_meta/ROUTING-META.md`, which the harness reads
with this file as one graph, so the diagrams below hand on to them by id.

The dialect is the one every brain uses, enforced by `_meta/brain lint`: one `flowchart` per section;
a lowercase id is a skill and is its exact name, a capitalised id is anything else; each node gets
one class (`entry`, `gate`, `work`, `optional`, `decision`, `state`, `human`); `-->` is a call and
`-.->` a call that happens only sometimes. `brain-write-skill` places a skill here and
`_meta/brain routing sync` writes the `## Where this sits` block of every skill from both maps.

## Making brains

```mermaid
flowchart LR
classDef entry fill:#e8eef7,stroke:#5b7aa6,color:#1f2328;
classDef work fill:#eceff3,stroke:#6b7686,color:#1f2328;
classDef human fill:#f8e6e6,stroke:#a86060,color:#1f2328;
  MAKE(make or adopt a brain):::entry --> template-make-brain:::work --> OPEN(the person opens a session in the brain):::human
```

## Taking in suggestions

```mermaid
flowchart LR
classDef entry fill:#e8eef7,stroke:#5b7aa6,color:#1f2328;
classDef work fill:#eceff3,stroke:#6b7686,color:#1f2328;
  INTAKE(suggestions from brains):::entry --> template-intake:::work
  template-intake -.-> brain-write-skill
  template-intake -.-> brain-write-script
  template-intake --> brain-sync
```

## Not drawn

A skill that is deliberately not drawn goes here with the reason, so "missing" always means "nobody
drew it".

| Skill | Why it is not drawn |
| --- | --- |
