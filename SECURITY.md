# Security

## Reporting a vulnerability

Report it privately through GitHub: this repository's **Security** tab, then **Report a
vulnerability**. Please do not open a public issue for it. Expect a first answer within a week.

## In scope

- The pre-commit privacy guard (`_meta/brain hook`): any way to commit a `.env` file, a credential, a
  private term or a nested repository past it.
- Secret handling: `secret run`, `env-sync` or the scripts' `.env` loader printing or leaking a value.
- `new`, `adopt`, `init` and `update` writing outside the brain, following a link, or losing a
  person's files.

## Not a security boundary

The skill gate (`_meta/brain gate`) makes Claude run the right skill before it writes that skill's
output. It is friction and visibility for an agent working in good faith, not protection against a
determined one, so a way around it is a welcome bug report rather than a vulnerability. The same
goes for the `.env` read deny in `.claude/settings.json`: it stops a casual read, not every way of
reading a file.

## Supported versions

The latest commit on `main`. A brain gets fixes with `_meta/brain update`.
