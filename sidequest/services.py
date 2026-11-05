"""A bounded read-only gh process, with safe error text."""
import re
import subprocess
from sidequest.identity import GITHUB_REPO, GITHUB_LOGIN
from sidequest.access import access_error


def configured_author():
    return GITHUB_LOGIN or '@me'


def run_command(args):
    result = subprocess.run(args, text=True, capture_output=True, timeout=90)
    if result.returncode:
        raise RuntimeError(access_error('GitHub', result.stderr))
    return result.stdout


def extract_ticket(text):
    match = re.search(r'\b([A-Z][A-Z0-9_]*)[ -](\d+)\b', text or '', re.I)
    return match.group(1).upper() + '-' + match.group(2) if match else None
