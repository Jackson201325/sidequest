#!/usr/bin/env python3
"""sidequest-data questions KEY ...: the ticket's decision record of questions, answers and decisions.

Writes only <tickets folder>/KEY/questions.md (SIDEQUEST_TICKETS_DIR overrides the folder).
Never posts to Jira, GitHub or chat. The dashboard shows the file in its Questions tab (c).

  sidequest-data questions APP-123 list [--json]
  sidequest-data questions APP-123 add "Question?" [--context WHY] [--source sidequest-start]
  sidequest-data questions APP-123 asked Q1 [--to WHO] [--via "Jira comment"]
  sidequest-data questions APP-123 answer Q1 "What they said" [--by WHO] [--via Slack] [--decision WHAT_WE_DID]
  sidequest-data questions APP-123 decision Q1 "What was done because of the answer"

Output: ADDED Q3 <path>, EXISTS Q2 <path> (already logged), UPDATED Q1 <path>; errors exit 1.
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sidequest import questions
from sidequest.identity import TZ
from sidequest.qa import ticket_dir
from sidequest.ticket_keys import is_key


def main():
    parser = argparse.ArgumentParser(prog="sidequest-data questions", description=__doc__.split("\n")[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument("key")
    parser.add_argument("--date", help="YYYY-MM-DD to record (default: today in the configured timezone)")
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list")
    listing.add_argument("--json", action="store_true")
    add = commands.add_parser("add")
    add.add_argument("question")
    add.add_argument("--context", default="")
    add.add_argument("--source", default="")
    asked = commands.add_parser("asked")
    asked.add_argument("id")
    asked.add_argument("--to", default="")
    asked.add_argument("--via", default="")
    answer = commands.add_parser("answer")
    answer.add_argument("id")
    answer.add_argument("reply")
    answer.add_argument("--by", default="")
    answer.add_argument("--via", default="")
    answer.add_argument("--decision", default="")
    decision = commands.add_parser("decision")
    decision.add_argument("id")
    decision.add_argument("text")
    options = parser.parse_args()
    key = options.key.upper()
    if not is_key(key):
        parser.error("expected a Jira key such as APP-123")
    today = options.date or datetime.now(TZ).date().isoformat()
    path = ticket_dir(key) / "questions.md"
    try:
        if options.command == "list":
            items = questions.parse(path.read_text()) if path.exists() else []
            if options.json:
                print(json.dumps([{k: v for k, v in i.items() if k not in ("line", "end", "status_line")}
                                  for i in items], indent=2))
            elif not items:
                print("No questions logged for " + key)
            else:
                print("\n".join(questions.view_lines(items, [], "")).rstrip())
            return 0
        if options.command == "add":
            qid, created = questions.add(path, key, options.question, today, options.context, options.source)
            print(("ADDED " if created else "EXISTS ") + qid + " " + str(path))
            return 0
        if options.command == "asked":
            qid = questions.asked(path, options.id, today, options.to, options.via)
        elif options.command == "answer":
            qid = questions.answer(path, options.id, options.reply, today, options.by, options.via, options.decision)
        else:
            qid = questions.decide(path, options.id, options.text, today)
        print("UPDATED " + qid + " " + str(path))
        return 0
    except (ValueError, LookupError) as exc:
        print("sidequest-data questions: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
