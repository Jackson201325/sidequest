"""Configuration separate from source, credentials and the personal installation."""
import json
import os
from pathlib import Path
import re
import shlex
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

NAMESPACE = 'sidequest'
CONFIG_ROOT = (Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / NAMESPACE).expanduser()
PROJECTS_DIR = CONFIG_ROOT / 'projects'


def _read(path):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        raise ValueError('Cannot read configuration; check the JSON file at ' + str(path)) from None


def profiles(root=PROJECTS_DIR):
    """{name: projects/<name>/config.json} for every project profile."""
    try:
        folders = sorted(Path(root).iterdir())
    except OSError:
        return {}
    return {folder.name: folder / 'config.json' for folder in folders
            if re.fullmatch(r'[a-z0-9][a-z0-9_-]*', folder.name) and (folder / 'config.json').is_file()}


def select_project(environ, cwd, root=PROJECTS_DIR):
    """SIDEQUEST_PROJECT, else the profile whose repository or worktrees folder holds cwd (the
    deepest one), else the only profile; '' means shared settings only."""
    found = profiles(root)
    named = environ.get('SIDEQUEST_PROJECT')
    if named:
        if named not in found:
            raise ValueError('Unknown project ' + repr(named) + '; known: ' + (', '.join(found) or 'none') +
                             ' (folders in ' + str(root) + ')')
        return named
    matches = []
    for name, path in found.items():
        workspace = _read(path).get('workspace')
        for key in ('repository', 'worktrees_dir'):
            folder = workspace.get(key) if isinstance(workspace, dict) else None
            if isinstance(folder, str) and folder and cwd:
                folder = Path(folder).expanduser().resolve()
                if cwd == folder or folder in cwd.parents:
                    matches.append((len(folder.parts), name))
    if matches:
        return max(matches)[1]
    return next(iter(found)) if len(found) == 1 else ''


def _cwd():
    try:
        return Path.cwd().resolve()
    except OSError:
        return None


_EXPLICIT = os.environ.get('SIDEQUEST_CONFIG')
CONFIG_PATH = Path(_EXPLICIT or CONFIG_ROOT / 'config.json').expanduser()
PROJECT = '' if _EXPLICIT else select_project(os.environ, _cwd())
PROJECT_PATH = PROJECTS_DIR / PROJECT / 'config.json' if PROJECT else None
if PROJECT:
    os.environ['SIDEQUEST_PROJECT'] = PROJECT  # commands started from here keep this project
_STORAGE = Path(NAMESPACE, 'projects', PROJECT) if PROJECT else Path(NAMESPACE)
DATA_DIR = Path(os.environ.get('SIDEQUEST_DATA_DIR') or
                Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / _STORAGE).expanduser()
STATE_DIR = Path(os.environ.get('SIDEQUEST_STATE_DIR') or
                 Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / _STORAGE).expanduser()
# Every documented setting; SIDEQUEST_<SECTION>_<KEY> sets one from the environment.
KEYS = {
    'identity': ('display_name', 'git_author', 'timezone'),
    'jira': ('site', 'email', 'account_id', 'cloud_id', 'projects', 'start_status', 'start_from', 'start_ask'),
    'github': ('repository', 'username', 'pr_tickets', 'branch_tickets'),
    'heroku': ('pipeline',),
    'workspace': ('repository', 'plans_dir', 'worktrees_dir', 'base_ref', 'agent_command', 'terminal',
                  'tmux_session', 'browser', 'copy_files', 'agent_tasks', 'reports_dir', 'report_command', 'windows', 'on_up'),
    'app': ('url', 'switch_command', 'current_command', 'running_command', 'required_files', 'ttl_minutes',
            'wait_minutes'),
    'qa': ('browser', 'email'),
    'checks': ('test', 'lint'),
    'credentials': ('jira', 'review', 'qa'),
    'sync': ('tickets_jql', 'open_prs', 'update', 'cleanup'),
}
# Credentials, read where they are used; they never enter settings.
NOT_SETTINGS = {'SIDEQUEST_JIRA_TOKEN', 'SIDEQUEST_QA_PASSWORD'}


def from_environment(data, environ):
    """The file's settings with SIDEQUEST_<SECTION>_<KEY> variables applied on top."""
    data = {section: dict(values) if isinstance(values, dict) else values for section, values in data.items()}
    for name, value in sorted((environ or {}).items()):
        section = next((s for s in KEYS if name.startswith('SIDEQUEST_' + s.upper() + '_')), None)
        if not section or name in NOT_SETTINGS:
            continue
        key = name[len('SIDEQUEST_' + section + '_'):].lower()
        if key not in KEYS[section]:
            raise ValueError(name + ' is not a Sidequest setting')
        if key == 'projects':
            value = [part.strip() for part in value.split(',') if part.strip()]
        elif key in ('pr_tickets', 'branch_tickets', 'agent_tasks', 'windows', 'on_up'):
            try:
                value = json.loads(value)
            except ValueError:
                raise ValueError(name + ' must be JSON (' + key + ')') from None
        target = data.setdefault(section, {})
        if not isinstance(target, dict):
            raise ValueError('Each configuration section must be an object')
        target[key] = value
    return data


