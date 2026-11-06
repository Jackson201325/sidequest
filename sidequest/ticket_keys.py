"""The one rule for reading Jira ticket keys out of PR titles and branch names."""
import re

KEY = re.compile(r"\b[A-Z][A-Z0-9_]*-\d+\b", re.I)


def ticket_key(text, known=()):
    """First ticket key in free text such as a PR title or branch.

    Case-insensitive matching reads "utf-8" or "python-3" as keys, so with known project
    prefixes only those are accepted (any case); without them a key must be written in capitals.
    """
    known = {prefix.upper() for prefix in known}
    for match in KEY.finditer(text or ""):
        candidate = match.group()
        if candidate.rsplit("-", 1)[0].upper() in known if known else candidate == candidate.upper():
            return candidate.upper()
    return None


def pr_ticket(pr, known=()):
    """Ticket for a PR from its collected `ticket` field, then its title, then its branch."""
    return next(filter(None, (ticket_key(str(pr.get(field) or ""), known) for field in ("ticket", "title", "branch"))), None)
