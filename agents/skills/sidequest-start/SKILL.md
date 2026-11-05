---
name: sidequest-start
description: Read a Jira ticket, find or create its local worktree and prepare an implementation plan.
---

# Start a ticket

Follow `{{SIDEQUEST_HOME}}/agents/RULES.md` and the target project's instructions.
Use `{{SIDEQUEST_DATA}}` as the helper command throughout this workflow.

1. Read the requested key with `{{SIDEQUEST_DATA}} ticket APP-123 --json --activity`.
   Read the description, acceptance criteria and comments. Ask for missing evidence;
   do not invent requirements. Open any relevant attachments through the user's Jira
   access before planning; this portable helper does not download attachments.
2. Run `{{SIDEQUEST_DATA}} worktree APP-123 --json`. Reuse existing work, including
   a main checkout already on the ticket's branch. Preserve all unrelated changes.
3. If no checkout exists, preview `{{SIDEQUEST_DATA}} workspace APP-123 --summary
   "Ticket summary" --type Bug --base origin/main`. Choose the base from the target
   project's instructions. A user request to start local ticket work authorizes
   repeating the reviewed command with `--apply`. Use --prefix hotfix only when requested.
4. Use `{{SIDEQUEST_DATA}} plan-init APP-123 --summary "Ticket summary"`. Fill the
   printed plan with the user-facing problem, code flow, acceptance checklist,
   approach, tests, risks and open questions. Preserve any existing plan edits.
5. Report the branch, checkout, plan and intended tests. Ask before implementation
   if the request only authorized planning. Propose any Jira status change for the
   user to apply; board-specific transitions are not automated by Sidequest.

Never push, open a PR, reset an existing checkout or copy environment secrets.
