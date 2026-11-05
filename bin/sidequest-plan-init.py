#!/usr/bin/env python3
"""sidequest-data plan-init DEMO-### [--summary TEXT] [--type TYPE]: create the ticket's plan skeleton, never overwrite.

Writes the configured tickets folder/DEMO-###/plan.md (SIDEQUEST_TICKETS_DIR overrides the folder) with the
sections sidequest-start fills in. Prints CREATED <path> or EXISTS <path>.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sidequest.qa import plan_path
from sidequest.workspaces import KEY
from sidequest import config

TEMPLATE = """# {title}

## Ticket
- Key: {key} · {link}
- Type: {type}
- Summary: {summary}

## What's going on
(Plain language for someone who hasn't read the ticket: who hits this, what they see vs. should see, why it matters, history. Then 2-4 concrete examples; start made-up ones with "(example)". No file names or code here.)

## Code flow
(Numbered spots in the order the code runs, matching the markers in the code: `n. path/file:line  function  # why`. Then one sentence tying them together.)

## Acceptance criteria
- [ ] (From the ticket; mark drafted ones *(inferred)*.)

## Approach
1. (Numbered steps with files; refer to Code flow spots by number.)

## Tests
(Tests to add or update, exact commands from the target project, and expected results.)

## Risks
(Migrations, backfills, background jobs, external integrations, anything that auto-deploys.)

## Open questions
(For the ticket author, if any.)

## PR
Targets the base branch configured by the target project. Ticket link: {link}. Body follows `.github/pr_template.md`; ship with `sidequest-ship`.
"""


def main():
    parser = argparse.ArgumentParser(prog="sidequest-data plan-init")
    parser.add_argument("key")
    parser.add_argument("--summary", default="")
    parser.add_argument("--type", default="", dest="issue_type")
    options = parser.parse_args()
    key = options.key.upper()
    if not KEY.fullmatch(key):
        parser.error("expected a Jira key such as APP-123")
    path = plan_path(key)
    if path.exists():
        print("EXISTS " + str(path))
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = options.summary.strip()
    path.write_text(TEMPLATE.format(
        title=(key + " " + summary).strip(), key=key, link=(config.get('jira', 'site').rstrip('/') + '/browse/' + key) if config.get('jira', 'site') else '(Jira not configured)',
        type=options.issue_type or "(see ticket)", summary=summary or "(one line)"))
    print("CREATED " + str(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
