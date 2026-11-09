---
name: sidequest-implement
description: Implement a started ticket from everything already written: the plan with the user's edits, meetings, logged questions, attachments, new ticket comments and code markers. Use after sidequest-start, when the user says implement, build or apply the plan for APP-123.
---

# Implement a ticket

Follow `{{SIDEQUEST_HOME}}/agents/RULES.md` and the target project's instructions (its
AGENTS.md or CLAUDE.md: test commands, app booking, code style). Use `{{SIDEQUEST_DATA}}`
as the helper command. Input: a key such as APP-123. Work only in the ticket's checkout
from `{{SIDEQUEST_DATA}} worktree APP-123 --json`. If none exists, stop and offer
sidequest-start.

## 1. Read everything already written
The plan is the starting point, not the only source. Read all of it before you edit.
- plan.md in the ticket folder: every section, the user's edits, ticked boxes and the
  Updates section. The user's edits win over the original draft.
- meetings.md, when present: later notes win over the ticket and the plan.
- `{{SIDEQUEST_DATA}} questions APP-123 list`: answered questions change the work;
  open questions may block it.
- Every file in the ticket folder's attachments/ that the plan names or that shows
  expected behavior.
- `{{SIDEQUEST_DATA}} ticket APP-123 --json --activity` again: comments, links or
  description changes made after the plan.
- The numbered `APP-123 (n)` markers in the worktree, in order, and the code around them.
- `git -C <worktree> status` and the branch diff: earlier work on this ticket.
If a source cannot be read, say which one and why. Do not continue as if it were empty.

## 2. Reconcile before you build
List each difference between the plan and the newer sources (edits, meeting notes,
answers, new comments). Update plan.md: keep the user's text, change the affected
criteria, and add a dated line under Updates for each difference.
For each open question, decide whether it blocks a criterion. Build the criteria it
does not block. Ask the user about the blocking ones; do not guess an answer. Log a new
question with `{{SIDEQUEST_DATA}} questions APP-123 add "<question>" --source
sidequest-implement --context "<what is missing, and where>"`.

## 3. Build each criterion test-first
Work in the code-flow order of the plan. For each acceptance criterion:
1. Write or extend a test at a public boundary that shows the expected behavior.
2. Run it and see it fail for the expected reason.
3. Make the smallest change that makes it pass. Follow the code's existing patterns.
4. Run the focused tests (the test command under Project commands, when listed).
5. Tick the criterion in plan.md.
For UI-only criteria without a practical automated test, write the manual check into
the plan for sidequest-qa-local. When the project shares one local app and `app` is
configured, book it with `{{SIDEQUEST_DATA}} app` and release it with `app --release`,
also after a failure.
Do not change scope. Note a needed change outside the plan as an open question.

## 4. Check the whole change
- Run the project's full tests and lint (Project commands, when listed).
- Review the complete diff against every criterion and against the reconciled sources.
  Look for leftover debug code, unrelated edits and missing migrations.
- Keep the plan markers: sidequest-ship lists and removes them.

## 5. Finish
Reply briefly with: the sources read and any that failed, the plan differences found,
each criterion with its test and result, blocked criteria with their question ids, the
checks run, and the files changed. Name the next step: sidequest-qa-local for UI
changes, else sidequest-ship.

Do not commit, push, open a PR or change Jira unless the user asks.
