---
name: sidequest-qa-review-app
description: Verify an open PR on its configured Heroku review app using a dedicated test login.
---

# QA a review app

Follow `{{SIDEQUEST_HOME}}/agents/RULES.md`. This optional workflow needs an open
PR, a configured Heroku pipeline and an approved test account for that review app.

1. Run `{{SIDEQUEST_DATA}} review-app APP-123 --json` (or --pr N). Do not assume a
   provisioned app is ready; wait until its status is Web up.
2. Read the ticket's local QA specification. Use qa-review/shots.json to override it
   when necessary. Use relative paths so requests stay on the discovered review app.
3. Have the user set SIDEQUEST_REVIEW_EMAIL and SIDEQUEST_REVIEW_PASSWORD locally.
   No local account defaults or Keychain entries are reused. The helper only sends
   this login to the HTTPS Heroku host identified for this PR.
4. Run `{{SIDEQUEST_DATA}} qa-shot APP-123 --review-app` (optionally --pr N).
   Save a criterion-by-criterion report in qa-review/report.md. Record any local
   commits that are not deployed to the PR's review app.
5. Present the evidence. Offer to update the PR screenshots only after approval.

Never change Jira, use production credentials, access production data or deploy.
