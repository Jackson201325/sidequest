# Queue UI

Run `../bin/sidequest --demo` to explore without accounts. The complete setup,
commands, keys, storage locations and limits are in [../README.md](../README.md).
Rendering uses curses and the Python standard library. The list stays above
details; `+/-` resizes the split and `=` restores it. `?` opens keyboard help.

All external collection runs in background workers. The UI thread applies source
updates and SQLite writes. Failed refreshes stay visible across restarts. Demo
mode uses in-memory data and disables all external actions.

Without tmux, w opens the existing worktree in your shell; Space n creates/reuses
one and opens it. Type exit to return to the dashboard. Space s uses the configured
workspace.agent_command in the same terminal. No tmux installation is needed.
