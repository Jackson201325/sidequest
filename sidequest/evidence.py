"""Dated evidence and source-aware time parsing shared by readers."""
import re
from datetime import datetime, time, timedelta
from sidequest.identity import TZ, GIT_AUTHOR


def parse_time(value, naive_zone=TZ):
    try:
        # Jira sends "+0000"; fromisoformat only reads "+00:00" before Python 3.11.
        stamp = datetime.fromisoformat(re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", str(value).replace("Z", "+00:00")))
        return stamp.replace(tzinfo=naive_zone) if stamp.tzinfo is None else stamp
    except (ValueError, TypeError):
        return None


def parse_commits(raw):
    result, seen = [], set()
    if "\x1f" in raw:
        records = [r.strip().split("\x1f", 2) for r in raw.split("\x1e")]
    else:
        records = [[f[0], f[2], f[3]] for line in raw.splitlines() if len(f := line.split("|", 3)) == 4]
    for fields in records:
        if len(fields) == 3 and fields[0] and fields[0] not in seen and parse_time(fields[1]):
            seen.add(fields[0])
            result.append({"sha": fields[0], "date": fields[1], "subject": fields[2], "source": "git"})
    return result


def commits_for_day(team, day):
    start = datetime.combine(day, time.min, TZ)
    raw = team.run_command(["git", "log", "--all", "--author=" + GIT_AUTHOR,
                            "--since=" + start.isoformat(), "--until=" + (start + timedelta(days=1)).isoformat(),
                            "--format=%H%x1f%aI%x1f%s%x1e"])
    return [{"sha": c["sha"][:7], "full_sha": c["sha"], "committed_at": c["date"],
             "subject": c["subject"], "ticket": team.extract_ticket(c["subject"])} for c in parse_commits(raw)]
