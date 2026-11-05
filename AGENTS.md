# Standalone sidequest development

Read DEVELOPMENT.md, HARDENING.md and ticket-tui/DESIGN.md before changes.
Use Python 3.9+ standard library only. Keep rendering, domain rules, service
transport and snapshot publication separate.

Reproduce behavioral changes at a public boundary with a failing test before
fixing them. Mock services and use temporary files. Run bin/check before finishing.
Update the relevant help, README, DEVELOPMENT.md and HARDENING.md together.

Jira transport belongs in bin/sidequest-jira.py. Keep all collectors read-only. Failed
or incomplete sources must retain their previous data and original timestamps.
Never copy credentials, real snapshots, private ticket text, shell profiles or
another checkout's helpers into this repository. Keep runtime storage outside it.
Never add remote writes or destructive worktree actions to refresh or tests.
Do not publish, push, deploy or send messages without user authorization.
