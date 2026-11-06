"""One personal identity for CLI adapters, work history and display."""
from zoneinfo import ZoneInfo
from sidequest import config

JIRA_ACCOUNT_ID = config.get('jira', 'account_id')
JIRA_EMAIL = config.get('jira', 'email')
GITHUB_LOGIN = config.get('github', 'username')
GIT_AUTHOR = config.get('identity', 'git_author')
DISPLAY_NAME = config.get('identity', 'display_name', 'You')
TZ = ZoneInfo(config.get('identity', 'timezone', 'UTC'))
GITHUB_REPO = config.get('github', 'repository')


def is_my_author(authors):
    if isinstance(authors, dict):
        authors = authors.get("nodes", [])
    return any((GITHUB_LOGIN and (a.get("login") or "").lower() == GITHUB_LOGIN.lower()) or
               (GIT_AUTHOR and a.get("name") == GIT_AUTHOR) for a in authors or [])
