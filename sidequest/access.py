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
# Fixed extra sentences an adapter may attach; records carry only these names, never free text.
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

    def record(self):
        return {'service': self.service, 'cause': self.cause, 'tool': self.tool, 'note': self.note}


def classify(text):
    """Best guess at a cause from a text-only tool's output: (cause, missing tool or None)."""
    text = str(text).casefold()
    if 'no jira credentials' in text or 'no jira token' in text:
        return 'credentials', None
    if re.search(r"(?:^|/)env: \W?[\w.+-]+\W?: no such file or directory", text, re.M):
        return 'missing_tool', None  # a CLI's interpreter (BSD or GNU env output)
    missing = re.search(r"no such file or directory: '([^']+)'", text)
    if missing:  # a known CLI, or a file: a file name must not suggest login, TLS or network
        return ('missing_tool', missing[1]) if missing[1] in TOOLS else ('unknown', None)
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


class CommandFailure(RuntimeError):
    """A sidequest-data command failed for a reason other than a service: named by error type only."""

    def __init__(self, command, error):
        self.command, self.error = command, error
        self.terminal_text = (f'{COMMANDS[command]} failed ({error}). Run sidequest-data {command} again '
                              'in your terminal to see why.')
        super().__init__(f'{COMMANDS[command]} failed ({error}). Run sidequest-data {command} in your terminal '
                         'to see why.' + RETAINED)


def failure_record(exc, command):
    """(failure, record) for an error that ended a sidequest-data command. Errors that name a
    service and cause (AccessFailure, JiraError) keep them, including unknown causes and notes."""
    service, cause = service_name(getattr(exc, 'service', '')), getattr(exc, 'cause', None)
    if service in KNOWN_SERVICES and cause in CAUSES:
        failure = AccessFailure(service, cause, getattr(exc, 'tool', None), getattr(exc, 'note', None))
        return failure, failure.record()
    if cause in CAUSES and cause != 'unknown':
        failure = AccessFailure('sidequest-data', cause, getattr(exc, 'tool', None), getattr(exc, 'note', None))
        return failure, failure.record()
    failure = CommandFailure(command, type(exc).__name__)
    return failure, {'error': failure.error, 'command': command}


def failure_from_record(text):
    """Rebuild a failure from a record. Only known services, causes, tools, notes, commands and
    type names pass; anything else is a generic failure, so helper output never shows as text."""
    try:
        record = json.loads(text)
    except ValueError:
        record = None
    if not isinstance(record, dict) or not all(isinstance(value, (str, type(None))) for value in record.values()):
        return AccessFailure('sidequest-data', 'unknown')
    if set(record) <= {'service', 'cause', 'tool', 'note'}:
        if (record.get('service') in KNOWN_SERVICES and record.get('cause') in CAUSES
                and record.get('tool') in (None, *TOOLS) and record.get('note') in (None, *NOTES)):
            return AccessFailure(record['service'], record['cause'], record.get('tool'), record.get('note'))
    if (set(record) == {'error', 'command'} and record['command'] in COMMANDS
            and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,60}', str(record['error']))):
        return CommandFailure(record['command'], record['error'])
    return AccessFailure('sidequest-data', 'unknown')


def failure_for(service, detail):
    """An AccessFailure for `service` from an exception or text. A known cause is used as is."""
    cause = getattr(detail, 'cause', None)
    if cause in CAUSES:
        return AccessFailure(service, cause, getattr(detail, 'tool', None), getattr(detail, 'note', None))
    return AccessFailure(service, *classify(detail))
