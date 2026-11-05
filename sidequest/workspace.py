"""Preview or create one local worktree from live Git evidence; never remove one."""
import os
from pathlib import Path
import subprocess
from sidequest import config
from sidequest.workspaces import branch_name
from sidequest.worktrees import lookup


def prepare(key, summary, issue_type='', prefix=None, base='origin/main', apply=False):
    repo = Path(os.environ.get('SIDEQUEST_REPO') or config.get('workspace', 'repository') or '.').expanduser().resolve()
    def git(*args, required=True):
        result = subprocess.run(['git', '-C', str(repo), *args], text=True, capture_output=True)
        if required and result.returncode:
            raise RuntimeError('Git command failed; check the repository and base ref')
        return result
    repo = Path(git('rev-parse', '--show-toplevel').stdout.strip())
    names = git('for-each-ref', '--format=%(refname)', 'refs/heads', 'refs/remotes/origin').stdout.splitlines()
    branches = [name.removeprefix('refs/heads/').removeprefix('refs/remotes/origin/') for name in names]
    existing = lookup(key.upper(), git('worktree', 'list', '--porcelain').stdout, branches)
    if existing['state'] in ('worktree', 'main-checkout'):
        return dict(existing, created=False)
    branch = existing.get('branch') or branch_name(key, summary, issue_type, prefix)
    folder = Path(config.get('workspace', 'worktrees_dir') or repo.parent).expanduser() / branch.split('/', 1)[-1]
    if folder.exists():
        raise RuntimeError('Destination already exists; refusing to overwrite it')
    local = git('show-ref', '--verify', '--quiet', 'refs/heads/' + branch, required=False).returncode == 0
    remote = git('show-ref', '--verify', '--quiet', 'refs/remotes/origin/' + branch, required=False).returncode == 0
    source = branch if local else 'origin/' + branch if remote else base
    git('rev-parse', '--verify', '--end-of-options', source + '^{commit}')
    result = {'state': 'preview', 'path': str(folder), 'branch': branch, 'base': source, 'created': False}
    if apply:
        folder.parent.mkdir(parents=True, exist_ok=True)
        args = ['worktree', 'add'] + ([] if local else ['-b', branch]) + [str(folder), branch if local else source]
        git(*args)
        result.update(state='worktree', created=True)
    return result
