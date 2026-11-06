"""A bounded read-only gh process, with safe error text."""
import os
import subprocess
from sidequest.identity import GITHUB_REPO, GITHUB_LOGIN
from sidequest.access import AccessFailure, failure_for


def configured_author():
    return GITHUB_LOGIN or '@me'


def run_tool(args, timeout=90):
    """Run a read-only service CLI (gh, heroku). Failures are AccessFailure for that tool's service."""
    tool = os.path.basename(args[0])
    try:
        result = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    except FileNotFoundError:
        raise AccessFailure(tool, 'missing_tool', tool) from None
    except subprocess.TimeoutExpired:
        raise AccessFailure(tool, 'timeout', tool) from None
    if result.returncode:
        raise failure_for(tool, result.stderr)
    return result.stdout
