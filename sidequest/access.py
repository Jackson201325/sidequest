"""Access failures as data: which service failed and why, plus safe recovery guidance.

Adapters that know the cause (an HTTP status, a missing program) report it. Only output
from text-only tools is classified by its words. Never echo credential-bearing output.
"""

SERVICE_NAMES = {'prs': 'GitHub', 'merged': 'GitHub', 'fetch': 'GitHub', 'gh': 'GitHub', 'jira': 'Jira'}
CAUSES = ('missing_tool', 'credentials', 'login', 'denied', 'dns', 'tls', 'network', 'not_found', 'unknown')


class AccessFailure(RuntimeError):
    """A failed request to a service. The message is the recovery text users see."""

    def __init__(self, service, cause, tool=None):
        if cause not in CAUSES:
            raise ValueError('unknown access failure cause: ' + str(cause))
        self.service = SERVICE_NAMES.get(service, service)
        self.cause, self.tool = cause, tool
        super().__init__(self.service + ': ' + _guidance(self.service, cause, tool) + ' Previous data retained.')


def _guidance(name, cause, tool):
    if cause == 'missing_tool':
        if tool == 'gh':
            return 'GitHub CLI (gh) is not installed or not on PATH. Install it, run gh auth login, then press r.'
        return 'a required command is not installed or not on PATH. Check the setup steps, then press r.'
    if cause == 'credentials':
        return ('no credentials yet. Set jira.email in your config and export SIDEQUEST_JIRA_TOKEN '
                'in the terminal you start Sidequest from, then restart it.')
    if cause == 'login':
        recovery = ('Run gh auth login in your terminal, then press r.' if name == 'GitHub' else
                    'Renew SIDEQUEST_JIRA_TOKEN in your terminal, then press r.' if name == 'Jira' else
                    'Check the helper login in your terminal, then press r.')
        return 'login unavailable or expired. ' + recovery
    return {'denied': 'access denied. Check account permissions, then press r.',
            'dns': 'DNS lookup failed. Check your network or VPN, then press r.',
            'tls': 'TLS certificate verification failed. Check your network and certificates, then press r.',
            'network': 'network unavailable. Check your connection or VPN, then press r.',
            'not_found': 'resource not found. Check helper configuration, then press r.',
            }.get(cause, 'request failed. Inspect the helper in your terminal, then press r.')


def classify(text):
    """Best guess at a cause from a text-only tool's output: (cause, missing tool or None)."""
    text = str(text).casefold()
    if "no such file or directory: 'gh'" in text:
        return 'missing_tool', 'gh'
    if 'no jira credentials' in text or 'no jira token' in text:
        return 'credentials', None
    if 'no such file or directory' in text:
        return 'missing_tool', None
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


def failure_for(service, detail):
    """An AccessFailure for `service` from an exception or text. A known cause is used as is."""
    if isinstance(detail, AccessFailure) and detail.service == SERVICE_NAMES.get(service, service):
        return detail
    cause = getattr(detail, 'cause', None)
    if cause in CAUSES:
        return AccessFailure(service, cause, getattr(detail, 'tool', None))
    if isinstance(detail, FileNotFoundError) and detail.filename:
        return AccessFailure(service, 'missing_tool', str(detail.filename))
    return AccessFailure(service, *classify(detail))
