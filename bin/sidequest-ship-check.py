#!/usr/bin/env python3
"""sidequest-data ship-check — the mechanical part of "ship DEMO-###", in one short report.

  sidequest-data ship-check                 check this worktree's branch against origin/main
  sidequest-data ship-check --no-fetch      skip `git fetch origin` (offline / sandbox)
  sidequest-data ship-check --base REF      compare with REF instead of origin/main
  sidequest-data ship-check --json          machine-readable output

Reports: ticket key, uncommitted changes, ahead/behind, commits, changed files, and flags for
things that usually don't belong in the PR (local/tool files, lockfiles without a Gemfile/package
change, formatting-only files, db/schema.rb tables no migration of this branch touches), migrations
that may not be reversible, debug leftovers / focused specs / TODOs / possible secrets on added lines,
AI attribution in commit messages, the specs to run for the changed app files, and for UI changes
whether the QA screenshots in tickets/DEMO-###/qa (from `sidequest-data qa-shot`) still match the code.
It only reads: no commits, no pushes, no Jira or GitHub calls. Deciding what is in scope stays
with the person or agent reading the report.
"""
import argparse, functools, json, os, re, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sidequest import config, gitutil, qa as qa_evidence
from sidequest.ticket_keys import branch_ticket

LOCAL = re.compile(r"^(\.claude/|\.codex/|\.opencode/|\.sidequest/|\.env|AGENTS\.md$|config/master\.key$|"
                   r"config/credentials/.*\.key$|log/|.*\.log$|tmp/|coverage/|\.idea/|\.vscode/|"
                   r".*\.swp$|(.*/)?\.DS_Store$|node_modules/)")
LOCKS = {"Gemfile.lock": "Gemfile", "yarn.lock": "package.json", "package-lock.json": "package.json"}
DEBUG = [
    (re.compile(r"\bbinding\.(pry|irb)\b|\bbyebug\b|^\s*debugger\b|\bconsole\.log\("), "debug call"),
    (re.compile(r"^\s*(puts|pp|p)\s|\bRails\.logger\.debug\b"), "print/debug output"),
    (re.compile(r"\b(fit|fdescribe|fcontext)\b|focus:\s*true|:focus\b"), "focused spec"),
    (re.compile(r"\b(TODO|FIXME|XXX|HACK)\b"), "TODO added"),
    (re.compile(r"AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY|"
                r"(api_?key|secret|token|password)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]", re.I), "possible secret"),
]
ATTRIB = re.compile(r"claude|codex|opencode|openai|anthropic|co-authored-by: .*(bot|ai)\b|generated (with|by)", re.I)
# "DEMO-766 (2): ..." breadcrumbs that sidequest-start leaves in the code; they must be gone before a PR.
PLAN_MARKER = r"[A-Z][A-Z0-9_]*-[0-9]+ \([0-9]+\):"
TABLE_RE = re.compile(r"""(?:create_table|change_table|drop_table|add_column|remove_column|rename_column|change_column\w*|
                          add_index|remove_index|add_reference|remove_reference|add_belongs_to|add_timestamps|
                          add_foreign_key|remove_foreign_key|add_check_constraint|rename_table)\s*\(?\s*[:"'](\w+)""", re.X)


git = functools.partial(gitutil.git, tool="ship-check")


def added_lines(rng, path=None):
    """[(path, line_no, text)] for lines added in the range."""
    args = ["diff", "-U0", "--no-color", rng, "--"] + ([path] if path else [])
    out, cur, n, res = git(*args), None, 0, []
    for l in out.splitlines():
        if l.startswith("+++ "):
            cur = l[6:] if l.startswith("+++ b/") else None
        elif l.startswith("@@"):
            n = int(re.search(r"\+(\d+)", l).group(1))
        elif cur and l.startswith("+"):
            res.append((cur, n, l[1:])); n += 1
    return res


