"""Per-ticket decision record of open questions: <tickets folder>/KEY/questions.md.

Written only through `sidequest-data questions`; the dashboard's Questions tab reads it.
Each question keeps a stable id and an append-only trail of evidence:

    ## Q1 · Should archived rewards be exported?
    - Status: answered
    - Raised: 2026-11-06 by sidequest-start
    - Context: The ticket says "export rewards" but not whether archived ones count.
    - Asked: 2026-11-06 to Alex via Jira comment
    - Answer: 2026-11-07 from Alex via Slack: No, only active rewards.
    - Decision: 2026-11-07: The export filters out archived rewards.

Only the Status line is ever replaced; every other change appends a line to its question.
"""
import os
import re
import tempfile

HEADING = re.compile(r'^## (Q\d+) · (.*)$')
FIELD = re.compile(r'^- (Status|Raised|Context|Asked|Answer|Decision|Note): ?(.*)$')
STATUSES = ("open", "asked", "answered")
INTRO = ("Decision record: what was asked, what the answer was and what was done because of it.\n"
         "Written by `sidequest-data questions`; shown in the dashboard's Questions tab (c).\n")


def clean(text):
    return " ".join(str(text or "").split())


def parse(text):
    """Questions in file order, each with id, text, status and its evidence lines."""
    items = []
    for number, line in enumerate(text.splitlines()):
        heading = HEADING.match(line)
        if heading:
            items.append({"id": heading[1], "text": heading[2].strip(), "status": "open", "line": number,
                          "end": number, "raised": "", "context": [], "asked": [], "answers": [],
                          "decisions": [], "notes": []})
            continue
        if not items:
            continue
        if line.startswith("#"):
            items[-1]["end_section"] = True
            continue
        if items[-1].get("end_section"):
            continue
        field = FIELD.match(line)
        if field:
            name, value = field[1], field[2].strip()
            items[-1]["end"] = number
            if name == "Status":
                items[-1]["status"] = value if value in STATUSES else "open"
                items[-1]["status_line"] = number
            elif name == "Raised":
                items[-1]["raised"] = value
            else:
                items[-1][{"Context": "context", "Asked": "asked", "Answer": "answers",
                           "Decision": "decisions", "Note": "notes"}[name]].append(value)
    for item in items:
        item.pop("end_section", None)
    return items


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".questions-", suffix=".md")
    with os.fdopen(handle, "w") as stream:
        stream.write(text)
    os.replace(temporary, path)


def _read(path):
    try:
        return path.read_text()
    except FileNotFoundError:
        return ""


def add(path, key, question, today, context="", source=""):
    """Append a question. Returns (id, created); a question already logged is not repeated."""
    question = clean(question)
    if not question:
        raise ValueError("Empty question")
    text = _read(path)
    items = parse(text)
    for item in items:
        if item["text"].casefold() == question.casefold():
            return item["id"], False
    number = max([int(i["id"][1:]) for i in items] or [0]) + 1
    if not text:
        text = f"# {key} questions\n\n{INTRO}"
    if not text.endswith("\n"):
        text += "\n"
    block = [f"\n## Q{number} · {question}", "- Status: open",
             f"- Raised: {today}" + (f" by {clean(source)}" if clean(source) else "")]
    if clean(context):
        block.append(f"- Context: {clean(context)}")
    _write(path, text + "\n".join(block) + "\n")
    return f"Q{number}", True


def normalize_id(qid):
    qid = str(qid).strip().upper()
    return qid if qid.startswith("Q") else "Q" + qid


def _update(path, qid, status, new_lines):
    text = _read(path)
    if not text:
        raise LookupError("No questions logged yet")
    lines = text.splitlines(keepends=True)
    qid = normalize_id(qid)
    item = next((i for i in parse(text) if i["id"] == qid), None)
    if not item:
        raise LookupError(f"No question {qid}")
    insert_at = item["end"] + 1
    if insert_at and not lines[insert_at - 1].endswith("\n"):
        lines[insert_at - 1] += "\n"
    lines[insert_at:insert_at] = [line + "\n" for line in new_lines]
    if status and "status_line" in item:
        lines[item["status_line"]] = f"- Status: {status}\n"
    _write(path, "".join(lines))
    return qid


def asked(path, qid, today, to="", via=""):
    detail = f"- Asked: {today}" + (f" to {clean(to)}" if clean(to) else "") + (f" via {clean(via)}" if clean(via) else "")
    current = next((i for i in parse(_read(path)) if i["id"] == normalize_id(qid)), None)
    return _update(path, qid, None if current and current["status"] == "answered" else "asked", [detail])


def answer(path, qid, reply, today, by="", via="", decision=""):
    reply = clean(reply)
    if not reply:
        raise ValueError("Empty answer")
    lines = [f"- Answer: {today}" + (f" from {clean(by)}" if clean(by) else "") +
             (f" via {clean(via)}" if clean(via) else "") + f": {reply}"]
    if clean(decision):
        lines.append(f"- Decision: {today}: {clean(decision)}")
    return _update(path, qid, "answered", lines)


def decide(path, qid, decision, today):
    decision = clean(decision)
    if not decision:
        raise ValueError("Empty decision")
    return _update(path, qid, None, [f"- Decision: {today}: {decision}"])


def view_lines(items, plan_lines, heading_marker):
    groups = [("answered", "ANSWERED"), ("asked", "ASKED, WAITING FOR AN ANSWER"), ("open", "NOT ASKED YET")]
    counts = {status: sum(i["status"] == status for i in items) for status in STATUSES}
    lines = [f"{counts['open']} not asked yet · {counts['asked']} waiting · {counts['answered']} answered", ""]
    for status, title in reversed(groups):
        chosen = [i for i in items if i["status"] == status]
        if not chosen:
            continue
        lines.append(heading_marker + title)
        for item in chosen:
            lines.append(f"{item['id']} {item['text']}")
            if item["raised"]:
                lines.append("   Raised " + item["raised"])
            lines += ["   Why: " + c for c in item["context"]]
            lines += ["   Asked " + a for a in item["asked"]]
            lines += ["   → Answer " + a for a in item["answers"]]
            lines += ["   ✓ Decision " + d for d in item["decisions"]]
            lines += ["   Note: " + n for n in item["notes"]]
            lines.append("")
    if plan_lines:
        lines += [heading_marker + "FROM PLAN.MD", *plan_lines, ""]
    return lines
