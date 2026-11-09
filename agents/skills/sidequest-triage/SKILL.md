---
name: sidequest-triage
description: Investigate a supplied error using code and fixtures, then propose and test a scoped fix.
---

# Triage an error

Follow `{{SIDEQUEST_HOME}}/agents/RULES.md`. Use supplied logs or stack traces and
local source code. Production console, databases, customer messages and deployments
are outside this workflow.

1. Extract the exception, relevant application frames, trigger, environment and
   occurrence window. Ask once for evidence essential to reproduce the failure.
2. Read the target project's release instructions before choosing a base branch.
   Trace the failing value/state through code and inspect nearby history. Do not
   assume that the default branch is deployed or that an existing PR is released.
3. Report the root cause with file/line evidence, affected behavior, proposed fix,
   risks and any suggested data cleanup. Never perform data cleanup automatically.
4. After the user authorizes a fix, use sidequest-start and a scoped branch. Choose
   --prefix hotfix only when requested. Reproduce using fixtures, observe the failing
   test, implement the smallest fix and run the project's focused and full checks
   (tests and lint under Project commands, when listed).
5. Hand off to sidequest-ship when ready. State what is local, committed, pushed,
   merged or deployed only when there is evidence for each state.
