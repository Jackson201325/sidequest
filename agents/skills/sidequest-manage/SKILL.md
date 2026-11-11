---
name: sidequest-manage
description: Manage the crew: see every ticket and its worker at once, say what needs the user, start or resume worker agents in ticket worktrees and route answers back to them. Use when the user says crew, manage, overview of all tickets, or start workers on APP-1 APP-2.
---

# Manage the crew

Follow `{{SIDEQUEST_HOME}}/agents/RULES.md`. Use `{{SIDEQUEST_DATA}}` as the helper command
and `{{SIDEQUEST_HOME}}/bin/sidequest` as the launcher. You are the manager. Workers do the
ticket work in their own worktrees; you watch, explain and dispatch. Do not edit code,
plans or tests yourself, and do not run tests or book the app.

## 1. Read the whole state
Read these sources. They are independent, so one failure does not stop the others; say
which source failed and why.
- Workers: `{{SIDEQUEST_HOME}}/bin/sidequest crew --status`, and `{{SIDEQUEST_DATA}} run list --json`
  for each worker's history.
- Tickets: `{{SIDEQUEST_DATA}} snapshot --json`: lane, status, whose turn, PRs and CI.
- For each ticket with a worker or in progress: `{{SIDEQUEST_DATA}} questions KEY list`,
  plan.md in the ticket folder (ticked criteria and the Updates section) and
  `{{SIDEQUEST_DATA}} worktree KEY --json`.

## 2. Report
Give one short overview, the user's turn first:
1. Waiting on you: the ticket, the step, the open question or request, and how long it waited.
2. Failed: what failed and what you suggest.
3. Ready for you: at ship-check, what is ready to ship (the user runs sidequest-ship); after
   shipping, suggest starting qa-review with `crew KEY`. At qa-review, the review app result.
4. Working and queued: the step and the age of the last update. A worker that has not
   updated for a long time may have stopped; say so.
5. Tickets in progress with no worker: suggest which ones to start.
Keep each ticket to one or two lines.

## 3. Act only when the user asks
- Start workers: `{{SIDEQUEST_HOME}}/bin/sidequest crew KEY...`. Preview first with `--dry-run`
  when the user named many tickets. A ticket without its own worktree needs
  `{{SIDEQUEST_HOME}}/bin/sidequest start KEY` first; ask before you run it, because it can move
  the Jira status.
- Restart a worker that stopped: `{{SIDEQUEST_HOME}}/bin/sidequest crew KEY --again`.
- Answer a question: record the user's answer with `{{SIDEQUEST_DATA}} questions KEY answer
  Q<n> "<their words>" --by <who> --via crew`. Then tell the user to type "continue" in that
  ticket's worker window, or restart the worker with `--again` when its window is closed.
- Never answer a question yourself, never invent an answer, and never commit, push, open a
  PR, post comments or change Jira for a worker.

## 4. Stay available
After the report, wait. When the user asks again, read the state again; do not reuse an
old report.
