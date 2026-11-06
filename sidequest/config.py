"""Configuration separate from source, credentials and the personal installation."""
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

NAMESPACE = 'sidequest'
CONFIG_PATH = Path(os.environ.get('SIDEQUEST_CONFIG') or
                   Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / NAMESPACE / 'config.json').expanduser()
DATA_DIR = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / NAMESPACE
STATE_DIR = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / NAMESPACE


def load(path):
    try:
        data = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        raise ValueError('Cannot read configuration; check the JSON file at SIDEQUEST_CONFIG') from None
    if not isinstance(data, dict) or set(data) - {'identity', 'jira', 'github', 'heroku', 'workspace'}:
        raise ValueError('Configuration must contain only the documented sections')
    for section, values in data.items():
        if not isinstance(values, dict):
            raise ValueError('Each configuration section must be an object')
        for key, value in values.items():
            if re.search(r'token|password|secret|api.?key', key, re.I):
                raise ValueError('Keep credentials in environment variables, not in configuration')
            if section == 'jira' and key == 'projects':
                if not isinstance(value, list) or not all(isinstance(v, str) and re.fullmatch(r'[A-Z][A-Z0-9_]*', v) for v in value):
                    raise ValueError('jira.projects must be a list of Jira project keys')
            elif not isinstance(value, str):
                raise ValueError('Configuration values must be strings, except jira.projects')
    site = data.get('jira', {}).get('site', '')
    if site:
        parts = urlsplit(site)
        if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.path not in ('', '/') or parts.query or parts.fragment:
            raise ValueError('jira.site must be an HTTPS origin without credentials or a path')
    repository = data.get('github', {}).get('repository', '')
    if data.get('workspace', {}).get('terminal', 'auto') not in ('auto', 'shell', 'tmux', 'herdr'):
        raise ValueError('workspace.terminal must be auto, shell, tmux or herdr')
    if repository and not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('github.repository must look like owner/repository')
    for section, key in (('jira', 'cloud_id'), ('heroku', 'pipeline')):
        value = data.get(section, {}).get(key, '')
        if value and not re.fullmatch(r'[A-Za-z0-9-]+', value):
            raise ValueError(section + '.' + key + ' contains unsupported characters')
    try:
        ZoneInfo(data.get('identity', {}).get('timezone', 'UTC'))
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError('identity.timezone must be an installed IANA timezone') from None
    return data


SETTINGS = load(CONFIG_PATH)


def get(section, key, default=''):
    return SETTINGS.get(section, {}).get(key, default)


def workspace_repository():
    """The repository workspace actions and the dashboard both use: SIDEQUEST_REPO, then config."""
    return os.environ.get('SIDEQUEST_REPO') or get('workspace', 'repository')


def base_ref():
    return get('workspace', 'base_ref') or 'origin/main'
