"""Install rendered canonical skills explicitly, preserving user edits."""
import hashlib
import json
from pathlib import Path
import shlex

ROOT = Path(__file__).resolve().parents[1]


def render(path):
    return path.read_text().replace('{{SIDEQUEST_DATA}}', shlex.quote(str(ROOT / 'bin/sidequest-data'))).replace('{{SIDEQUEST_HOME}}', shlex.quote(str(ROOT)))


def install(destination, apply=False, check=False):
    destination = Path(destination).expanduser()
    state_path = destination / '.sidequest-skill-state.json'
    previous = json.loads(state_path.read_text()) if state_path.is_file() else {}
    state, changes, pending = {}, [], []
    for source in sorted((ROOT / 'agents/skills').glob('sidequest-*/SKILL.md')):
        name = source.parent.name
        target = destination / name / 'SKILL.md'
        wanted = render(source)
        current = target.read_text() if target.is_file() else None
        digest = hashlib.sha256(current.encode()).hexdigest() if current is not None else None
        if current != wanted:
            changes.append(str(target))
            if apply and current is not None and previous.get(name) != digest:
                raise ValueError('Skill has user edits or is unmanaged; refusing to overwrite ' + str(target))
        state[name] = hashlib.sha256(wanted.encode()).hexdigest()
        pending.append((target, wanted))
    if not state:
        raise ValueError('Canonical skills are missing')
    if apply:
        for target, wanted in pending:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(wanted)
        state_path.write_text(json.dumps(state, indent=2) + '\n')
    return changes