def schema_tables(rng, base_ref):
    """Tables whose lines changed in db/schema.rb, plus whether the version line changed."""
    out = git("diff", "-U0", "--no-color", rng, "--", "db/schema.rb")
    if not out:
        return set(), False
    new = git("show", "HEAD:db/schema.rb", check=False).splitlines()
    old = git("show", base_ref + ":db/schema.rb", check=False).splitlines()

    def table_at(lines, i):
        for j in range(min(i, len(lines)) - 1, -1, -1):
            m = re.match(r'\s*(?:create_table|add_foreign_key)\s+"(\w+)"', lines[j])
            if m:
                return m.group(1)
            if lines[j].startswith("  ") is False and j < i - 1:
                break
        return None

    tables, version = set(), False
    for l in out.splitlines():
        if l.startswith("@@"):
            m = re.search(r"-(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))?", l)
            o, oc, n, nc = int(m.group(1)), int(m.group(2) or 1), int(m.group(3)), int(m.group(4) or 1)
            for i in range(n, n + nc):
                if i - 1 < len(new) and "ActiveRecord::Schema" in new[i - 1]:
                    version = True
                t = table_at(new, i) if nc else None
                if t: tables.add(t)
            for i in range(o, o + oc):
                t = table_at(old, i) if oc else None
                if t: tables.add(t)
    return tables, version


def spec_for(path):
    """Candidate spec files for an app/lib file (controllers are usually covered by request specs)."""
    m = re.match(r"app/(\w+)/(.+)\.rb$", path)
    if m:
        kind, rest = m.groups()
        c = ["spec/%s/%s_spec.rb" % (kind, rest)]
        if kind == "controllers":
            c.append("spec/requests/%s_spec.rb" % re.sub(r"_controller$", "", rest))
        return c
    m = re.match(r"lib/(.+)\.(rb|rake)$", path)
    return ["spec/lib/%s_spec.rb" % m.group(1), "spec/lib/%s_rake_spec.rb" % m.group(1)] if m else []


