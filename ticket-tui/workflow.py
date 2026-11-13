"""A simplified workflow position and evidence-based explanations."""

STAGES = ("Backlog", "Build", "Review", "QA", "Approved", "Done")
STAGE_LABELS = ("Not started", "Implementation", "Code review", "QA testing", "Approved", "Done")
REWORK = ("qa failed", "reopened", "fixing revisions")
ALIASES = {
    **dict.fromkeys(REWORK, 1),
    "backlog": 0, "to do": 0, "open": 0, "ready for development": 0,
    "in progress": 1, "development": 1, "in development": 1,
    "ready for code review": 2, "code review": 2, "in review": 2, "in code review": 2,
    "qa": 3, "in qa": 3, "ready for qa": 3, "testing": 3, "in testing": 3,
    "approved": 4, "ready for production": 4, "ready to deploy": 4,
    "done": 5, "closed": 5, "resolved": 5,
    # The DEMO board's own status names (Backlog → In Design → Ready for Dev → In Dev → …).
    "in design": 0, "ready for dev": 0,
    "in dev": 1,
    "ready for stakeholder review": 4, "in stakeholder review": 4,
    "archived": 5,
}


def stage_context(ticket):
    status = " ".join(ticket.status.casefold().replace("_", " ").split())
    index = ALIASES.get(status)
    source = "Jira status"
    if index is None:
        source = "PR evidence (inferred)"
        if ticket.prs:
            index = 1 if any(p.get("wip") for p in ticket.prs) else 2
        else:
            source = "Unmapped Jira status"
    reviewers = sorted({r for p in ticket.prs for r in p.get("requested_reviewers", [])})
    blocker = "The available data does not establish the reason for the wait."
    next_gate = "Clarify the next owner or workflow step."
    if index == 0:
        blocker = "The ticket is queued for work; the data does not say why it has not started."
        next_gate = "Start implementation when prioritized."
    elif index == 1:
        blocker = "Implementation or rework is the current phase; code completeness is not verified."
        next_gate = "Finish the change, check it, and get a PR ready for review."
    elif index == 2:
        if ticket.court == "them" and ticket.assignee not in ("Unknown", "Unassigned", ""):
            blocker = "Jira hands review to " + ticket.assignee + "; GitHub feedback is shown separately below."
        elif any(p.get("review_decision") == "CHANGES_REQUESTED" for p in ticket.prs):
            blocker = "Review requested changes; your response or code update is needed."
        elif any(p.get("ci") == "failing" for p in ticket.prs):
            blocker = "A PR check is failing; inspect the failed check before the next handoff."
        elif any(p.get("unresolved_count", 0) for p in ticket.prs):
            blocker = "Inline threads remain unresolved; they may need a fix, reply, or reviewer resolution."
        elif ticket.prs and all(p.get("review_decision") == "APPROVED" for p in ticket.prs):
            blocker = "PR approval is recorded, but Jira still maps to review; the next handoff needs confirmation."
        elif reviewers:
            blocker = "Likely awaiting review from " + ", ".join(reviewers) + ". Their reason for waiting is unknown."
        elif ticket.prs:
            blocker = "There is an open PR with no requested reviewer."
        else:
            blocker = "Jira says review; no associated PR is loaded to confirm review progress."
        next_gate = "Address feedback, obtain review approval, and confirm the QA handoff."
    elif index == 3:
        owner = ticket.assignee if ticket.assignee not in ("Unknown", "", "Unassigned") else "the QA owner"
        blocker = "Likely awaiting QA results from " + owner + "; a test result is not confirmed by status alone."
        if ticket.assigned_me is True:
            blocker = "QA status conflicts with assignment to you; check whether QA returned findings for you to fix."
        next_gate = "QA passes, or findings return to implementation."
    elif index == 4:
        blocker = "Jira records approval; the remaining release/closure handoff is not established by that label."
        next_gate = "Confirm who owns the next release or closure step."
    elif index == 5:
        blocker = "Jira records completion; this does not independently verify a production deployment."
        next_gate = "No next action unless the ticket is reopened."
    if status == "blocked":
        blocker = "Jira marks this blocked, but the blocking reason is not loaded. Any mapped phase comes only from PR evidence."
    return {"index": index, "name": STAGES[index] if index is not None else "Unknown",
            "source": source, "likely": blocker, "next": next_gate}


def workflow_strip(ticket):
    stage = stage_context(ticket)
    index = stage["index"]
    return ([f"YOU ARE HERE: {STAGE_LABELS[index]} (step {index + 1} of {len(STAGES)})"] if index is not None else
            ["CURRENT STEP: Unknown — Jira status needs clarification"])


def workflow_path(ticket):
    index = stage_context(ticket)["index"]
    return [f"{i + 1}. {label}" + ("   YOU ARE HERE" if i == index else
            "   (earlier)" if index is not None and i < index else
            "   (later)" if index is not None else "") for i, label in enumerate(STAGE_LABELS)]


def next_owner(ticket):
    return ownership(ticket)[0]


def ownership(ticket):
    if ticket.court == "me":
        return "You", "Jira assignment or actionable PR feedback"
    if ticket.court == "unknown":
        return "Needs clarification", "Next owner is not established"
    if ticket.court == "done":
        return "No next owner", "Ticket is complete in Jira"
    if ticket.assignee not in ("Unknown", "Unassigned", "") and ticket.assigned_me is not True:
        return ticket.assignee, "Jira assignee; next ownership inferred"
    if ticket.assigned_me is True or stage_context(ticket)["index"] == 2:
        reviewers = sorted({r for p in ticket.prs for r in p.get("requested_reviewers", [])})
        if reviewers:
            return ", ".join(reviewers), "GitHub reviewer request"
    return "Someone else (name unknown)", "Next owner is not confirmed"
