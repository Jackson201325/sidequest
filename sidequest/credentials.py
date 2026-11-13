"""Secrets by reference. The environment variable wins; otherwise the project's `credentials` setting
names where the secret lives: keychain:SERVICE, keychain:SERVICE/ACCOUNT (macOS Keychain) or env:NAME.
Settings never hold a secret, and nothing here prints one."""
import os
import re
import subprocess
import sys

from sidequest import config

REFERENCE = re.compile(r'keychain:[^/\s]+(/\S+)?|env:[A-Za-z_][A-Za-z0-9_]*')
SECRETS = {'jira': 'SIDEQUEST_JIRA_TOKEN', 'qa': 'SIDEQUEST_QA_PASSWORD'}
LOGINS = {'review': ('SIDEQUEST_REVIEW_EMAIL', 'SIDEQUEST_REVIEW_PASSWORD')}
NAMES = tuple(SECRETS) + tuple(LOGINS)
RUN = subprocess.run


def reference(name):
    return config.get('credentials', name)


def _security(args):
    if sys.platform != 'darwin':
        return None
    try:
        result = RUN(['security', 'find-generic-password', *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def _resolve(name):
    """(account, secret) from the reference, or None."""
    ref = reference(name)
    if not ref or not REFERENCE.fullmatch(ref):
        return None
    if ref.startswith('env:'):
        value = os.environ.get(ref[4:])
        return ('', value) if value else None
    service, _, account = ref[len('keychain:'):].partition('/')
    args = ['-s', service] + (['-a', account] if account else [])
    secret = _security(args + ['-w'])
    if secret is None:
        return None
    if not account:
        found = re.search(r'"acct"<blob>="([^"]*)"', _security(args) or '')
        account = found.group(1) if found else ''
    return account, secret.rstrip('\n')


def secret(name):
    """The secret for `name` (jira, qa), or None."""
    value = os.environ.get(SECRETS[name])
    if value:
        return value
    found = _resolve(name)
    return found[1] if found else None


def login(name):
    """(account, password) for `name` (review), or (None, None). An env: reference holds only the
    password, so the email variable names the account then."""
    email, password = (os.environ.get(variable) for variable in LOGINS[name])
    if email and password:
        return email, password
    found = _resolve(name)
    return (found[0] or email or None, found[1]) if found else (None, None)