def main():
    ap = argparse.ArgumentParser(prog="sidequest-data ship-check", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default=config.base_ref())
    ap.add_argument("--no-fetch", action="store_true", default=True)
    ap.add_argument("--fetch", action="store_false", dest="no_fetch", help="Explicitly refresh origin before checking")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    os.chdir(git("rev-parse", "--show-toplevel").strip())
    r = {"warnings": []}
    branch = git("branch", "--show-current").strip()
    r["branch"] = branch
    r["ticket"] = branch_ticket(branch, config.get("jira", "projects", []))
    if not r["ticket"]:
        r["warnings"].append("branch name has no ticket key")

    if not a.no_fetch:
        p = subprocess.run(["git", "fetch", "--quiet", "origin"], capture_output=True, text=True, timeout=120)
        if p.returncode != 0:
            r["warnings"].append("git fetch failed, %s may be stale: %s" % (a.base, p.stderr.strip()[:200]))

    rng = a.base + "...HEAD"
    behind, ahead = git("rev-list", "--left-right", "--count", rng).split()
    r["ahead"], r["behind"] = int(ahead), int(behind)
    r["commits"] = git("log", "--oneline", "--no-decorate", a.base + "..HEAD").splitlines()
    r["uncommitted"] = [l for l in git("status", "--porcelain").splitlines() if l.strip()]

    # files
    files = []
    numstat = {}
    for l in git("diff", "--numstat", rng).splitlines():
        ad, de, p = l.split("\t", 2)
        numstat[p] = (ad, de)
    for l in git("diff", "--name-status", rng).splitlines():
        parts = l.split("\t")
        st, p = parts[0][0], parts[-1]
        ad, de = numstat.get(p, ("?", "?"))
        files.append({"status": st, "path": p, "added": ad, "deleted": de, "flags": []})
    paths = {f["path"] for f in files}
    migrations = [f["path"] for f in files if f["path"].startswith("db/migrate/") and f["status"] in "AM"]

    mig_tables = set()
    for mp in migrations:
        mig_tables |= set(TABLE_RE.findall(git("show", "HEAD:" + mp, check=False)))
    s_tables, s_version = schema_tables(rng, a.base) if "db/schema.rb" in paths else (set(), False)

    for f in files:
        p, fl = f["path"], f["flags"]
        if LOCAL.match(p):
            fl.append("local/tool file: should not be in the PR")
        if p in LOCKS and LOCKS[p] not in paths:
            fl.append("lockfile changed without %s: dependency intended?" % LOCKS[p])
        if p == "package.json":
            fl.append("package.json changed: dependency intended?")
        if f["status"] == "M" and not re.search(r"\.(png|jpe?g|gif|pdf|ico)$", p):
            if subprocess.run(["git", "diff", "--quiet", "-w", "--ignore-blank-lines", rng, "--", p]).returncode == 0:
                fl.append("whitespace/formatting-only changes")
        if p == "db/schema.rb":
            if not migrations:
                fl.append("schema changed but this branch adds no migration: likely leaked from another branch")
            else:
                leaked = sorted(s_tables - mig_tables)
                if leaked:
                    fl.append("tables changed that no migration here touches (likely other branches): " + ", ".join(leaked))
                ver = re.search(r"define\(version:\s*([\d_]+)", git("show", "HEAD:db/schema.rb", check=False))
                stamps = [m_.group(1) for m_ in (re.match(r"db/migrate/(\d+)", path) for path in migrations) if m_]
                newest = max(stamps, default="")
                if ver and newest and ver.group(1).replace("_", "") < newest:
                    fl.append("schema version %s is older than migration %s: schema.rb not regenerated?" % (ver.group(1), newest))
        if p == ".gitignore":
            fl.append(".gitignore changed: if it's only for your machine, use .git/info/exclude instead")
        if p in migrations:
            src = git("show", "HEAD:" + p, check=False)
            if re.search(r"def up\b", src) and not re.search(r"def down\b", src):
                fl.append("migration has `up` without `down`: not reversible")
            elif re.search(r"def change\b", src) and re.search(r"\bexecute\b|remove_column\s+:\w+,\s*:\w+\s*$|change_column\b", src, re.M) \
                    and "reversible" not in src:
                fl.append("`change` uses execute/change_column/remove_column without type: check reversibility")
    r["files"] = files

    # added-line checks (skip specs for print checks? keep all, but ignore lockfiles/schema)
    hits = []
    for p, n, text in added_lines(rng):
        if p in LOCKS or p == "db/schema.rb" or p.endswith((".md", ".lock", ".svg")):
            continue
        for rx, label in DEBUG:
            if label == "print/debug output" and (not p.endswith(".rb") or p.startswith(("lib/tasks/", "db/", "bin/"))):
                continue
            if label == "focused spec" and not p.startswith("spec/"):
                continue
            if rx.search(text):
                hits.append({"path": p, "line": n, "kind": label, "text": text.strip()[:120]})
    r["added_line_flags"] = hits

    # plan markers anywhere in the working tree (committed or not), excluding local/tool files
    grep = git("grep", "--untracked", "-nIE", PLAN_MARKER, "--", ".", check=False)
    r["plan_markers"] = [l[:160] for l in grep.splitlines() if not LOCAL.match(l.split(":", 1)[0])]

    msgs = git("log", "--format=%h%x00%B%x01", a.base + "..HEAD")
    attrib = []
    for chunk in msgs.split("\x01"):
        if "\x00" not in chunk:
            continue
        sha, body = chunk.strip().split("\x00", 1)
        for l in body.splitlines():
            if ATTRIB.search(l):
                attrib.append({"commit": sha, "line": l.strip()[:120]})
    r["attribution"] = attrib

    specs_run, no_spec = set(), []
    for f in files:
        p = f["path"]
        if f["status"] == "D":
            continue
        if p.startswith("spec/") and p.endswith("_spec.rb"):
            specs_run.add(p)
        cands = spec_for(p)
        found = [c for c in cands if os.path.exists(c)]
        if not found and p.startswith("lib/tasks/") and p.endswith(".rake"):
            stem = os.path.basename(p)[:-5]
            d = os.path.join("spec", os.path.dirname(p))
            found = sorted(os.path.join(d, f) for f in (os.listdir(d) if os.path.isdir(d) else [])
                           if f.startswith(stem + "_") and f.endswith("_spec.rb"))
        specs_run.update(found)
        if cands and not found and not p.startswith(("app/views/", "app/assets/", "app/javascript/", "app/controllers/concerns/")):
            no_spec.append(p)
    r["specs_to_run"] = sorted(specs_run)
    r["no_spec"] = no_spec

    uncommitted_paths = [l[3:].split(" -> ")[-1] for l in r["uncommitted"] if len(l) > 3]
    r["ui_files"] = qa_evidence.ui_files({f["path"] for f in files if f["status"] != "D"} | set(uncommitted_paths))
    r["qa"] = qa_evidence.status(r["ticket"], r["ui_files"])

    if a.json:
        print(json.dumps(r, indent=1))
        return 0

    out = []
    out.append("ship-check: %s (%s) vs %s" % (r["ticket"] or "?", branch, a.base))
    for w in r["warnings"]:
        out.append("  ! " + w)
    out.append("ahead %d, behind %d%s" % (r["ahead"], r["behind"], "  (offer a rebase)" if r["behind"] else ""))
    if r["uncommitted"]:
        out.append("UNCOMMITTED (%d):" % len(r["uncommitted"]))
        out += ["  " + l + ("   <- local/tool file" if LOCAL.match(l[3:]) else "") for l in r["uncommitted"][:25]]
    out.append("COMMITS (%d):" % len(r["commits"]))
    out += ["  " + c for c in r["commits"][:30]]
    out.append("FILES (%d):" % len(files))
    for f in files:
        out.append("  %s %-60s +%s -%s" % (f["status"], f["path"], f["added"], f["deleted"]))
        out += ["      ! " + x for x in f["flags"]]
    out.append("ADDED-LINE FLAGS: " + ("none" if not hits else str(len(hits))))
    out += ["  %s:%d %s: %s" % (h["path"], h["line"], h["kind"], h["text"]) for h in hits]
    out.append("PLAN MARKERS: " + ("none" if not r["plan_markers"] else
                                    "%d (remove before the PR)" % len(r["plan_markers"])))
    out += ["  " + m for m in r["plan_markers"]]
    out.append("AI ATTRIBUTION IN COMMITS: " + ("none" if not attrib else str(len(attrib))))
    out += ["  %s %s" % (x["commit"], x["line"]) for x in attrib]
    out.append("SPECS TO RUN: " + (" ".join(r["specs_to_run"]) or "none found"))
    if no_spec:
        out.append("CHANGED WITHOUT A MATCHING SPEC: " + ", ".join(no_spec))
    out.append("UI CHANGES: " + ("none" if not r["ui_files"] else "%d file(s)" % len(r["ui_files"])))
    out += ["  " + p for p in r["ui_files"][:15]]
    q = r["qa"]
    if q["status"] == "missing":
        out.append("QA SCREENSHOTS: missing (run sidequest-qa-local; it saves them to %s)" % q.get("dir"))
    elif q["status"] == "current":
        out.append("QA SCREENSHOTS: %d current (captured at %s)" % (len(q["screenshots"]), str(q.get("commit"))[:9]))
        out += ["  " + p for p in q["screenshots"]]
    elif q["status"] == "stale":
        out.append("QA SCREENSHOTS: stale, %s (re-run sidequest-qa-local)" % q.get("reason"))
        out += ["  changed: " + p for p in q.get("changed_since", [])[:15]]
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
