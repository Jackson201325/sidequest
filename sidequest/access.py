"""Safe recovery guidance: never echo credential-bearing helper output."""

def access_error(service, detail):
    text = str(detail).casefold()
    name = {'prs': 'GitHub', 'merged': 'GitHub', 'fetch': 'GitHub', 'jira': 'Jira'}.get(service, service)
    if 'no such file or directory' in text and name == 'GitHub':
        # A missing gh binary surfaces as FileNotFoundError, which read as a vague "request failed".
        cause = 'GitHub CLI (gh) is not installed or not on PATH. Install it, run gh auth login, then press r.'
    elif 'no jira credentials' in text or 'no jira token' in text:
        cause = ('no credentials yet. Set jira.email in your config and export SIDEQUEST_JIRA_TOKEN '
                 'in the terminal you start Sidequest from, then restart it.')
    elif 'no such file or directory' in text:
        cause = 'a required command is not installed or not on PATH. Check the setup steps, then press r.'
    elif any(word in text for word in ('401', 'token expired', 'invalid token', 'bad credentials', 'unauthorized', 'not logged', 'authentication', 'login', 'no jira token', 'no jira credentials', 'SIDEQUEST_JIRA_TOKEN')):
        recovery = ('Run gh auth login in your terminal, then press r.' if name == 'GitHub' else
                    'Renew SIDEQUEST_JIRA_TOKEN in your terminal, then press r.' if name == 'Jira' else
                    'Check the helper login in your terminal, then press r.')
        cause = 'login unavailable or expired. ' + recovery
    elif any(word in text for word in ('403', 'forbidden', 'permission', 'access denied', 'eacces')):
        cause = 'access denied. Check account permissions, then press r.'
    elif any(word in text for word in ('enotfound', 'getaddrinfo', 'nodename nor servname')):
        cause = 'DNS lookup failed. Check your network or VPN, then press r.'
    elif any(word in text for word in ('certificate', 'ssl', 'tls')):
        cause = 'TLS certificate verification failed. Check your network and certificates, then press r.'
    elif any(word in text for word in ('internet connection', 'connect', 'network', 'timed out', 'timeout', 'unreachable', 'offline')):
        cause = 'network unavailable. Check your connection or VPN, then press r.'
    elif any(word in text for word in ('not found', "couldn't find")):
        cause = 'resource not found. Check helper configuration, then press r.'
    else:
        cause = 'request failed. Inspect the helper in your terminal, then press r.'
    return name + ': ' + cause + ' Previous data retained.'
