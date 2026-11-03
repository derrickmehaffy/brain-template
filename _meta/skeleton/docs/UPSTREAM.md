# Upstream suggestions

Changes this brain would like made to the files the template owns (`_meta/`, a `brain-*` skill, a
managed block), and the template's answers. Record one with the `brain-upstream` skill. Write it
without this brain's private details, because it is sent to the template.

Each suggestion is a `## <YYYY-MM-DD-slug>` heading followed by three lines, `- template: <version>`,
`- files: <paths>` and `- status: open|landed <version>|declined: <reason>`, and then the sections
`### What happened` and `### Proposed change`. When the template answers, the commit that brings in
that update flips `open` to `landed` or `declined`.
