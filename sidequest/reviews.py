"""Normalize GitHub check runs and commit status contexts."""


def ci_summary(checks):
    if not checks:
        return "unknown"
    results = []
    for check in checks:
        conclusion = check.get("conclusion")
        status = check.get("status")
        state = check.get("state")
        if conclusion in {"FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STALE", "STARTUP_FAILURE"} or state in {"FAILURE", "ERROR"}:
            results.append("failing")
        elif status in {"IN_PROGRESS", "QUEUED", "WAITING", "PENDING", "REQUESTED"} or state in {"PENDING", "EXPECTED"}:
            results.append("pending")
        elif conclusion == "SUCCESS" or state == "SUCCESS":
            results.append("green")
        elif conclusion in {"SKIPPED", "NEUTRAL"}:
            results.append("skipped")
        else:
            results.append("unknown")
    for result in ("failing", "pending", "unknown"):
        if result in results:
            return result
    return "green" if "green" in results else "skipped"
