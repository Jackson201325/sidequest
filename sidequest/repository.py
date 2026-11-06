"""Which repository workspace actions use. No configuration import: callers pass settings."""
import os
from pathlib import Path


def repository_from(environ, settings):
    """SIDEQUEST_REPO when it names an existing folder, else workspace.repository."""
    override = environ.get('SIDEQUEST_REPO')
    if override and Path(override).expanduser().is_dir():
        return override
    return settings.get('workspace', {}).get('repository', '')


def environment_repository(settings):
    return repository_from(os.environ, settings)
