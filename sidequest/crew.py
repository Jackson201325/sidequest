"""Crew: one worker agent per ticket worktree that runs the Sidequest steps until it needs the person,
and a manager agent that watches every ticket. Workers report through run.json (sidequest.runs).
No Git, Jira or terminal policy lives here; callers pass the launcher and worktree lookup."""
import json
import shlex
from pathlib import Path

from sidequest import runs

DEFAULT_MANAGER = "claude --model claude-opus-5-5"
DEFAULT_WORKER = "claude --model claude-sonnet-5-5"
DEFAULT_CHALLENGER = "claude --model claude-opus-5-5"


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
        if record.get("state") == "ready" and record["step"] in ("ship-check", "challenge"):
            return runs.STEPS[runs.STEPS.index(record["step"]) + 1]
        return record["step"]
    return "implement" if has_plan else "start"


def challenge_prompt(key, record, data):
    """The challenger (a stronger model) reviews the worker's finished ship-check before the person ships."""
    report = f"{data} run {key} set"
    note = f" The worker's note: {record['note']}." if record and record.get("note") else ""
    return "\n".join([
        f"You are the Sidequest crew challenger for {key}. Work only in this worktree.{note}",
        "Another agent implemented this ticket and says it is ready to ship. Assume every part of its work "
        "is wrong until you prove it right: the criteria it claims, the code, the tests and the QA evidence.",
        f"1. Run `{data} run {key} ran challenge`. Exit 0 means you already challenged this same code: "
        "say so and stop.",
        f"2. Run `{report} challenge working`.",
        f"3. Read the Jira ticket (`{data} ticket {key} --json`), plan.md, the questions and the plan's Updates. "
        "Write each acceptance criterion again in your own words. Do not trust the worker's summary.",
        "4. Read the full branch diff against its base and the uncommitted changes. For each criterion, find "
        "the code and the test that prove it. Look for missed cases, wrong assumptions, dead code, scope "
        "creep, security and data risks, and tests that pass without checking the behaviour.",
        f"5. Run the focused tests and `{data} ship-check`. Try to break the change with the cases you found.",
        "6. Fix each defect that is inside the ticket's scope, with a test that failed before the fix. Ask "
        "before a fix that changes product behaviour or the plan.",
        f"7. Write the ticket folder's challenge.md: each claim you checked, proved or wrong, the evidence, "
        "and what you fixed.",
        f"Then run `{report} challenge ready --note \"<n> wrong, <m> fixed, <k> open\"`, give a short summary "
        "and stop. Open items that need the person: report waiting with them instead.",
        f"Questions and permissions: run `{report} challenge waiting --note \"<what you need>\"`, then ask.",
        "Never commit, push, open a PR, post comments or change Jira. The person ships with sidequest-ship.",
    ])


def worker_prompt(key, record, data, has_plan=False):
    step = first_step(record, has_plan)
    if step == "challenge":
        return challenge_prompt(key, record, data)
    report = f"{data} run {key} set"
    lines = [
        f"You are the Sidequest crew worker for {key}. Work only in this worktree.",
        "Run these steps in order. Each step is a Sidequest workflow. Before each step, run "
        f"`{data} run {key} ran <step>`: exit 0 means the step already finished on this same code, so skip it "
        "and say so; otherwise run it.",
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
        "5. challenge: a separate challenger agent reviews your work. Never run it yourself.",
        f"6. qa-review: only after the person shipped (an open PR). Run `{report} qa-review working`, then "
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
        "Never commit, push, open a PR, post comments or change Jira. One exception: finishing the rebase or "
        "merge that update-branch started. Skip the start workflow's Jira move: leave the ticket's status "
        "as it is, even when that workflow says to move it. Never push or "
        "force-push. The person ships with sidequest-ship.",
    ]
    if record:
        note = f" Its note: {record['note']}." if record.get("note") else ""
        lines += ["", f"This ticket already has a run: step {record['step']}, state {record['state']}.{note} "
                  f"Read `{data} run {key} show`, the plan's Updates, the questions and `git status` first. "
                  f"When `{data} review-app {key} --json` shows an open PR, the person already shipped: "
                  "continue from qa-review. "
                  f"Continue from {step}."]
    else:
        lines += ["", f"Begin at {step}."]
    return "\n".join(lines)


AGAIN_HINT = "use --again to start it anyway"


def dispatch(keys, find_worktree, tickets, launch, data, at, again=False, dry_run=False, waiting=None,
             challenger=None):
    """Start a worker for each ticket that has its own worktree. Returns (lines, any skipped).
    waiting(key) gives a reason the ticket is with someone else (review, QA, another assignee), or None.
    challenger(key, path, prompt) starts the challenge step; without it, launch does."""
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
        reason = waiting(key) if waiting and not again else None
        if reason:
            lines.append(f"skip {key}: {reason}; {AGAIN_HINT}")
            skipped = True
            continue
        has_plan = (tickets / key / "plan.md").is_file()
        prompt = worker_prompt(key, record, data, has_plan)
        if dry_run:
            lines.append(f"would start {key} in {found['path']} at {first_step(record, has_plan)}")
            continue
        step = first_step(record, has_plan)
        agent = "challenger" if step == "challenge" and challenger else "worker"
        (challenger if agent == "challenger" else launch)(key, found["path"], prompt)
        runs.update(path, key, step, "queued", "Dispatched by sidequest crew", at)
        lines.append(f"{key}: {agent} started at {step}")
    return lines, skipped


def manager_prompt(data, sidequest):
    return (f"You are the Sidequest crew manager. Run `{data} skill manage` and follow the instructions it "
            f"prints. Start workers with `{sidequest} crew KEY...`; see every worker with "
            f"`{sidequest} crew --status`. Then wait for my questions.")
