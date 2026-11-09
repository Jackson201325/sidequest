---
name: sidequest-qa-local
description: Verify a ticket locally, then capture acceptance screenshots and a QA report outside the repository.
---

# QA a local change

Follow `{{SIDEQUEST_HOME}}/agents/RULES.md` and the target project's environment and
test-account rules. Work in the ticket's checkout. When the project shares one local
app between worktrees and `app` is configured, run `{{SIDEQUEST_DATA}} app` before testing
(exit 75: another worktree has it; keep working and retry, or use `app --wait`; never
`--force`) and `{{SIDEQUEST_DATA}} app --release` when done, also after a failure.
Otherwise use the project's own documented commands to start it.

1. Read the ticket and plan, list every acceptance criterion, and run relevant tests
   (the test command under Project commands, when listed).
2. Verify each criterion in a local browser using demo data. Report failures before
   capturing success screenshots. Use the browser executable in the qa.browser setting
   when the helper cannot discover Chrome, Chromium or Edge.
   Sweep every screen the ticket sends QA through, not only the changed lines:
   reopen each modal, dropdown or panel two or three times without reloading (look
   for duplicated rows, stale data, double actions); use every filter, toggle, tab,
   sort and page control; check images, names, prices and counts; and confirm you
   opened the record you meant. For each issue, check whether the base branch has the
   same code and mark it pre-existing or caused by this branch. Report both.
3. Prepare `APP-123/qa/shots.json` under the configured tickets folder, with base_url,
   shots, names, paths, click/fill/expect steps and captions explaining where to look.
   Use the format in the Sidequest README. Do not put login secrets in this file.
4. Ask the user to set qa.email in their settings and SIDEQUEST_QA_PASSWORD in their
   terminal if login is needed. Never ask them to paste credentials into chat. Automatic
   local login is limited to localhost, loopback addresses and *.localhost.
5. Run `{{SIDEQUEST_DATA}} qa-shot APP-123`. Only passing checks produce success
   screenshots. A failure saves separate evidence and must be fixed and retested.
6. Write qa/report.md with tested criteria, click paths, results and limitations.
   Add a "Screen sweep" line: what was checked beyond the criteria and each issue,
   marked pre-existing or caused by this branch, or "nothing found".
   Use `{{SIDEQUEST_DATA}} qa-shot APP-123 --pr-markdown` for the screenshot section.

Do not push or post screenshots automatically. Re-capture if the branch's UI changes.
