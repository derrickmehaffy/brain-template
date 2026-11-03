# Contributing

Thanks for helping. The template is small on purpose: standard-library Python, seven meta skills and
a few checks, written for any kind of brain. Changes that keep it that way are the easiest to take.

## Before you start

- For anything bigger than a fix, open an issue first (the **Suggestion** form), so the change is
  agreed before you build it.
- If you run a brain made from this template, its `brain-upstream` skill writes a suggestion with
  nothing private in it: paste that into the issue.
- Setting up your own brain rather than changing the template? Start with
  [docs/guides/start-here.md](docs/guides/start-here.md).

## Setting up

Python 3.9 or newer and git, on macOS or Linux (on Windows, inside WSL).

```bash
git clone https://github.com/derrickmehaffy/brain-template.git
cd brain-template
mkdir local
_meta/brain hook install
```

`local/` marks this as the template's own checkout rather than a copy to turn into a brain; it is
ignored and never committed. The hook is the pre-commit privacy guard every brain has.

## Making a change

- Read [CLAUDE.md](CLAUDE.md): it is the working agreement for this repository, and what Claude Code
  reads when you work on it with Claude.
- The `brain-*` skills ship to every brain. Edit them through the `brain-write-skill` skill: with
  Claude Code, the skill gate refuses a skill file until it has run.
- Harness code in `_meta/brainlib/` uses the standard library only, runs on Python 3.9+, macOS and
  Linux, and holds no absolute or home path.
- Write for any brain: nothing specific to one organisation, product, person or machine.
- A change brains should receive gets an entry in [_meta/CHANGELOG.md](_meta/CHANGELOG.md), which
  `update` shows to every brain that pulls it.

## Checks

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -t . -v
_meta/brain lint
_meta/brain routing sync --check
_meta/brain doctor
```

The tests are a smoke set: each way into a brain, once, end to end. Add a test when a change opens a
new route a person takes, not for every branch of the code.

## Commits and pull requests

- One scope per commit, with a short, imperative subject: `meta(<area>)`, `skill(<name>)`,
  `docs(<area>)` or `test(<area>)`.
- Open pull requests against `main`. CI runs the tests on Linux and macOS.

## Licence

By contributing, you agree that your contribution is licensed under the [MIT License](LICENSE).
