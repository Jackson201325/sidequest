"""`sidequest start KEY`: move the ticket to jira.start_status, then create or reuse its worktree."""
from sidequest.ticket_keys import is_key


def full_key(text, projects):
    """'800' -> FIRST-800 (jira.projects); a whole key is upper-cased; anything else is refused."""
    text = str(text or '').strip().upper()
    if text.isdigit():
        if not projects:
            raise ValueError('a bare number needs jira.projects; give the full key such as APP-123')
        return projects[0] + '-' + text
    if not is_key(text):
        raise ValueError('expected a Jira key such as APP-123')
    return text


def start(key, jira, workspace, move=True, yes=False, prefix=None):
    """(lines, worktree result). A move that is refused is noted; the worktree is still made."""
    lines = []
    if move:
        code, message = jira.start_ticket(key, yes=yes)
        lines.append(message if code == 0 else 'note     ' + message)
    info = jira.fetch_one(key)
    plan = workspace.preview(key, info.get('summary') or '', info.get('issue_type') or '', prefix)
    return lines, workspace.apply(plan)
