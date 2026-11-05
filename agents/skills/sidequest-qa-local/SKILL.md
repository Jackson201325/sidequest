---
name: sidequest-qa-local
description: Verify a ticket locally, then capture acceptance screenshots and a QA report outside the repository.
---

# QA a local change

Follow `{{SIDEQUEST_HOME}}/agents/RULES.md` and the target project's environment and
test-account rules. Work in the ticket's checkout. Sidequest does not start or book
the application's Docker stack; use the project's own documented commands.

1. Read the ticket and plan, list every acceptance criterion, and run relevant tests.
2. Verify each criterion in a local browser using demo data. Report failures before
   capturing success screenshots. Use the browser executable in SIDEQUEST_QA_BROWSER
   when the helper cannot discover Chrome, Chromium or Edge.
3. Prepare `APP-123/qa/shots.json` under the configured tickets folder, with base_url,
   shots, names, paths, click/fill/expect steps and captions explaining where to look.
   Use the format in the Sidequest README. Do not put login secrets in this file.
4. Ask the user to set SIDEQUEST_QA_EMAIL and SIDEQUEST_QA_PASSWORD in their terminal
   if login is needed. Never ask them to paste credentials into chat. Automatic
   local login is limited to localhost, loopback addresses and *.localhost.
5. Run `{{SIDEQUEST_DATA}} qa-shot APP-123`. Only passing checks produce success
   screenshots. A failure saves separate evidence and must be fixed and retested.
6. Write qa/report.md with tested criteria, click paths, results and limitations.
   Use `{{SIDEQUEST_DATA}} qa-shot APP-123 --pr-markdown` for the screenshot section.

Do not push or post screenshots automatically. Re-capture if the branch's UI changes.
