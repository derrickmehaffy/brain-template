# Reviewing practices: rulings and the sweep

## Reading `candidates`

```bash
_meta/brain practices candidates --tags router,vlan,mdns --text "the router drops mDNS between VLANs"
```

Each line is `<score> <id>: <the entry's point>`, best first, at most five. The score is 0.6 times the
tag overlap plus 0.4 times the word overlap: a ranking, not a verdict. A high score means "read this
one", never "this is a duplicate". Once you have drafted the entry, `practices candidates
docs/practices/<id>.md` ranks against the draft itself (an entry is never its own candidate).

For each listed entry, read its point (and the entry, when the point is close) and ask three things:
is it the same system, the same behaviour, and under the same conditions (version, setting, access)?

| Same system | Same behaviour | Same conditions | Ruling |
| --- | --- | --- | --- |
| yes | yes | yes | **merge**: one fact, one entry |
| yes | yes, but the claim differs | yes | **supersede**: the old one is wrong, or the system changed |
| yes | yes | no | **distinct**: each says its condition; link them with `[[id]]` |
| any | no | any | **distinct** |

## Worked rulings

**Homelab, distinct.** Proposed: the router drops mDNS between VLANs unless its reflector is on.
`candidates` lists `router-vlan-default-isolation` (0.52), which says which VLANs reach the internet
by default. Same router, different behaviour: distinct. Write `router-mdns-not-forwarded-across-vlans`
with `reviewed-against: [router-vlan-default-isolation]`. The person said it and nobody has watched
it here, so `evidence: researched`, with their statement as the `source`.

**Game modding, merge.** Proposed: the mod loader reads mod folders in name order, upper case first.
`candidates` lists `mod-loader-load-order` (0.71), "mods load in alphabetical order", `researched`
from the loader's readme. You started the game with two dummy mods, `a-test` and `B-test`, and the
load log showed `B-test` first. Same fact, now observed: merge. Edit the existing entry: add the
case detail to the body, raise `evidence` to `reproduced`, add
`reproduced-by: loaded two dummy mods a-test and B-test and read the load log, 2026-11-02`, add the
log path to `source`, set `verified`. No new file. Its point changed, so run `candidates` on it
again and add anything new it lists to its `reviewed-against`.

**Plugin maintainer, supersede.** Proposed: in the host app's plugin API v3, `onLoad` runs before
settings are read. `candidates` lists `host-plugin-settings-before-onload` (0.64), verified against
v2. The v3 release notes changed the order and you reproduced it on v3, and the plugin no longer
supports v2: supersede. Write `host-plugin-v3-onload-before-settings` with
`reviewed-against: [host-plugin-settings-before-onload]`, then add
`superseded-by: host-plugin-v3-onload-before-settings` to the old entry and change nothing else in
it. Had the plugin still supported v2, both facts would hold under different versions: distinct,
each naming its version and linking the other.

## Superseding, step by step

1. Write the new entry first, naming the old one in its `reviewed-against`.
2. On the old entry, add `superseded-by: <new-id>` and leave the rest as it was: it is the record of
   what was believed and why. A superseded entry is no longer reported as stale.
3. Never delete an entry and never rename an id: other entries' `[[id]]` links and
   `reviewed-against` lists point at it, and `practices lint` blocks a link that does not resolve.

## Updating an existing entry

- Re-verified by observing it again: set `verified`, and update `reproduced-by` with how and the
  date. A second separate observation, with its own `source`, can raise it to `reliable`.
- Its point or tags changed: run `candidates` on the entry and extend `reviewed-against`.
- Its evidence fell (below): lower `evidence`, and keep `reproduced-by` as the record of the earlier
  observation.

## The sweep, in full

When: `practices lint` or `doctor` warns that entries are stale, before relying on a `volatile` fact,
or on a regular rhythm the person picks.

1. `_meta/brain practices lint`. Each stale entry is a WARN line naming its file; `INDEX.md` lists the
   same entries under `## Stale`, oldest first.
2. For each stale entry, in turn:
   - Read its `recheck` before running it. Run it only when it only reads; when it would change
     something, ask the person first.
   - No `recheck` (a `durable` entry): re-read its `source`, or observe it again the way
     `reproduced-by` describes.
   - Rule on what you saw:

     | What you saw | Change |
     | --- | --- |
     | It holds, checked the way its level needs | `verified: <today>`; at `reproduced` or `reliable`, `reproduced-by` with today's how and date |
     | It holds, but you could only re-read a source | `evidence: researched`, `verified: <today>` |
     | It no longer holds | supersede it with an entry that says what is true now |
     | It cannot be checked now (the system is gone or out of reach) | leave it stale; tell the person |

3. `_meta/brain practices index`, then `_meta/brain practices lint` (no BLOCK), stage `INDEX.md` with
   the changed entries, and hand to `brain-sync`.

Never set `verified` to a day on which nothing was checked. A date moved to silence a warning makes
every later reader trust a fact nobody looked at.
