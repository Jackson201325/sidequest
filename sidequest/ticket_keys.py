"""The one place that reads Jira ticket keys out of text, branches and PR fields."""
import re

SHAPE = r"[A-Z][A-Z0-9_]*-\d+"  # a key in capitals; the patterns below accept any case
KEY = re.compile(r"\b" + SHAPE + r"\b", re.I)
WHOLE_KEY = re.compile(SHAPE, re.I)
SEGMENT_KEY = re.compile(r"(?:^|/)(" + SHAPE + r")(?=-|$)", re.I)
MENTION = re.compile(r"\b([A-Z][A-Z0-9_]*)[ -](\d+)\b", re.I)
LEADING_KEY = re.compile(r"^\s*\[?[A-Z][A-Z0-9_]*[ -]\d+\]?[\s:.-]*", re.I)


def is_key(text):
    """True when the whole text is a key such as APP-12 (any case)."""
    return bool(WHOLE_KEY.fullmatch(str(text or "")))


def _first_trusted(candidates, known):
    """Case-insensitive matching reads "utf-8" or "python-3" as keys, so with known project
    prefixes only those are accepted (any case); without them a key must be written in capitals."""
    known = {prefix.upper() for prefix in known}
    for candidate in candidates:
        if candidate.rsplit("-", 1)[0].upper() in known if known else candidate == candidate.upper():
            return candidate.upper()
    return None


def ticket_key(text, known=()):
    """First trusted ticket key in free text such as a PR title or branch."""
    return _first_trusted((match.group() for match in KEY.finditer(text or "")), known)


def linked_ticket(number=None, branch=""):
    """A user-confirmed link (github.pr_tickets, github.branch_tickets) for work whose names omit the key."""
    from sidequest import config
    by_pr = config.get("github", "pr_tickets", {})
    if number is not None and str(number) in by_pr:
        return by_pr[str(number)].upper()
    return config.get("github", "branch_tickets", {}).get(branch or "", "").upper() or None


def pr_ticket(pr, known=()):
    """Ticket for a PR: a confirmed link, then its collected `ticket` field, its title, its branch."""
    return linked_ticket(pr.get("number"), str(pr.get("branch") or "")) or next(
        filter(None, (ticket_key(str(pr.get(field) or ""), known) for field in ("ticket", "title", "branch"))), None)


def branch_keys(branch):
    """Keys at the start of a branch path segment, e.g. feature/APP-1-revert-APP-2 → [APP-1].
    Requiring a segment start keeps APP-6 from matching APP-61; backup/ branches hold no ticket."""
    if branch.startswith("backup/"):
        return []
    return [key.upper() for key in SEGMENT_KEY.findall(branch)]


def branch_ticket(branch, known=()):
    """The ticket a branch is for, when nothing else names it: a confirmed link, then the first trusted segment key."""
    return linked_ticket(branch=branch) or _first_trusted(SEGMENT_KEY.findall(branch) if not branch.startswith("backup/") else [], known)


def mentions(text):
    """Keys a person wrote in text, with a hyphen or a space ("APP 12"), in order and without repeats.
    Use only to find known keys; spaced matches such as "python 3" are not proof that a ticket exists."""
    return list(dict.fromkeys(f"{prefix.upper()}-{number}" for prefix, number in MENTION.findall(text or "")))


def without_leading_key(title):
    """PR titles often repeat the key ("DEMO 297 Remove emojis"); remove it once."""
    return LEADING_KEY.sub("", title or "").strip()
