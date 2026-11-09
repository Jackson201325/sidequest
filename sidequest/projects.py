"""Adopting a project: write a profile from the example settings, then check what is set and what works."""
import json
from pathlib import Path
import re
import shutil
import subprocess

from sidequest import config, credentials

ROOT = Path(__file__).resolve().parents[1]
SECRET_STEPS = {
    'jira': ('Jira API token', 'YOUR_JIRA_EMAIL'),
    'review': ('review-app QA login', 'QA_LOGIN_EMAIL'),
    'qa': ('local QA password', 'local-qa'),
}


def init(name, repository):
    """Write projects/NAME/config.json and skills/; return the lines to print."""
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', name):
        raise ValueError('Project names use lowercase letters, digits, - and _ (for example "acme-web")')
    folder = config.PROJECTS_DIR / name
    if (folder / 'config.json').exists():
        raise ValueError('Project ' + name + ' already exists: ' + str(folder / 'config.json'))
    repository = Path(repository).expanduser().resolve()
    if not repository.is_dir():
        raise ValueError('No folder at ' + str(repository) + '; pass the project\'s main checkout with --repo')
    settings = json.loads((ROOT / 'config.example.json').read_text())
    settings.pop('identity', None)
    settings['workspace'].update(repository=str(repository), worktrees_dir=str(repository.parent), tmux_session=name)
    settings['credentials'] = {key: 'keychain:sidequest-' + name + '-' + key for key in credentials.NAMES}
    (folder / 'skills').mkdir(parents=True, exist_ok=True)
    (folder / 'config.json').write_text(json.dumps(settings, indent=2) + '\n')
    (folder / 'config.json').chmod(0o600)
    shared = config.CONFIG_ROOT / 'config.json'
    lines = ['Created ' + str(folder / 'config.json')]
    if not shared.exists():
        shared.write_text(json.dumps({'identity': {'display_name': '', 'git_author': '', 'timezone': 'UTC'}}, indent=2) + '\n')
        lines.append('Created ' + str(shared) + ' (identity, shared by every project)')
    lines += ['', 'Next:',
              '1. Fill in Jira, GitHub, Heroku, app, qa and checks in ' + str(folder / 'config.json') +
              ' (empty values are off; README "Adopt a project" lists each one).',
              '2. Store the secrets you need in the Keychain; each command asks for the secret (delete the unused '
              'names under "credentials"):']
    for key, (what, account) in SECRET_STEPS.items():
        lines.append('   ' + what + ': security add-generic-password -s sidequest-' + name + '-' + key + ' -a ' + account + ' -w')
    lines += ['3. Check it: sidequest-data --project ' + name + ' project check',
              '4. Optional: put workflow additions (WORKFLOW.md) or replacements (WORKFLOW.replace.md) in '
              + str(folder / 'skills') + '.']
    return lines


def _git_repository(path):
    try:
        return subprocess.run(['git', '-C', str(path), 'rev-parse', '--git-dir'], capture_output=True,
                              timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def check():
    """(lines, failed): one line per part, OK / MISSING / FAIL / OFF. Never prints a secret."""
    rows = []

    def row(state, text):
        rows.append(state.ljust(9) + text)

    if not config.PROJECT:
        row('FAIL', 'no project selected: run this inside a project folder or pass --project NAME (known: ' +
            (', '.join(config.profiles()) or 'none') + ')')
        return rows, True
    row('OK', 'project: ' + config.PROJECT + ' (' + str(config.PROJECT_PATH) + ')')
    repository = config.get('workspace', 'repository')
    if not repository:
        row('FAIL', 'repository: workspace.repository is not set')
    elif _git_repository(Path(repository).expanduser()):
        row('OK', 'repository: ' + repository)
    else:
        row('FAIL', 'repository: no Git checkout at ' + repository)
    author = config.get('identity', 'git_author')
    row('OK' if author else 'MISSING', 'identity.git_author' + (': ' + author if author else ' (your commits in the standup)'))

    if config.get('jira', 'site'):
        for key in ('email', 'projects'):
            row('OK' if config.get('jira', key) else 'MISSING', 'jira.' + key)
        ref = credentials.reference('jira') or 'SIDEQUEST_JIRA_TOKEN'
        found = credentials.secret('jira') is not None
        row('OK' if found else 'FAIL', 'Jira token: ' + ('found' if found else 'not found') + ' (' + ref + ')')
    else:
        row('OFF', 'Jira (jira.site is not set)')

    if config.get('github', 'repository'):
        row('OK', 'github.repository: ' + config.get('github', 'repository'))
        try:
            signed_in = subprocess.run(['gh', 'auth', 'status'], capture_output=True, timeout=20).returncode == 0
        except (OSError, subprocess.SubprocessError):
            signed_in = False
        row('OK' if signed_in else 'FAIL', 'GitHub sign-in' + ('' if signed_in else ': run gh auth login'))
    else:
        row('OFF', 'GitHub (github.repository is not set)')

    if config.get('heroku', 'pipeline'):
        row('OK' if shutil.which('heroku') else 'FAIL', 'Heroku pipeline ' + config.get('heroku', 'pipeline') +
            ('' if shutil.which('heroku') else ': the heroku CLI is not installed'))
    else:
        row('OFF', 'Heroku review apps')
    row('OK' if config.get('app', 'switch_command') else 'OFF',
        'shared app (sqapp)' + (': ' + config.get('app', 'switch_command') if config.get('app', 'switch_command') else ''))
    for key, label in (('test', 'tests'), ('lint', 'lint')):
        value = config.get('checks', key)
        row('OK' if value else 'OFF', label + (': ' + value if value else ''))
    for key, label in (('review', 'review-app login'), ('qa', 'local QA password')):
        ref = credentials.reference(key)
        if ref:
            found = (credentials.login(key)[1] if key == 'review' else credentials.secret(key)) is not None
            row('OK' if found else 'MISSING', label + ': ' + ('found' if found else 'not found') + ' (' + ref + ')')
    skills = sorted(path.name for path in (config.PROJECTS_DIR / config.PROJECT / 'skills').glob('*.md'))
    row('OK' if skills else 'OFF', 'project skills' + (': ' + ', '.join(skills) if skills else ' (generic skills)'))
    return rows, any(line.startswith('FAIL') for line in rows)
