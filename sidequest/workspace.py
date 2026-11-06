"""One owner for local Git workspace planning and execution. No terminal or HTTP I/O."""
from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Optional

from sidequest.workspaces import branch_name
from sidequest.worktrees import lookup


@dataclass(frozen=True)
class WorkspacePlan:
    repository: str
    key: str
    summary: str
    issue_type: str
    prefix: Optional[str]
    base_ref: str
    state: str
    path: str
    branch: str
    base: str = ''
    revision: str = ''
    local: bool = False

    def result(self, created=False):
        result = {'state': 'worktree' if created else self.state, 'path': self.path,
                  'branch': self.branch, 'created': created}
        if self.base:
            result['base'] = self.base
        return result


class GitWorkspace:
    def __init__(self, repository, worktrees_dir=None, base_ref='origin/main'):
        self.repository = Path(repository).expanduser().resolve()
        self.worktrees_dir = Path(worktrees_dir).expanduser().resolve() if worktrees_dir else None
        self.base_ref = base_ref

    def _git(self, *args, required=True):
        result = subprocess.run(['git', '-C', str(self.repository), *args], text=True, capture_output=True)
        if required and result.returncode:
            lines = [line.strip() for line in result.stderr.splitlines() if line.strip()]
            detail = next((line for line in lines if line.startswith(('fatal:', 'error:'))), lines[-1] if lines else '')
            raise RuntimeError('Git command failed' + (': ' + detail[:200] if detail else '; check the repository and base ref'))
        return result

    def preview(self, key, summary, issue_type='', prefix=None, base=None):
        """Inspect current local evidence without fetching, creating or switching anything."""
        key = key.upper()
        proposed = branch_name(key, summary, issue_type, prefix)
        base = base or self.base_ref
        repo = self._git('rev-parse', '--show-toplevel').stdout.strip()
        names = self._git('for-each-ref', '--format=%(refname)', 'refs/heads', 'refs/remotes/origin').stdout.splitlines()
        branches = [name.removeprefix('refs/heads/').removeprefix('refs/remotes/origin/') for name in names]
        existing = lookup(key, self._git('worktree', 'list', '--porcelain').stdout, branches)
        intent = dict(repository=repo, key=key, summary=summary, issue_type=issue_type,
                      prefix=prefix, base_ref=base)
        if existing['state'] in ('worktree', 'main-checkout'):
            return WorkspacePlan(**intent, **existing)
        branch = existing.get('branch') or proposed
        folder = (self.worktrees_dir or Path(repo).parent) / branch.split('/', 1)[-1]
        if folder.exists() or folder.is_symlink():
            raise RuntimeError('Destination already exists; refusing to overwrite it')
        local = self._git('show-ref', '--verify', '--quiet', 'refs/heads/' + branch, required=False).returncode == 0
        remote = self._git('show-ref', '--verify', '--quiet', 'refs/remotes/origin/' + branch, required=False).returncode == 0
        source = branch if local else 'origin/' + branch if remote else base
        revision = self._git('rev-parse', '--verify', '--end-of-options', source + '^{commit}').stdout.strip()
        return WorkspacePlan(**intent, state='preview', path=str(folder), branch=branch,
                             base=source, revision=revision, local=local)

    def apply(self, plan):
        """Reinspect before executing a plan; changed evidence requires a new preview."""
        current = self.preview(plan.key, plan.summary, plan.issue_type, plan.prefix, plan.base_ref)
        if current != plan:
            raise RuntimeError('Workspace changed since preview; preview again before applying')
        if current.state != 'preview':
            return current.result()
        Path(current.path).parent.mkdir(parents=True, exist_ok=True)
        # An existing remote branch keeps tracking origin/<branch>. A new branch must not track its
        # base: with origin/main upstream, the first `git push` fails and suggests pushing to main.
        # The revision above detects stale plans; Git rejects concurrent path/branch conflicts.
        new_branch = not current.local and current.base != 'origin/' + current.branch
        args = ['worktree', 'add'] + ([] if current.local else ['-b', current.branch]) + (['--no-track'] if new_branch else [])
        self._git(*args, current.path, current.branch if current.local else current.base)
        return current.result(created=True)


def prepare(key, summary, issue_type='', prefix=None, base='origin/main', apply=False):
    """Compatibility adapter; new CLI/TUI callers use WorkspaceWorkflow."""
    import os
    from sidequest import config
    values = config.SETTINGS.get('workspace', {})
    workspace = GitWorkspace(os.environ.get('SIDEQUEST_REPO') or values.get('repository') or '.',
                             values.get('worktrees_dir'))
    plan = workspace.preview(key, summary, issue_type, prefix, base)
    return workspace.apply(plan) if apply else plan.result()
