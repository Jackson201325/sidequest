"""Per-ticket crew worker state: <tickets folder>/KEY/run.json.

Written only through `sidequest-data run` (by the worker, and by its Claude Code hooks);
`sidequest crew --status`, the manager and the dashboard read it.

    {"key": "APP-1", "step": "implement", "state": "waiting", "note": "Q2: Which copy?",
     "updated": "2026-11-11T10:05:00+00:00", "history": [{"at", "step", "state", "note"}, ...]}
"""
from datetime import datetime
import json
import os
import tempfile

STEPS = ("start", "implement", "qa-local", "ship-check", "qa-review")
STATES = ("queued", "working", "waiting", "ready", "failed")
LABELS = {"queued": "queued", "working": "working", "waiting": "waiting on you",
          "ready": "ready for you", "failed": "failed"}
# Attention order: the person's turn first.
ORDER = {"waiting": 0, "failed": 1, "ready": 2, "working": 3, "queued": 4}
HISTORY = 50
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
ACTIVE = ("working", "queued", "waiting")
HOOK_NOTES = {"stop": "The worker ended its turn and waits for you",
              "notify": "The worker asks for permission or input"}


def clean(text):
    return " ".join(str(text or "").split())


def read(path):
    """The record, or None when there is none. A damaged file raises ValueError."""
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    if not isinstance(data, dict) or data.get("state") not in STATES or data.get("step") not in STEPS:
        raise ValueError("Damaged run record " + str(path))
    return data


def _write(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".run-", suffix=".json")
    with os.fdopen(handle, "w") as stream:
        json.dump(record, stream, indent=2)
        stream.write("\n")
    os.replace(temporary, path)


def update(path, key, step, state, note, at):
    if step not in STEPS:
        raise ValueError("Unknown step " + repr(step) + "; known: " + ", ".join(STEPS))
    if state not in STATES:
        raise ValueError("Unknown state " + repr(state) + "; known: " + ", ".join(STATES))
    record = read(path) or {"key": key.upper(), "history": []}
    entry = {"at": at, "step": step, "state": state, "note": clean(note)}
    record.update(key=key.upper(), step=step, state=state, note=entry["note"], updated=at)
    record["history"] = (record.get("history") or [])[-(HISTORY - 1):] + [entry]
    _write(path, record)
    return record


def hook(path, event, at):
    """Apply a Claude Code hook event. A turn that ends while working means the worker waits for the
    person; a state the worker reported itself (ready, failed, waiting) is kept. No record: no change."""
    record = read(path)
    if not record:
        return None
    state = record["state"]
    if event == "prompt" and state != "working":
        return update(path, record["key"], record["step"], "working", "", at)
    if event in HOOK_NOTES and state in ("working", "queued"):
        return update(path, record["key"], record["step"], "waiting", HOOK_NOTES[event], at)
    return record


def glyph(state, frame):
    """Animation frame for a state: working spins, waiting blinks, queued and finished stay still."""
    if state == "working":
        return SPINNER[frame % len(SPINNER)]
    if state == "waiting":
        return "●" if frame // 4 % 2 == 0 else "○"
    return {"queued": "◌", "ready": "✓", "failed": "✗"}[state]


def track(step, state, frame):
    """'✓ start  ✓ implement  ⠹ qa-local  · ship-check  · qa-review'"""
    current = STEPS.index(step)
    return "  ".join(("✓" if i < current else glyph(state, frame) if i == current else "·") + " " + name
                     for i, name in enumerate(STEPS))


def age(updated, clock):
    try:
        seconds = (clock - datetime.fromisoformat(updated)).total_seconds()
    except (TypeError, ValueError):
        return "?"
    minutes = max(0, int(seconds // 60))
    if minutes < 1:
        return "now"
    if minutes < 60:
        return f"{minutes}m"
    if minutes < 48 * 60:
        return f"{minutes // 60}h"
    return f"{minutes // 1440}d"


def summary(record, clock):
    """'implement · waiting on you · 12m · Q1: Copy?'"""
    parts = [record["step"], LABELS[record["state"]], age(record.get("updated"), clock)]
    return " · ".join(parts + ([record["note"]] if record.get("note") else []))


def all_records(folder):
    """Every ticket's record, the person's turn first, then the oldest update first."""
    found = []
    for path in sorted(folder.glob("*/run.json")) if folder.is_dir() else []:
        try:
            record = read(path)
        except (OSError, ValueError):
            continue
        if record:
            found.append(record)
    return sorted(found, key=lambda r: (ORDER[r["state"]], r.get("updated") or ""))


def table(records, clock):
    if not records:
        return ["No crew workers yet. Start one with: sidequest crew APP-123"]
    width = max(len(r["key"]) for r in records)
    return [f"{r['key']:<{width}}  {r['step']}  {LABELS[r['state']]}  {age(r.get('updated'), clock)}"
            + (f"  {r['note']}" if r.get("note") else "") for r in records]
