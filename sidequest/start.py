"""`sidequest start KEY`: move the ticket to jira.start_status, then create or reuse its worktree."""
from sidequest.ticket_keys import is_key


def full_key(text, projects):
    """'800' -> APP-800 when jira.projects names one project; a whole key is upper-cased; anything
    else is refused, also a number that several projects could own."""
    text = str(text or '').strip().upper()
    if text.isdigit():
        if not projects:
            raise ValueError('a bare number needs jira.projects; give the full ticket key, such as APP-123')
        if len(projects) > 1:
            raise ValueError('a bare number fits several projects (' + ', '.join(projects) + '); give the full '
                             'ticket key, such as ' + projects[0] + '-' + text)
        return projects[0].upper() + '-' + text
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
