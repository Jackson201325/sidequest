---
name: sidequest-feedback
description: Read complete PR feedback, make scoped fixes and draft replies for user approval.
---

# Handle review feedback

Follow `{{SIDEQUEST_HOME}}/agents/RULES.md`. Locate the correct checkout first with
`{{SIDEQUEST_DATA}} worktree APP-123 --json`.

1. Read `{{SIDEQUEST_DATA}} pr-feedback N --json --activity`. It includes unresolved
   thread pages, discussions, reviews and commit evidence. Stop if collection fails;
   do not treat inaccessible comments as an empty review.
2. Classify each request as a fix, question, disagreement or already addressed.
   Validate automated suggestions against the actual code and requirements.
3. Reproduce behavioral defects first, make scoped fixes and run relevant project
   checks. Review the complete resulting diff and leave unrelated changes untouched.
4. Prepare ticket-scoped commits and a reply for each thread, linking evidence.
   Push and post replies only under the user's explicit authorization. Resolving
   threads is a separate remote action that also needs authorization.
5. Report changes, tests, outstanding questions and the PR URL. Do not merge or deploy.
