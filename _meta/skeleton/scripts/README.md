# Scripts

- Place a script by the system it touches: `scripts/<system>/`, or `scripts/common/` for code that two or more systems share.
- A script is read-only unless its name starts `apply_`, `write_` or `delete_`, and it takes secrets from the environment, never from its arguments.
- Tests live in `scripts/tests/`; write or change a script through the `brain-write-script` skill.
