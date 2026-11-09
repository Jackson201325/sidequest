"""Queue evidence: the data the dashboard shows, its last good copies and which sources failed.

The UI thread owns an instance. Only `collect` may run in a worker thread; it changes nothing.
"""
import json
import subprocess
from pathlib import Path

from core import now
from sidequest.evidence import parse_time
from sidequest.snapshots import SnapshotStore, source_problem

SOURCES = {"jira": "Jira", "prs": "GitHub"}
EVERY = "all"
COMMENT_FIELDS = ("jira_comments", "jira_comment_total", "jira_comments_checked_at", "jira_changes")
EPOCH = parse_time("1970-01-01")


def read_json(path):
    try:
        data = json.loads(Path(path).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def newest(*copies):
    return max(copies, key=lambda data: parse_time(data.get("generated_at")) or EPOCH)


def failed_by_text(messages):
    """Failure sets for errors saved before they were recorded: a message that starts with a
    source label belongs to that source; any other message means the whole run failed."""
    failed = set()
    for message in map(str, messages):
        failed.add(next((name for name, label in SOURCES.items() if message.startswith(label)), EVERY))
    return failed


def own_failures(failures):
    """The failures of the sources the dashboard shows; `sidequest up` reports its own (sync) sources."""
    return {name: message for name, message in failures.items() if name in SOURCES}


class QueueEvidence:
    def __init__(self, store, snapshots, demo=None):
        """`demo` is (jira, prs, environments) sample data that replaces every stored copy."""
        self.store, self.snapshots = store, Path(snapshots)
        self.environment_error = store.source("heroku_error").get("message", "")
        self.worklog = store.source("worklog")
        self.windows = {}
        saved = store.source("refresh_errors")
        self.refresh_errors = saved.get("messages", [])
        self.failed_sources = set(saved["sources"]) if "sources" in saved else failed_by_text(self.refresh_errors)
        if demo:
            self.fallback = {}
            self.jira, self.prs, self.environments = demo
            return
        self.environments = store.source("heroku")
        self.fallback = read_json(self.snapshots / "standup.json")
        try:
            generation = SnapshotStore(self.snapshots).read()
            shared = generation.get("sources", {})
            checked, generated = parse_time(saved.get("checked_at")), parse_time(generation.get("generated_at"))
            if generated and (not checked or generated >= checked):
                failures = own_failures(generation.get("failures", {}))
                self.refresh_errors, self.failed_sources = list(failures.values()), set(failures)
        except (OSError, ValueError):
            shared = {}
        self.jira = newest(store.source("jira"), shared.get("jira", {}))
        self.prs = newest(store.source("prs"), read_json(self.snapshots / "pr-feedback.json"), shared.get("prs", {}))

    def collect(self, run):
        """Run the read-only collector. Returns (updates, messages, failed sources); changes nothing."""
        updates, messages, failed = {}, [], set()
        try:
            data = json.loads(run(["sidequest-data", "collect", "--json", "--out", str(self.snapshots)], timeout=300))
            if (not isinstance(data, dict) or not isinstance(data.get("sources"), dict)
                    or not isinstance(data.get("failures", {}), dict)):
                raise RuntimeError("Invalid shared snapshot; keeping previous data")
            failures = own_failures(data.get("failures", {}))
            messages.extend(str(message) for message in failures.values())
            failed.update(failures)
            for name, label in SOURCES.items():
                if name in failures:
                    continue
                if source_problem(name, data["sources"].get(name)):
                    messages.append(label + " unavailable; keeping previous data")
                    failed.add(name)
                else:
                    updates[name] = data["sources"][name]
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            messages.append(str(exc))
            failed.add(EVERY)
        return updates, messages, failed

    def finish_refresh(self, result):
        """Apply a `collect` result. Failed sources keep their previous data. Returns True when tickets change."""
        updates, messages, failed = result
        changed = any([self.apply(name, data) for name, data in updates.items()])
        self.refresh_errors, self.failed_sources = list(messages), set(failed)
        self.store.source("refresh_errors", {"messages": self.refresh_errors, "sources": sorted(self.failed_sources),
                                             "checked_at": now().isoformat()})
        return changed

    def failed(self, name):
        """Whether the last refresh failed for a source ("jira" or "prs")."""
        return EVERY in self.failed_sources or name in self.failed_sources

    def apply(self, name, data):
        """Merge and save one background result. Returns True when the ticket list must be rebuilt."""
        if name == "jira":
            previous = {ticket["key"]: ticket for ticket in self.jira.get("tickets", [])}
            for issue in data.get("tickets", []):
                for field in COMMENT_FIELDS:
                    if field not in issue and field in previous.get(issue.get("key"), {}):
                        issue[field] = previous[issue["key"]][field]
        if name in ("jira", "prs", "worklog"):
            self.store.source(name, data)
            setattr(self, name, data)
            return True
        if name == "worktrees":
            self.windows = data
            return True
        if name == "heroku":
            self.environments, self.environment_error = data, ""
            self.store.source("heroku", data)
            self.store.source("heroku_error", {"message": ""})
        elif name == "heroku_error":
            self.environment_error = data
            self.store.source("heroku_error", {"message": data, "at": now().isoformat()})
        else:
            raise ValueError("unknown queue evidence: " + name)
        return False
