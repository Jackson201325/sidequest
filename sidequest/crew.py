"""Crew: one worker agent per ticket worktree that runs the Sidequest steps until it needs the person,
and a manager agent that watches every ticket. Workers report through run.json (sidequest.runs).
No Git, Jira or terminal policy lives here; callers pass the launcher and worktree lookup."""
import json
import shlex
from pathlib import Path

from sidequest import runs

DEFAULT_MANAGER = "claude --model claude-opus-5-5"
DEFAULT_WORKER = "claude --model claude-sonnet-5-5"


def hook_settings(key, data):
    """Claude Code settings: each prompt marks the worker working; a finished turn or a permission
    request marks it waiting, unless the worker reported ready or failed itself."""
    def entry(event):
        return [{"hooks": [{"type": "command", "command": f"{data} run {key} hook {event}"}]}]
    return json.dumps({"hooks": {"UserPromptSubmit": entry("prompt"), "Stop": entry("stop"),
                                 "Notification": entry("notify")}})


def worker_command(command, key, data):
    """The worker's command line; Claude Code also gets the reporting hooks."""
    argv = shlex.split(command)
    if argv and Path(argv[0]).name == "claude":
        return command + " --settings " + shlex.quote(hook_settings(key, data))
    return command


def first_step(record, has_plan):
    if record and record.get("step") in runs.STEPS:
        if record["step"] == "ship-check" and record.get("state") == "ready":
            return "qa-review"  # The person ships in between; the review app needs the open PR.
        return record["step"]
    return "implement" if has_plan else "start"


def worker_prompt(key, record, data, has_plan=False):
    step = first_step(record, has_plan)
    report = f"{data} run {key} set"
    lines = [
        f"You are the Sidequest crew worker for {key}. Work only in this worktree.",
        "Run these steps in order. Each step is a Sidequest workflow:",
        f"1. start: run `{report} start working`, then `{data} skill start` and follow it. "
        "Skip this step when the ticket's plan.md exists.",
        f"2. implement: run `{report} implement working`, then `{data} skill implement` and follow it.",
        f"3. qa-local: run `{report} qa-local working`, then `{data} skill qa-local` and follow it. "
        f"Finish it with the screenshots from `{data} qa-shot {key}` and the ticket's qa/report.md. "
        "Skip this step only when the change has no UI part, and say so in the step's note.",
        f"4. ship-check: run `{report} ship-check working`, then bring the branch up to date with "
        f"`{data} update-branch --keep-conflicts`. Exit 3 means conflicts are open: resolve each listed file so "
        "both the base's change and this ticket's change survive, run the focused and full checks, then finish "
        "with the command it prints. When a conflict needs a product decision, run the abort command it prints, "
        f"then `{report} ship-check waiting --note \"Conflict in <files>: <the decision>\"` and ask. Exit 1 or 2: "
        f"report it as waiting with its message. Then run `{data} ship-check` and review its report and the full "
        "branch diff against the plan. Fix what is in scope and run the checks again. Do not run the ship workflow.",
        f"5. qa-review: only after the person shipped (an open PR). Run `{report} qa-review working`, then "
        f"`{data} review-app {key} --json`. With no open PR or no review app yet, run `{report} qa-review "
        "waiting --note \"Ship first: open the PR with sidequest-ship\"` and stop. Otherwise run "
        f"`{data} skill qa-review-app` and follow it. When the review login is not set, report waiting with "
        "the variables to set; never ask for a password in chat. Never update the PR screenshots yourself.",
        "",
        "Stop and wait for the person when you need them:",
        f"- A question blocks a criterion: log it with `{data} questions {key} add \"<question>\" --source crew "
        f"--context \"<why>\"`, run `{report} <step> waiting --note \"Q<n>: <short question>\"`, then ask it. "
        "Keep building the criteria it does not block before you ask.",
        f"- You need a permission, a credential or a decision outside the plan: run `{report} <step> waiting "
        "--note \"<what you need>\"`, then ask.",
        f"- A check fails and you cannot fix it inside the ticket's scope: run `{report} <step> failed "
        "--note \"<what failed>\"`, then explain.",
        f"When an answer comes, record it with `{data} questions {key} answer Q<n> \"<answer>\" --by <who>`, "
        "then continue from the same step.",
        "",
        f"When ship-check is clean, run `{report} ship-check ready --note \"<one line: what is ready>\"`, "
        "give a short summary (criteria, tests, checks, QA evidence, files) and stop. Do not start qa-review "
        "in the same run.",
        f"When qa-review is done, run `{report} qa-review ready --note \"<one line: review app result>\"`, "
        "present the evidence and stop.",
        "Never commit, push, open a PR, post comments or change Jira. Two exceptions: finishing the rebase or "
        "merge that update-branch started, and the start workflow's configured start move. Never push or "
        "force-push. The person ships with sidequest-ship.",
    ]
    if record:
        note = f" Its note: {record['note']}." if record.get("note") else ""
        lines += ["", f"This ticket already has a run: step {record['step']}, state {record['state']}.{note} "
                  f"Read `{data} run {key} show`, the plan's Updates, the questions and `git status` first. "
                  f"Continue from {step}."]
    else:
        lines += ["", f"Begin at {step}."]
    return "\n".join(lines)


def dispatch(keys, find_worktree, tickets, launch, data, at, again=False, dry_run=False):
    """Start a worker for each ticket that has its own worktree. Returns (lines, any skipped)."""
    lines, skipped = [], False
    for key in keys:
        found = find_worktree(key) or {"state": "none"}
        path = tickets / key / "run.json"
        if found.get("state") != "worktree":
            reason = ("its branch is in the main checkout; give it its own worktree" if found.get("state") == "main-checkout"
                      else f"no worktree yet; run sidequest start {key} first")
            lines.append(f"skip {key}: {reason}")
            skipped = True
            continue
        try:
            record = runs.read(path)
        except ValueError as exc:
            lines.append(f"skip {key}: {exc}")
            skipped = True
            continue
        if record and record["state"] in ("working", "queued") and not again:
            lines.append(f"skip {key}: a worker is already {record['state']} at {record['step']}; "
                         "use --again if it stopped")
            skipped = True
            continue
        has_plan = (tickets / key / "plan.md").is_file()
        prompt = worker_prompt(key, record, data, has_plan)
        if dry_run:
            lines.append(f"would start {key} in {found['path']} at {first_step(record, has_plan)}")
            continue
        launch(key, found["path"], prompt)
        runs.update(path, key, first_step(record, has_plan), "queued", "Dispatched by sidequest crew", at)
        lines.append(f"{key}: worker started at {first_step(record, has_plan)}")
    return lines, skipped


def manager_prompt(data, sidequest):
    return (f"You are the Sidequest crew manager. Run `{data} skill manage` and follow the instructions it "
            f"prints. Start workers with `{sidequest} crew KEY...`; see every worker with "
            f"`{sidequest} crew --status`. Then wait for my questions.")
