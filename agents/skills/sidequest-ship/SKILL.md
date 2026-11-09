---
name: sidequest-ship
description: Review and test a ticket branch, prepare a scoped commit and PR, then publish only when authorized.
---

# Ship a ticket

Follow `{{SIDEQUEST_HOME}}/agents/RULES.md` and the target project's PR template.
Use that project's base branch, tests and lint (named under Project commands when listed);
do not assume a deployment model.

1. Read the ticket, plan, full branch diff and uncommitted changes. Identify what
   belongs to this ticket. Preserve unrelated files and hunks; ask about ambiguity.
2. Run `{{SIDEQUEST_DATA}} ship-check --no-fetch --base origin/main --json`, changing
   the base when the project uses another branch. Check secrets, debug code, local
   files, plan markers, migrations, schema changes and unexpected dependency churn.
   This check suggests Rails specs when relevant; it does not replace project tests.
3. Run the target project's checks and review the whole change for correctness,
   security, permissions and regressions. Fix must-fix findings before publishing.
4. For UI changes, run sidequest-qa-local and require current passing screenshots.
   If a PR already has a review app, offer sidequest-qa-review-app as a separate pass.
5. Commit only authorized ticket-scoped changes, by explicit path or hunk. Prepare
   a PR body outside the repository with problem, behavior, ticket link, validation,
   screenshots and remaining limits. Run `{{SIDEQUEST_DATA}} pr-body-check FILE`.
6. Present the exact branch, commit, target and PR text. After authorization, push
   the feature branch and use `gh pr create --body-file FILE --base BASE` with the
   project's template. Attach screenshots only through supported GitHub tooling.
7. Run `{{SIDEQUEST_DATA}} pr-body-check --pr N`, check CI and report the PR URL.
   Jira links and status transitions follow the user's own process; Sidequest does
   not assume a company-specific custom field or automatic linking action.

Never merge, deploy, force-push, push protected branches or post unapproved comments.
