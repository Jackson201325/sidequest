#!/usr/bin/env python3
"""sidequest-data review-app [DEMO-###] [--pr N] [--json]: the ticket's Heroku review app (read-only).

Finds the open PR (by ticket key, PR number, or the current branch), then asks Heroku for its
review app. Prints the PR, the status (Web up, Building, Failed, Not provisioned…) and the URL.
Exit 0 when the app is up, 1 when it isn't ready or doesn't exist, 2 on errors.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sidequest import review_apps


def main():
    ap = argparse.ArgumentParser(prog="sidequest-data review-app", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("key", nargs="?")
    ap.add_argument("--pr", type=int)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    key = (a.key or "").upper()
    if re.fullmatch(r"\d+", key):
        key = "DEMO-" + key
    try:
        pr = review_apps.find_pr(key or None, a.pr)
        app = review_apps.review_app(pr["number"])
    except review_apps.ReviewAppError as exc:
        print("review-app: %s" % exc, file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps({"pr": pr, "review_app": app}, indent=1))
    else:
        print("PR #%d %s" % (pr["number"], pr["title"]))
        print("STATUS %s" % app.get("status"))
        if app.get("app"):
            print("APP %s" % app["app"])
        if app.get("url"):
            print("URL %s" % app["url"])
        if app.get("warning"):
            print("WARNING %s" % app["warning"])
    return 0 if app.get("status") == "Web up" else 1


if __name__ == "__main__":
    sys.exit(main())
