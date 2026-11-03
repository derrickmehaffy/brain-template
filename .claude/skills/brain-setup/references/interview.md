# The setup interview

For a person who said yes to being interviewed ("grill me"). The aim is a brain that starts out
knowing their goals, their systems and how they like to work, rather than one that learns it all
over the first month.

## How to run it

- One question at a time, in plain words. A vague answer gets a concrete follow-up: "Walk me through
  the last time that happened."
- The first answer sets the register: someone who does not use git or a terminal gets no jargon in
  any later question.
- Pick from the bank below; do not recite it. Skip what an earlier answer already settled.
- Never ask for a password, key or token. Ask for its **name** ("what do you call the key for the
  invoicing app?"); values go in later through `env-sync --open`, never the chat.
- They can stop at any point ("that's enough"): everything not asked takes the default.
- Before writing anything, play back what you heard in a short list, grouped as in "Where answers
  go", and ask what is wrong or missing.

## The bank

1. **You.** "How comfortable are you with git, terminals and code? None at all is fine."
2. **The goal.** "What should this brain help you do? In a month, what would make it worth it?"
3. **The work.** "Walk me through the last time you did this with Claude. What comes up again and
   again? What starts it: a message, a date, a ticket, a question from someone?"
4. **Where it lives.** "Which projects, repos or folders does it touch? Where are they now? Are any
   in git, and where is their online copy?"
5. **Systems.** "Which apps, services or APIs does the work use? Which are already connected to
   Claude, and which would need a key?"
6. **People.** "Who else is involved: do you hand work to someone or answer to someone? Should
   Claude ever write to them directly, or always leave you a draft?"
7. **Words.** "Are there words that mean something specific here, or names people mix up?"
8. **Never.** "What must never happen? What must never be saved in the brain's history?"
9. **Other brains.** "Do you have other brains, or plan more?"
10. **Housekeeping.** An online backup; keeping the template's guides for now.

## Where answers go

| Answer | Goes to | Through |
| --- | --- | --- |
| Name, description, prefix, never-saved names | `init` flags | this skill |
| Where the work lives, other brains | the shape and its folders (`references/shapes.md`), the `CLAUDE.md` folder map, `brains add` | this skill |
| Goal, comfort level | `CLAUDE.md`: a `## What this brain is for` section, and one line on how to talk to them | this skill |
| What must never happen, who Claude may write to | `CLAUDE.md` `## Rules that bite`, one rule a line with its reason | this skill |
| Words that mislead | `docs/GLOSSARY.md` | `brain-write-practice` |
| Each system to connect | `docs/CAPABILITIES.md`, `.env` names, `.mcp.json` | `brain-write-script`, one system at a time, probed |
| Work that recurs | `docs/UNCLASSIFIED-LOG.md`, one row each with what a skill would need | `brain-retro` |
| The first routine they want now | a skill | `brain-write-skill` |

Order: `init` first (it needs the flags), then the shape's folders, then `CLAUDE.md`, then the
hand-offs. Ask before each hand-off ("Shall I connect the invoicing app now, or later?"); a "later" is
an unclassified-log row, not a promise kept in the chat.

If the person wants to stop before the hand-offs are done, write what is left as one open entry in
`docs/INBOX.md` (`## <date> · from setup · Finish setting up from the interview`, then
`- status: open` and the list): the next chat is told about it at its start, so nothing waits on
memory.
