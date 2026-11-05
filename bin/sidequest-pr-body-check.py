#!/usr/bin/env python3
"""sidequest-data pr-body-check FILE | --pr N: catch AI attribution and leftover local paths in a PR text.

FILE (before `gh pr create`): attribution only; local screenshot paths are expected there because
`gh --attach` swaps them. --pr N (after creating): checks the title and body GitHub stored, which must
have no attribution and no local paths, and lists the changed files.
Exit 0 clean, 1 findings, 2 usage or gh failure.
"""
import argparse
import json
import re
import subprocess
import sys

ATTRIB = re.compile(r"claude|codex|opencode|openai|anthropic|generated (with|by)|co-authored", re.I)
LOCAL_PATH = re.compile(r"/Users/|/home/|tickets/[A-Z][A-Z0-9_]*-")


def findings(body, title=None, local_paths=False):
    out = []
    if title is not None and ATTRIB.search(title):
        out.append("ATTRIBUTION title: " + title.strip()[:100])
    for number, line in enumerate(body.splitlines(), 1):
        if ATTRIB.search(line):
            out.append("ATTRIBUTION line %d: %s" % (number, line.strip()[:100]))
        if local_paths and LOCAL_PATH.search(line):
            out.append("LOCAL PATH line %d: %s" % (number, line.strip()[:100]))
    return out


def main():
    parser = argparse.ArgumentParser(prog="sidequest-data pr-body-check")
    parser.add_argument("file", nargs="?")
    parser.add_argument("--pr", type=int)
    options = parser.parse_args()
    if bool(options.file) == bool(options.pr):
        parser.error("give a body FILE or --pr N")
    files = None
    if options.pr:
        p = subprocess.run(["gh", "pr", "view", str(options.pr), "--json", "title,body,files"],
                           capture_output=True, text=True)
        if p.returncode != 0:
            print("sidequest-data: gh pr view failed: " + p.stderr.strip(), file=sys.stderr)
            return 2
        data = json.loads(p.stdout)
        found = findings(data.get("body") or "", data.get("title") or "", local_paths=True)
        files = [f["path"] for f in data.get("files") or []]
    else:
        try:
            text = open(options.file).read()
        except OSError as exc:
            print("sidequest-data: cannot read %s: %s" % (options.file, exc.strerror), file=sys.stderr)
            return 2
        found = findings(text)
    print("\n".join(found) if found else "OK: no AI attribution")
    if files is not None:
        print("FILES %d: %s" % (len(files), ", ".join(files)))
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