def load(path, environ=None, project=None):
    """Settings from the JSON file, the project profile over it section by section, then
    SIDEQUEST_<SECTION>_<KEY> variables in `environ`; validated."""
    data = _read(path)
    if project and isinstance(data, dict):
        overlay = _read(project)
        if not isinstance(overlay, dict):
            raise ValueError('Configuration must contain only the documented sections')
        for section, values in overlay.items():
            merged = data.get(section)
            data[section] = dict(merged, **values) if isinstance(merged, dict) and isinstance(values, dict) else values
    if isinstance(data, dict):
        data = from_environment(data, environ)
    if not isinstance(data, dict) or set(data) - set(KEYS):
        raise ValueError('Configuration must contain only the documented sections')
    for section, values in data.items():
        if not isinstance(values, dict):
            raise ValueError('Each configuration section must be an object')
        for key, value in values.items():
            if re.search(r'token|password|secret|api.?key', key, re.I):
                raise ValueError('Keep credentials in environment variables, not in configuration')
            if section == 'github' and key in ('pr_tickets', 'branch_tickets'):
                pattern = r'\d+' if key == 'pr_tickets' else r'[^\s]+'
                if not isinstance(value, dict) or not all(
                        isinstance(k, str) and re.fullmatch(pattern, k) and isinstance(v, str) and
                        re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*-\d+', v) for k, v in value.items()):
                    raise ValueError('github.' + key + ' must map ' + ('PR numbers' if key == 'pr_tickets' else 'branch names') +
                                     ' to Jira keys such as APP-123')
            elif section == 'credentials':
                if key not in KEYS['credentials'] or not isinstance(value, str) or not re.fullmatch(
                        r'keychain:[^/\s]+(/\S+)?|env:[A-Za-z_][A-Za-z0-9_]*', value):
                    raise ValueError('credentials.' + str(key) + ' must name where the secret lives (keychain:SERVICE, '
                                     'keychain:SERVICE/ACCOUNT or env:NAME), never the secret itself; known names: '
                                     + ', '.join(KEYS['credentials']))
            elif section == 'workspace' and key == 'windows':
                if not isinstance(value, list) or not all(
                        isinstance(window, dict) and isinstance(window.get('name'), str) and window['name']
                        and set(window) <= {'name', 'command', 'cwd', 'at', 'stay', 'keys'}
                        and window.get('at', 'start') in ('start', 'end') and isinstance(window.get('stay', False), bool)
                        and all(isinstance(window.get(k, ''), str) for k in ('command', 'cwd', 'keys')) for window in value):
                    raise ValueError('workspace.windows must be a list of {name, command?, cwd?, at? (start or end), '
                                     'stay? (true or false), keys?} objects')
            elif section == 'workspace' and key == 'on_up':
                if not isinstance(value, list) or not all(isinstance(command, str) and command for command in value):
                    raise ValueError('workspace.on_up must be a list of commands')
            elif section == 'workspace' and key == 'agent_tasks':
                if not isinstance(value, list) or not all(
                        isinstance(task, dict) and {'label', 'prompt'} <= set(task) <= {'label', 'prompt', 'skill'}
                        and all(isinstance(v, str) and v for v in task.values()) for task in value):
                    raise ValueError('workspace.agent_tasks must be a list of {label, prompt, optional skill} '
                                     'objects with text values')
            elif section == 'jira' and key == 'projects':
                if not isinstance(value, list) or not all(isinstance(v, str) and re.fullmatch(r'[A-Z][A-Z0-9_]*', v) for v in value):
                    raise ValueError('jira.projects must be a list of Jira project keys')
            elif not isinstance(value, str):
                raise ValueError('Configuration values must be strings, except jira.projects, the github ticket links '
                                 'and workspace.agent_tasks, windows and on_up')
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
    for key, allowed in (('open_prs', ('on', 'off')), ('update', ('on', 'off')), ('cleanup', ('off', 'ask', 'on'))):
        value = data.get('sync', {}).get(key)
        if value is not None and value not in allowed:
            raise ValueError('sync.' + key + ' must be ' + ' or '.join(allowed))
    app = data.get('app', {})
    if set(app) - {'url', 'switch_command', 'current_command', 'running_command', 'required_files',
                   'ttl_minutes', 'wait_minutes'}:
        raise ValueError('app supports url, switch_command, current_command, running_command, '
                         'required_files, ttl_minutes and wait_minutes')
    if app.get('url') and urlsplit(app['url']).scheme not in ('http', 'https'):
        raise ValueError('app.url must be an http or https address')
    for key in ('ttl_minutes', 'wait_minutes'):
        if app.get(key) and not app[key].isdigit():
            raise ValueError('app.' + key + ' must be a whole number of minutes')
    for key in ('switch_command', 'current_command', 'running_command', 'required_files'):
        try:
            shlex.split(app.get(key, ''))
        except ValueError:
            raise ValueError('app.' + key + ' has unbalanced quotes') from None
    for section, key in (('jira', 'cloud_id'), ('heroku', 'pipeline')):
        value = data.get(section, {}).get(key, '')
        if value and not re.fullmatch(r'[A-Za-z0-9-]+', value):
            raise ValueError(section + '.' + key + ' contains unsupported characters')
    try:
        ZoneInfo(data.get('identity', {}).get('timezone', 'UTC'))
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError('identity.timezone must be an installed IANA timezone') from None
    return data


SETTINGS = load(CONFIG_PATH, os.environ, PROJECT_PATH)


def get(section, key, default=''):
    return SETTINGS.get(section, {}).get(key, default)


def workspace_repository():
    """The repository workspace actions and the dashboard both use."""
    from sidequest.repository import environment_repository
    return environment_repository(SETTINGS)


def base_ref():
    return get('workspace', 'base_ref') or 'origin/main'
