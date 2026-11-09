"""Canonical skills: the generic workflow plus the current project's additions, and installed stubs
that load them at run time. Installation is explicit and preserves user edits."""
import hashlib
import json
from pathlib import Path
import shlex

from sidequest import config

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / 'agents/skills'
DATA = shlex.quote(str(ROOT / 'bin/sidequest-data'))


def render(path):
    return path.read_text().replace('{{SIDEQUEST_DATA}}', DATA).replace('{{SIDEQUEST_HOME}}', shlex.quote(str(ROOT)))


def names():
    """Workflow names: ship for agents/skills/sidequest-ship."""
    return sorted(path.parent.name.removeprefix('sidequest-') for path in SKILLS.glob('sidequest-*/SKILL.md'))


def source(name):
    short = name.removeprefix('sidequest-')
    if short not in names():
        raise ValueError('Unknown skill ' + repr(name) + '; known: ' + ', '.join(names()))
    return short, SKILLS / ('sidequest-' + short) / 'SKILL.md'


def _parts(text):
    """(front matter including its --- lines, body) of a SKILL.md."""
    if text.startswith('---\n') and '\n---\n' in text[4:]:
        end = text.index('\n---\n', 4) + 5
        return text[:end], text[end:].lstrip('\n')
    return '', text


def addon_path(short, suffix='.md'):
    return config.PROJECTS_DIR / config.PROJECT / 'skills' / (short + suffix) if config.PROJECT else None


def commands_block():
    """The project's configured checks and app booking, which the generic steps refer to."""
    lines = []
    if config.get('checks', 'test'):
        lines.append('- Tests: `' + config.get('checks', 'test') + '` ({files}: the test files to run)')
    if config.get('checks', 'lint'):
        lines.append('- Lint: `' + config.get('checks', 'lint') + '`')
    if config.get('app', 'switch_command'):
        lines.append('- Shared app: run `' + DATA + ' app` before tests or opening the app, and `' + DATA +
                     ' app --release` when done, also after a failure (exit 75: another worktree has it; retry or '
                     'use `app --wait`; never `--force`).')
    if not lines:
        return ''
    return ('## Project commands: ' + (config.PROJECT or 'this project') + '\n\n'
            'Where the steps below say tests, lint or the app, use these.\n\n' + '\n'.join(lines) + '\n\n')


def instructions(name):
    """The project's replace version (NAME.replace.md) when it has one; otherwise the rendered
    workflow, then the project's additions (NAME.md) when it has them."""
    short, path = source(name)
    replacement = addon_path(short, '.replace.md')
    if replacement and replacement.is_file():
        return ('<!-- Project version: ' + config.PROJECT + ', from ' + str(replacement) + ' -->\n\n'
                + _parts(render(replacement))[1])
    body = commands_block() + _parts(render(path))[1]
    addon = addon_path(short)
    if addon and addon.is_file():
        body = (body.rstrip('\n') + '\n\n## Project additions: ' + config.PROJECT + '\n\n'
                'From ' + str(addon) + '. Where these differ from the steps above, follow these.\n\n'
                + addon.read_text().strip() + '\n')
    return body


def stub(path):
    """An installed skill: the canonical name and description, and a pointer to `skill NAME`."""
    short = path.parent.name.removeprefix('sidequest-')
    front, body = _parts(path.read_text())
    title = next((line for line in body.splitlines() if line.startswith('# ')), '# ' + short)
    return (front + '\n' + title + '\n\n'
            'Run `' + DATA + ' skill ' + short + '` from the ticket\'s worktree and follow the instructions it\n'
            'prints: the Sidequest workflow plus the current project\'s additions. If the command fails,\n'
            'follow ' + str(path) + ' instead.\n')


def install(destination, apply=False, check=False):
    destination = Path(destination).expanduser()
    state_path = destination / '.sidequest-skill-state.json'
    previous = json.loads(state_path.read_text()) if state_path.is_file() else {}
    state, changes, pending = {}, [], []
    for source in sorted((ROOT / 'agents/skills').glob('sidequest-*/SKILL.md')):
        name = source.parent.name
        target = destination / name / 'SKILL.md'
        wanted = stub(source)
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
