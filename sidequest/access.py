"""Access failures as data: which service failed and why, plus safe recovery guidance.

Adapters that know the cause (an HTTP status, a missing program, a timeout) report it.
Only output from text-only tools is classified by its words. Never echo credential-bearing
output. Advice is a problem plus an action; the dashboard adds "then press r" and the
retention note, and command-line helpers show the plain action.
"""
import json
import os
import re

SERVICE_NAMES = {'prs': 'GitHub', 'merged': 'GitHub', 'fetch': 'GitHub', 'gh': 'GitHub', 'jira': 'Jira',
                 'heroku': 'Heroku'}
# tool: (label, how to log in)
TOOLS = {'gh': ('GitHub CLI (gh)', 'run gh auth login'), 'heroku': ('Heroku CLI (heroku)', 'run heroku login')}
KNOWN_SERVICES = ('GitHub', 'Jira', 'Heroku', 'sidequest-data')
CAUSES = ('missing_tool', 'credentials', 'login', 'denied', 'dns', 'tls', 'network', 'timeout', 'server',
          'rate_limited', 'not_found', 'unknown')
RETAINED = ' Previous data retained.'
MAX_TEXT = 300  # longest dashboard message
# Fixed extra sentences an adapter may attach by name.
NOTES = {'site_refused_token': 'The Jira site refused the token; if it is not a scoped token, '
                               'renew SIDEQUEST_JIRA_TOKEN'}
COMMANDS = {'collect': 'Collection', 'snapshot': 'Snapshot read', 'ticket': 'Ticket lookup'}


def service_name(name):
    name = os.path.basename(str(name))
    return SERVICE_NAMES.get(name, name)


def _advice(service, cause, tool):
    """(problem, action, retry): retry means pressing r can help once the action is done."""
    if cause == 'missing_tool':
        if tool in TOOLS:
            label, login = TOOLS[tool]
            return label + ' is not installed or not on PATH', 'Install it, ' + login, True
        return 'a required command is not installed or not on PATH', 'Check the setup steps', True
    if cause == 'credentials':
        return ('no credentials yet', 'Set jira.email in your config and export SIDEQUEST_JIRA_TOKEN in the '
                'terminal you start Sidequest from, then restart it', False)
    if cause == 'login':
        action = {'GitHub': 'Run gh auth login in your terminal', 'Jira': 'Renew SIDEQUEST_JIRA_TOKEN in your terminal',
                  'Heroku': 'Run heroku login in your terminal'}.get(service, 'Check the helper login in your terminal')
        return 'login unavailable or expired', action, True
    if cause == 'timeout':
        if tool:
            return 'timed out without an answer', 'Run the same command in your terminal to see what it waits for', True
        return 'the service did not answer in time', 'Try again in a few minutes', True
    return {'denied': ('access denied', 'Check account permissions', True),
            'dns': ('DNS lookup failed', 'Check your network or VPN', True),
            'tls': ('TLS certificate verification failed', 'Check your network and certificates', True),
            'network': ('network unavailable', 'Check your connection or VPN', True),
            'server': ('the service reported a server error', 'Try again in a few minutes', True),
            'rate_limited': ('rate limited by the service', 'Wait a few minutes', True),
            'not_found': ('resource not found', 'Check helper configuration', True),
            }.get(cause, ('request failed', 'Inspect the helper in your terminal', True))


class AccessFailure(RuntimeError):
    """A failed request to a service. str() is the dashboard's recovery text; terminal_text
    is the same advice for a command-line helper, which has no r key and keeps no data."""

    def __init__(self, service, cause, tool=None, note=None):
        if cause not in CAUSES or note not in (None, *NOTES):
            raise ValueError('unknown access failure cause or note: %s %s' % (cause, note))
        self.service, self.cause, self.tool, self.note = service_name(service), cause, tool, note
        problem, action, retry = _advice(self.service, cause, tool)
        extra = ' ' + NOTES[note] + '.' if note else ''
        self.terminal_text = f'{self.service}: {problem}. {action}.{extra}'
        super().__init__(f'{self.service}: {problem}. {action}' + (', then press r.' if retry else '.') + extra + RETAINED)


