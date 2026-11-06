"""A bounded read-only gh process, with safe error text."""
import subprocess
from sidequest.identity import GITHUB_REPO, GITHUB_LOGIN
from sidequest.access import AccessFailure, failure_for


def configured_author():
    return GITHUB_LOGIN or '@me'


def run_tool(args, timeout=90):
    """Run a read-only service CLI (gh, heroku). Failures are AccessFailure for that tool's service."""
    try:
        result = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise failure_for(args[0], exc) from None
    except subprocess.TimeoutExpired:
        raise AccessFailure(args[0], 'timeout') from None
    if result.returncode:
        raise failure_for(args[0], result.stderr)
    return result.stdout


def run_command(args):
    return run_tool(args)
