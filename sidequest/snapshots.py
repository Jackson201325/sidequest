"""Validated, atomically published source snapshots. Runtime files are never tracked."""
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from sidequest.identity import TZ


def stamp():
    return datetime.now(TZ).isoformat(timespec="seconds")


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


REQUIRED_LISTS = {"prs": "open_prs", "jira": "tickets"}


def source_problem(name, data):
    """Why collected data cannot replace a source's last good copy, or None. Shared by
    publication and the dashboard, which reads the collector's output across a process."""
    if not isinstance(data, dict) or (name in REQUIRED_LISTS and not isinstance(data.get(REQUIRED_LISTS[name]), list)):
        return "invalid " + name + " snapshot"
    if name == "jira" and data.get("jira_available") is not True:
        return "Jira unavailable; existing file retained"
    return None


class SnapshotStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / "snapshot.json"

    def read(self):
        if not self.path.exists():
            return {"version": 1, "sources": {}, "failures": {}}
        data = json.loads(self.path.read_text())
        if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("sources"), dict):
            raise ValueError("unsupported snapshot; existing file retained")
        return data

    def publish(self, updates, failures=None):
        for name, data in updates.items():
            if not isinstance(data, dict) or not data.get("generated_at"):
                raise ValueError("source requires its own collection timestamp")
            collected = datetime.fromisoformat(str(data["generated_at"]).replace("Z", "+00:00"))
            if collected.tzinfo is None:
                raise ValueError("collection timestamp requires a timezone")
            problem = source_problem(name, data)
            if problem:
                raise ValueError(problem)
        previous = self.read()
        result = {"version": 1, "generated_at": stamp(),
                  "sources": {**previous["sources"], **updates}, "failures": failures or {}}
        atomic_write(self.path, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        return result
