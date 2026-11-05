"""Load the sole Jira client; implementation stays in bin/sidequest-jira.py."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("sidequest_jira_client", Path(__file__).resolve().parents[1] / "bin/sidequest-jira.py")
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)
