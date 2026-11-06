"""Naming shared by explicit ticket starts and automatic worktree sync."""
import re

from sidequest.ticket_keys import is_key


def branch_name(key, summary, issue_type="", prefix=None):
    key = str(key).upper()
    if not is_key(key):
        raise ValueError("expected a Jira key such as APP-123")
    prefix = prefix or ("fix" if issue_type.lower() in ("bug", "defect") else "feature")
    if prefix not in ("fix", "feature", "hotfix", "chore"):
        raise ValueError("prefix must be fix, feature, hotfix or chore")
    base = prefix + "/" + key
    room = 60 - len(base) - 1
    if room < 1:
        raise ValueError("ticket key is too long for a 60-character branch")
    words = re.sub(r"[^a-z0-9]+", "-", summary.lower()).strip("-")
    slug = words[:room]
    if len(words) > room and "-" in slug:
        slug = slug.rsplit("-", 1)[0]
    slug = slug.strip("-")
    return base + "-" + slug if slug else base
