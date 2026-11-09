# Portable workflow rules

Read the target repository's AGENTS.md and development guide first. Its testing,
environment booking, branch and review rules apply. Sidequest never supplies a
shared Docker stack, private account, company checkout or production access.

Use the bundled sidequest-data helper for ticket evidence, naming, worktree lookup,
plans, QA capture, review apps, feedback and pre-PR checks. Collection stays read-only.
The one Jira write is `jira-start`, which moves a ticket to the project's start status
only when jira.start_status is set. The workspace command previews by default; --apply
explicitly creates a local worktree and copies only the files listed in
workspace.copy_files into it. It never removes worktrees or switches an existing checkout.

Log every question about unclear requirements with `sidequest-data questions APP-123
add "<question>" --context "<why>"`. Record when the user asked it (`asked Q1 --to WHO
--via WHERE`), the answer in the asker's words (`answer Q1 "..." --by WHO --via WHERE`)
and the resulting `decision`. Never edit questions.md directly, invent an answer, or
post questions to Jira or chat unless asked.

If the project shares one local app between worktrees, book it with `sidequest-data app`
before tests or browser checks, re-run it before each further test command, and release
it with `sidequest-data app --release` when done. Exit code 75 means another worktree
is testing: keep coding and retry later, or use `--wait`. Never use `--force`.

Use temporary or demo data. Never modify production data, reset shared databases,
delete worktrees or deploy through these workflows. Put ticket plans and screenshots
outside repositories. Keep credentials in the user's environment, never in a plan,
shot specification, PR, source file or conversation.

Reproduce bugs with a failing test, make the smallest scoped fix and run the target
project's relevant checks. Keep unrelated uncommitted files and hunks untouched.
Commit only authorized, ticket-scoped work. No attribution trailers or generated-by
text in commits, PRs or comments. Review the complete branch diff before publishing.

Draft remote changes for review. Ask before pushing, opening a PR, posting replies,
changing Jira status or assigning reviewers unless the current user has explicitly
authorized that action. Never merge, deploy, force-push or push to a protected branch.
