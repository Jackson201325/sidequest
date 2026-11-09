---
name: sidequest-start
description: Start a Jira ticket: read it and open every attachment first, move it to the start status when configured, find or create its worktree, mark the code flow and write the plan. Use when the user says start, pick up or kick off APP-123.
---

# Start a ticket

Follow `{{SIDEQUEST_HOME}}/agents/RULES.md` and the target project's instructions (its
AGENTS.md or CLAUDE.md: test commands, app booking, base branch, PR template). Commands
listed under Project commands above come from Sidequest's settings for this project.
Use `{{SIDEQUEST_DATA}}` as the helper command throughout. Input: a key such as
APP-123. The user may also say "hotfix" or give a short name for the branch.

Never check out, reset or switch the main checkout: it may hold other uncommitted work.

## 1. Read the ticket
- Run `{{SIDEQUEST_DATA}} ticket APP-123 --json --activity`: summary, type, status,
  assignee, description (acceptance criteria are usually in it), comments, links.
- If it fails (for example no Jira token), show the error and ask the user to paste
  the ticket text. Do not guess.
- If the ticket is not assigned to the user, say so; it may still be right.
- Note vague or contradictory points as open questions for step 7. Do not stop.

## 2. Open every attachment before anything else
Attachments (screenshots, recordings, CSVs, PDFs, mockups) often show the real problem
better than the description, so read them before you search code or plan.
- Run `{{SIDEQUEST_DATA}} ticket APP-123 --attachments`. It saves each file in the ticket
  folder's attachments/ (outside the repository) and prints `SAVED <path>` or
  `ERROR <reason>: <file>`.
- Open every file: view images and PDF pages, read CSV and text files. For a video or
  a file you cannot open, say so and ask the user to describe it if it looks important.
- If a download fails, report it and ask the user to open the attachment. Do not plan
  as if it did not exist. Use what the files show in the plan, naming each file.

## 3. Move the ticket to the start status
Run `{{SIDEQUEST_DATA}} jira-start APP-123`. Its first word says what happened:
- `MOVED`: report it ("moved APP-123 Ready for Dev → In Dev").
- `ALREADY`: nothing to do.
- `ASK`: the ticket is in a status such as Backlog or Blocked. Ask the user; only after
  a yes, run `{{SIDEQUEST_DATA}} jira-start APP-123 --yes`.
- `SKIPPED`: the ticket is in a later status (review, QA); it may be follow-up work. Say so.
- "Moving tickets is off": the project has no start status. Tell the user which status
  to set; do not change Jira another way.
- A failure lists the available statuses; report it and continue.
This is the only Jira change this skill makes.

## 4. Find existing work first
- If the ticket folder has plan.md, read it: it is an earlier plan, maybe with the
  user's edits. If it has meetings.md, read it like ticket comments; later notes win,
  and anything that contradicts the ticket becomes an open question.
- Run `{{SIDEQUEST_DATA}} questions APP-123 list` to see questions already logged.
- Run `{{SIDEQUEST_DATA}} worktree APP-123 --json`:
  - `worktree` or `main-checkout`: use it and report "reused". If its tree is clean,
    `git -C <path> pull --ff-only` may update it; never reset or force anything.
  - otherwise go to step 5.

## 5. Create the worktree (only when none exists)
- Preview: `{{SIDEQUEST_DATA}} workspace APP-123 --summary "<summary>" --type "<issue type>"`.
  Choose the base from the project's instructions. Use `--prefix hotfix` (or chore)
  only when the user asked for it.
- A request to start the ticket authorizes repeating the reviewed command with `--apply`.
  It also copies the project's listed local files (workspace.copy_files, for example
  .env) into the new worktree and reports them as `copied`.
- If it fails, report the error and keep the existing checkout. Never improvise resets
  or worktree removal.
- Run the project's own dependency check if its instructions name one. Report the
  result; do not fix dependency problems unasked.

## 6. Find the code and leave numbered markers
Search the worktree for the ticket's key nouns and pick the 3–8 spots that matter.
Number them in the order the code runs: entry point (route, controller, job, command),
then services, then data access, then output (view, email, file, API response).
Put a one-line comment directly above each spot:
`# APP-123 (n): <why this spot matters, under ~80 chars> (plan: Code flow)`
(use the file's comment syntax: `//`, `<%# %>`, `--`, `<!-- -->`).
Markers are the only code edit this skill makes. They are never committed:
`{{SIDEQUEST_DATA}} ship-check` lists them as PLAN MARKERS and sidequest-ship removes them.

## 7. Write the plan
Run `{{SIDEQUEST_DATA}} plan-init APP-123 --summary "<summary>" --type "<issue type>"` and
fill every section. If it prints `EXISTS`, update the plan instead: keep the user's
edits and ticked boxes, and add a dated line under a final Updates section.
- **What's going on**: for someone who has not read the ticket, with 2–4 concrete
  examples from the ticket, comments and attachments. For a bug, how to see it; for a
  feature, a short before and after.
- **Code flow**: the numbered spots from step 6, same numbers as the markers.
- **Acceptance criteria**: a checklist from the ticket; mark drafted ones *(inferred)*
  and items agreed in meetings.md *(from meeting YYYY-MM-DD)*.
- **Open questions**: log each one with `{{SIDEQUEST_DATA}} questions APP-123 add
  "<question>" --source sidequest-start --context "<what is missing, and where>"`
  (`EXISTS` means it is already logged). In the plan, list the ids (Q1, Q2) and
  "see questions.md". Do not mark them asked: the user asks them.
- **PR**: the base branch and template from the project's instructions, and the ticket link.

## 8. Finish
Reply briefly with: worktree reused or created (and copied files), the Jira status
result, the attachments read (count and folder) and any you could not open, the
branch and path with a `cd` command, the markers added, the plan path (it shows in
the dashboard's Plan tab), and the question ids (Questions tab). Then ask whether to
start implementing.

Do not commit (markers included), push, open a PR, or change Jira in any other way
(assignee, comments, other statuses) unless the user asks.
