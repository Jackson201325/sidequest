"""Collect configured services once and retain each failed source atomically."""
import fcntl
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from sidequest import config, github, identity
from sidequest.access import access_error
from sidequest.jira import client
from sidequest.snapshots import SnapshotStore, stamp

DEFAULT_OUT = config.STATE_DIR / 'snapshots'


def collect_prs():
    if not identity.GITHUB_REPO:
        return {'enabled': False, 'open_prs': []}
    rows = github.list_open_prs(include_activity=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        prs = list(pool.map(lambda row: github.enrich_pr(row, include_threads=True, include_activity=True), rows))
    return {'enabled': True, 'repo': identity.GITHUB_REPO, 'open_prs': prs}


def collect_jira(extra_keys=()):
    if not config.get('jira', 'site'):
        return {'enabled': False, 'jira_available': True, 'tickets': []}
    account = identity.JIRA_ACCOUNT_ID or client.jira('GET', '/rest/api/3/myself').get('accountId')
    if not account:
        raise client.JiraError('Jira account could not be identified')
    projects = config.get('jira', 'projects', [])
    jql = 'assignee = currentUser() AND statusCategory != Done'
    if projects:
        jql += ' AND project IN (' + ','.join('"' + key + '"' for key in projects) + ')'
    issues = client.search(jql + ' ORDER BY created ASC', ['summary'], None)
    keys = list(dict.fromkeys([row['key'] for row in issues] + list(extra_keys)))
    with ThreadPoolExecutor(max_workers=4) as pool:
        tickets = list(pool.map(lambda key: client.fetch_one(key, include_activity=True, account_id=account), keys))
    return {'enabled': True, 'jira_available': True, 'tickets': tickets}


def collect(directory=DEFAULT_OUT, max_age=0):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / '.collect.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        store = SnapshotStore(directory)
        previous = store.read()
        if max_age and not previous.get('failures') and {'jira', 'prs'} <= set(previous['sources']):
            dates = [datetime.fromisoformat(previous['sources'][name]['generated_at']) for name in ('jira', 'prs')]
            if all(0 <= (datetime.now(identity.TZ) - date).total_seconds() < max_age for date in dates):
                return previous
        updates, failures = {}, {}
        try:
            updates['prs'] = dict(collect_prs(), generated_at=stamp())
        except (OSError, RuntimeError, ValueError, SystemExit) as exc:
            failures['prs'] = access_error('GitHub', str(exc))
        prs = updates.get('prs', previous['sources'].get('prs', {}))
        try:
            keys = [pr['ticket'] for pr in prs.get('open_prs', []) if pr.get('ticket')]
            updates['jira'] = dict(collect_jira(keys), generated_at=stamp())
        except (OSError, RuntimeError, ValueError, SystemExit, KeyError) as exc:
            failures['jira'] = access_error('Jira', str(exc))
        return store.publish(updates, failures)
