"""Collect configured services once and retain each failed source atomically."""
import fcntl
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from sidequest import config, github, identity
from sidequest.access import failure_for
from sidequest.jira import client
from sidequest.snapshots import SnapshotStore, stamp
from sidequest.ticket_keys import pr_ticket

DEFAULT_OUT = config.STATE_DIR / 'snapshots'


def collect_prs():
    if not identity.GITHUB_REPO:
        return {'enabled': False, 'open_prs': []}
    rows = github.list_open_prs(include_activity=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        prs = list(pool.map(lambda row: github.enrich_pr(row, include_threads=True, include_activity=True), rows))
    return {'enabled': True, 'repo': identity.GITHUB_REPO, 'open_prs': prs}


def collect_jira(prs=()):
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
    assigned = list(dict.fromkeys(row['key'] for row in issues))
    # Same rule and known prefixes as the queue (core.tickets_from), so both agree on a PR's ticket.
    # A missing, hidden or moved PR-derived key drops out instead of failing all of Jira.
    known = set(projects) | {key.rsplit('-', 1)[0] for key in assigned}
    extra = [key for key in dict.fromkeys(filter(None, (pr_ticket(pr, known) for pr in prs)))
             if key not in assigned]

    def fetch(key):
        try:
            return client.fetch_one(key, include_activity=True, account_id=account)
        except client.JiraError as exc:
            if key in extra and getattr(exc, 'status', None) in (301, 403, 404):
                return None
            raise
    with ThreadPoolExecutor(max_workers=4) as pool:
        tickets = [ticket for ticket in pool.map(fetch, assigned + extra) if ticket is not None]
    return {'enabled': True, 'jira_available': True, 'tickets': tickets}


def collect(directory=DEFAULT_OUT, max_age=0):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / '.collect.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        store = SnapshotStore(directory)
        previous = store.read()
        disabled = {name for name, enabled in (('jira', bool(config.get('jira', 'site'))),
                                               ('prs', bool(identity.GITHUB_REPO))) if not enabled}
        retained_disabled = {name for name in disabled if name in previous['sources']
                             and previous['sources'][name].get('enabled') is not False}
        if max_age and not retained_disabled and not previous.get('failures') and {'jira', 'prs'} <= set(previous['sources']):
            dates = [datetime.fromisoformat(previous['sources'][name]['generated_at']) for name in ('jira', 'prs')]
            if all(0 <= (datetime.now(identity.TZ) - date).total_seconds() < max_age for date in dates):
                return previous
        updates, failures = {}, {}
        def retain_or_update(name, source):
            if source.get('enabled') is False and name in retained_disabled:
                label, setting = ('Jira', 'jira.site') if name == 'jira' else ('GitHub', 'github.repository')
                failures[name] = label + ' is not configured; configure ' + setting + '. Previous data retained.'
            else:
                updates[name] = dict(source, generated_at=stamp())
        try:
            retain_or_update('prs', collect_prs())
        except (OSError, RuntimeError, ValueError, SystemExit, subprocess.SubprocessError) as exc:
            failures['prs'] = str(failure_for('GitHub', exc))
        prs = updates.get('prs', previous['sources'].get('prs', {}))
        try:
            retain_or_update('jira', collect_jira(prs.get('open_prs', [])))
        except (OSError, RuntimeError, ValueError, SystemExit, KeyError, subprocess.SubprocessError) as exc:
            failures['jira'] = str(failure_for('Jira', exc))
        return store.publish(updates, failures)
