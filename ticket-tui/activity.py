"""Combine dated evidence without treating activity as workflow progress."""

from core import parse_time


REVIEW_STATES = {"APPROVED": "approved", "CHANGES_REQUESTED": "changes requested",
                 "COMMENTED": "commented", "DISMISSED": "dismissed", "PENDING": "pending"}


def _has_inline_from(pr, login, submitted_at, seconds=300):
    """True when a loaded inline comment by the same reviewer was written around the review's submit time."""
    submitted = parse_time(submitted_at)
    if not submitted:
        return False
    for thread in pr.get("unresolved", []):
        for comment in thread.get("comments", []):
            created = parse_time(comment.get("created_at"))
            if comment.get("author") == login and created and abs((submitted - created).total_seconds()) <= seconds:
                return True
    return False


def ticket_activity(ticket):
    """Jira and GitHub events for a ticket, newest first. Local notes, local git commits and the
    queue's own clock resets are deliberately left out: they live in the Work log and Overview."""
    events, commit_ids = [], set()

    def add(at, source, title, body="", author=""):
        if parse_time(at):
            events.append({"at": at, "source": source, "title": title, "body": body, "author": author})

    # Bare "updated" stamps don't say what changed; the help screen explains that.
    add(ticket.updated, "Jira", "Ticket updated")
    for change in ticket.jira_changes:
        if change.get("field") == "status":
            add(change.get("at"), "Jira", f"Moved {change.get('from') or '?'} → {change.get('to') or '?'}", author=change.get("author", ""))
        elif change.get("field") == "assignee":
            title = f"Assigned to {change['to']}" if change.get("to") else "Unassigned"
            add(change.get("at"), "Jira", title + (f" (was {change['from']})" if change.get("from") else ""), author=change.get("author", ""))
    for comment in ticket.jira_comments:
        add(comment.get("created_at"), "Jira", "Comment added", comment.get("body", ""), comment.get("author", ""))
        if comment.get("updated_at") and comment.get("updated_at") != comment.get("created_at"):
            add(comment["updated_at"], "Jira", "Comment edited", comment.get("body", ""), comment.get("update_author", ""))
    for pr in ticket.prs:
        label = f"PR #{pr['number']}"
        add(pr.get("updated_at"), "GitHub", label + " updated")
        for comment in pr.get("discussion", []):
            author = comment.get("author") or {}
            add(comment.get("createdAt"), "GitHub", label + " discussion comment", comment.get("body", ""), author.get("login", ""))
        for review in pr.get("reviews", []):
            login = (review.get("author") or {}).get("login", "")
            state = review.get("state", "")
            body = (review.get("body") or "").strip()
            if not body and state == "COMMENTED":
                # GitHub wraps line comments submitted together in an empty "commented" review.
                # Skip it when those line comments are loaded; otherwise say where they are.
                if _has_inline_from(pr, login, review.get("submittedAt")):
                    continue
                add(review.get("submittedAt"), "GitHub", label + " review: comments on specific lines",
                    "The line comments themselves aren't loaded (their threads are resolved or outdated). "
                    "Space o opens the PR to read them.", login)
                continue
            add(review.get("submittedAt"), "GitHub", label + " review: " + REVIEW_STATES.get(state, state.lower() or "unknown"),
                body, login)
        for thread in pr.get("unresolved", []):
            for comment in thread.get("comments", []):
                location = f"{thread.get('path', '')}:{thread.get('line') or '?'}"
                add(comment.get("created_at"), "GitHub", label + " inline comment · " + location,
                    comment.get("body") or comment.get("summary", ""), comment.get("author", ""))
        for commit in pr.get("commits", []):
            sha = commit.get("oid")
            if sha and sha not in commit_ids:
                commit_ids.add(sha)
                add(commit.get("authoredDate"), "GitHub", label + " commit " + sha[:7], commit.get("messageHeadline", ""))
    events.sort(key=lambda event: parse_time(event["at"]).timestamp(), reverse=True)
    return events