def classify(text):
    """Best guess at a cause from a text-only tool's output: (cause, missing tool or None)."""
    text = str(text).casefold()
    if 'no jira credentials' in text or 'no jira token' in text:
        return 'credentials', None
    if re.search(r"(?:^|/)env: \W?[\w./+-]+\W?: no such file or directory", text, re.M):
        return 'missing_tool', None  # a CLI's interpreter (BSD or GNU env output)
    missing = re.findall(r"no such file or directory: '([^']+)'", text)
    tool = next((name for name in missing if name in TOOLS), None)
    if tool:
        return 'missing_tool', tool
    if 'traceback (most recent call last)' in text:
        return 'unknown', None  # code and variable names in a traceback ("LOGIN_PATH") are not causes
    # A missing file is not a cause, and its name ("login.json") must not suggest one.
    text = re.sub(r"no such file or directory: '[^']*'", '', text)
    for cause, words in (('login', ('401', 'token expired', 'invalid token', 'bad credentials', 'unauthorized',
                                    'not logged', 'authentication', 'login')),
                         ('denied', ('403', 'forbidden', 'permission', 'access denied', 'eacces')),
                         ('dns', ('enotfound', 'getaddrinfo', 'nodename nor servname')),
                         ('tls', ('certificate', 'ssl', 'tls')),
                         ('network', ('internet connection', 'connect', 'network', 'timed out', 'timeout',
                                      'unreachable', 'offline')),
                         ('not_found', ('not found', "couldn't find"))):
        if any(word in text for word in words):
            return cause, None
    return 'unknown', None


def jira_text(exc):
    """A JiraError's own sentence, without retention wording, naming Jira once."""
    text = re.sub(r';\s*(previous data retained|retain the previous snapshot)\.?$', '', str(exc)).rstrip('.')
    return (text if re.search(r'\bJira\b(?!-)', text) else 'Jira: ' + text) + '.'


def describe_failure(exc, command):
    """(terminal text, dashboard text) for an error that ended a sidequest-data command.
    Every text comes from these templates or from messages Sidequest's own code wrote."""
    if isinstance(exc, AccessFailure):
        return exc.terminal_text, clip(str(exc))
    service, cause = service_name(getattr(exc, 'service', '')), getattr(exc, 'cause', None)
    if service in KNOWN_SERVICES and cause in CAUSES:
        failure = AccessFailure(service, cause, getattr(exc, 'tool', None), getattr(exc, 'note', None))
        if service == 'Jira' and (cause == 'unknown' or getattr(exc, 'permanent', False)):
            # Jira's own sentence explains these (a bad key, a moved issue's new key).
            note = ' ' + NOTES[failure.note] + '.' if failure.note else ''
            retry = '' if getattr(exc, 'permanent', False) else ' Press r to try again.'
            text = jira_text(exc) + note
            return text, clip(text + retry + RETAINED)
        return failure.terminal_text, clip(str(failure))
    label, error = COMMANDS[command], type(exc).__name__
    # Only the operating system's own reason; other messages may repeat commands or response bodies.
    reason = getattr(exc, 'strerror', None) if isinstance(exc, OSError) else None
    return (f'{label} failed ({error}' + (': ' + reason if reason else '') + ').',
            clip(f'{label} failed ({error}). Run sidequest-data {command} in your terminal to see the error.' + RETAINED))


def clip(text):
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT - 1].rstrip() + '…'


def dashboard_text(record_text):
    """The message from a sidequest-data failure record, or None when it is not one safe line."""
    try:
        record = json.loads(record_text)
    except ValueError:
        return None
    text = record.get('text') if isinstance(record, dict) and set(record) == {'text'} else None
    if isinstance(text, str) and text and len(text) <= MAX_TEXT and text.isprintable():
        return text
    return None


def failure_for(service, detail):
    """An AccessFailure for `service` from an exception or text. A known cause is used as is."""
    cause = getattr(detail, 'cause', None)
    if cause in CAUSES:
        return AccessFailure(service, cause, getattr(detail, 'tool', None), getattr(detail, 'note', None))
    return AccessFailure(service, *classify(detail))
