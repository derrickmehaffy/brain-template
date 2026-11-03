# Inbox

Work another brain handed over to this one. Entries are added by that brain, with
`_meta/brain brains handoff`; nothing here is written by hand. Work an open entry through the routing
map like any other request. When it is done, set its status to `done`, or to `declined: <reason>`,
and commit through `brain-sync`. The session-start check reports every entry still open.

Each entry is a `## <date> · from <brain> · <title>` heading, a `- status: open` line and the request.
