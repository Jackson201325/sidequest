"""sidequest meeting: run the person's own meeting.command in a pane, then show what it wrote.

Sidequest does not record or transcribe; the command does and appends `## <date> · <scope>`
sections to tickets/KEY/meetings.md. This module only finds those new sections."""
from pathlib import Path

from sidequest import tmux

ROLE = 'meeting'


def pane_argv(python, script, key, project=''):
    argv = [python, '-B', str(script), '--here', *([key] if key else [])]
    return ['env', 'SIDEQUEST_PROJECT=' + project, *argv] if project else argv


def open_pane(run, pane, path, argv, percent=40):
    """A pane below the caller's pane runs argv; an open meeting pane is selected instead."""
    return tmux.open_below(run, pane, path, argv, ROLE, percent)


CONTEXT_FILES = ('plan.md', 'questions.md', 'meetings.md')


def context(key, folder, limit=12000):
    """What a ticket meeting starts with: the ticket folder's plan, questions and earlier meetings.
    A long file keeps its end, where the newest notes are."""
    parts = ['Ticket ' + key + ': this meeting is about it. Its notes so far follow.']
    for name in CONTEXT_FILES:
        try:
            text = (Path(folder) / name).read_text(errors='replace').strip()
        except OSError:
            continue
        if text:
            parts.append('## ' + name + '\n' + (text if len(text) <= limit else '…\n' + text[-limit:]))
    return '\n\n'.join(parts) + '\n'


def newest_section(text):
    heading, lines = None, []
    for line in text.splitlines():
        if line.startswith('## '):
            heading, lines = line[3:].strip(), []
        elif heading is not None:
            lines.append(line)
    while lines and not lines[-1].strip():
        lines.pop()
    while lines and not lines[0].strip():
        lines.pop(0)
    return heading, lines


def changed_since(tickets, since):
    """(key, heading, lines) of the newest section of each meetings.md modified at or after since."""
    found = []
    for path in sorted(Path(tickets).glob('*/meetings.md')):
        try:
            if path.stat().st_mtime < since:
                continue
            heading, lines = newest_section(path.read_text(errors='replace'))
        except OSError:
            continue
        if heading:
            found.append((path.parent.name, heading, lines))
    return found


def summary(found):
    if not found:
        return 'No meeting notes were added to any ticket.'
    blocks = []
    for key, heading, lines in found:
        blocks.append('\n'.join([key + ' · ' + heading, *('  ' + line for line in lines)]))
    return '\n\n'.join(blocks)
