---
name: sidequest-where
description: Resume a ticket: work out where it stands from its Jira and PR activity, plan, updates, questions, meetings, QA evidence and local branch, then print a short status with the next step. Read-only. Use when the user says where am I, resume, catch me up or what is the state of APP-123.
---

# Where am I on a ticket

Follow `{{SIDEQUEST_HOME}}/agents/RULES.md`. Use `{{SIDEQUEST_DATA}}` as the helper command.
Input: a key such as APP-123; without one, use the key in the current branch name.

This skill only reads and reports. Do not edit code, plan.md or questions, do not create
a worktree or a plan, and do not change Jira or GitHub. Do not run tests or book the app.

## 1. Read the evidence
These are the sources behind the dashboard's tabs. Read all that exist; they are
independent, so one failure does not stop the others.
- Activity and Flow: `{{SIDEQUEST_DATA}} ticket APP-123 --json --activity`: status,
  assignee, status history, comments and links.
- Work log: `{{SIDEQUEST_DATA}} worktree APP-123 --json`. In a checkout it finds, run
  `git status --short`, `git log` for the branch's own commits with dates, and
  `{{SIDEQUEST_DATA}} ship-check --no-fetch --json` (ahead/behind, changed files, leftover
  plan markers). Search for the numbered `APP-123 (n)` markers still in the code.
- Pull request: `{{SIDEQUEST_DATA}} pr-feedback --json` lists the open PRs; take the one
  whose branch names the key. Then `{{SIDEQUEST_DATA}} pr-feedback N --json --activity`:
  draft state, review decision, checks, unresolved threads, reviews and commits.
  When a PR exists, `{{SIDEQUEST_DATA}} review-app APP-123 --json` gives its review app.
- Plan and Updates: plan.md in the ticket folder: acceptance criteria with ticked and
  unticked boxes, the user's edits, and the dated lines under Updates.
- Questions: `{{SIDEQUEST_DATA}} questions APP-123 list`: open, asked and answered.
- Meetings: meetings.md in the ticket folder, when present.
- QA: the ticket folder's qa/ and qa-review/ (report, manifest, screenshots), when
  present, with their dates.

A missing file is evidence ("no plan yet"). A source that fails (no token, `gh` not
signed in, command error) is unknown: name it and the error. Never report a failed
source as empty.

## 2. Deduce the state
Order the dated evidence into one timeline, newest first. Then pick the furthest stage
that the evidence supports, and say what supports it:
1. Not started: no branch, no worktree, no plan.
2. Planned: plan.md exists; the branch has no commits or changes of its own.
3. In progress: commits or uncommitted changes exist; some criteria are unticked or
   their code is missing. Name the criteria done and the criteria left.
4. Ready for QA or ship: all criteria are met in the diff; no PR yet.
5. In review: a PR is open. Say who must act: you (unresolved threads, changes
   requested, failed checks, a draft) or the reviewers (waiting since when).
6. Merged or done: the PR is merged or the ticket is in a done status. Name anything
   left over (review app QA, a ticket still in an earlier status, a worktree to remove).
Check the sources against each other and report each conflict, for example: a ticked
criterion with no code for it, a Jira status behind the PR, a meeting note or answered
question newer than the plan, a comment added after the last commit, uncommitted work on
a branch whose PR is open. When two stages fit, say so; do not choose silently.

## 3. Print the resume
Reply with this, in plain text, short enough to read in a minute:
- **State**: one sentence (stage, and who must act next).
- **Last activity**: the three to five newest events with dates and authors, and the
  date of your own last work on it.
- **Done / left**: acceptance criteria met and not met; uncommitted and unpushed work.
- **Blockers**: open questions with their ids, failed checks, unresolved review threads,
  conflicts found in step 2.
- **Unknown**: each source that failed or is missing, and what it would have shown.
- **Next step**: one concrete action, and the skill for it (sidequest-start,
  sidequest-implement, sidequest-qa-local, sidequest-ship, sidequest-feedback or
  sidequest-qa-review-app).

Deduce from the evidence before you ask. Ask the user only for a fact that no source
holds, and ask at most the questions that would change the next step. Mark each
deduction that rests on one weak signal as a guess.
