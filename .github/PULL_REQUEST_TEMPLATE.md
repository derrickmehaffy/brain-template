## What and why

<!-- One or two lines: the change, and the problem it solves for a brain. Link the issue if there is one. -->

## Checklist

- [ ] Tests pass: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -t . -v`
- [ ] `_meta/brain lint` and `_meta/brain routing sync --check` are clean
- [ ] A change brains should receive has a `_meta/CHANGELOG.md` entry
- [ ] `brain-*` skills were changed through `brain-write-skill`, and stay written for any brain
- [ ] Standard library only; Python 3.9+; macOS and Linux
- [ ] Nothing specific to one organisation, product, person or machine
