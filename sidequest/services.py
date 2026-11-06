"""A bounded read-only gh process, with safe error text."""
import subprocess
from sidequest.identity import GITHUB_REPO, GITHUB_LOGIN
from sidequest.access import AccessFailure, failure_for


def configured_author():
    return GITHUB_LOGIN or '@me'


def run_command(args):
    try:
        result = subprocess.run(args, text=True, capture_output=True, timeout=90)
    except FileNotFoundError as exc:
        raise failure_for('GitHub', exc) from None
    except subprocess.TimeoutExpired:
        raise AccessFailure('GitHub', 'network') from None
    if result.returncode:
        raise failure_for('GitHub', result.stderr)
    return result.stdout
