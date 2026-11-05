"""Partition and render a ticket document without modifying its source file."""
import re

HEADING = re.compile(r'^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$')
UPDATE_TITLE = re.compile(
    r'^(?:updates?|progress(?: log| notes| updates)?|implementation (?:progress|updates|notes|summary)'
    r'|qa results|test results|verification results|validation results|changes implemented|changelog)'
    r'(?=$|[\s:—–(\-])', re.I)


def document_views(text, heading_marker):
    views = {'Plan': [], 'Updates': []}
    parents = []
    target = 'Plan'
    fence = None
    for line in text.splitlines():
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= fence[1] and not marker[2].strip():
                fence = None
            else:
                views[target].append(line)
            continue
        if marker:
            fence = (marker[1][0], len(marker[1]))
            continue
        heading = HEADING.match(line)
        if heading:
            level, title = len(heading[1]), heading[2]
            while parents and parents[-1][0] >= level:
                parents.pop()
            target = parents[-1][1] if parents else 'Plan'
            title_text = title.replace('**', '').replace('`', '').strip()
            if UPDATE_TITLE.match(title_text):
                target = 'Updates'
            parents.append((level, target))
            line = heading_marker + title.upper()
        line = re.sub(r'^(\s*)[-*] \[ \] ', r'\1☐ ', line)
        line = re.sub(r'^(\s*)[-*] \[[xX]\] ', r'\1☑ ', line)
        line = re.sub(r'^(\s*)[-*] ', r'\1• ', line)
        views[target].append(line.replace('**', '').replace('`', ''))
    return views
