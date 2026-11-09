"""`--project NAME` on a command line: sets SIDEQUEST_PROJECT before any settings load."""
import os


def take(argv):
    """Remove the first --project NAME (or --project=NAME) from argv and export it."""
    for index, arg in enumerate(argv[1:], 1):
        if arg == '--project' and index + 1 < len(argv):
            os.environ['SIDEQUEST_PROJECT'] = argv[index + 1]
            del argv[index:index + 2]
            return
        if arg.startswith('--project='):
            os.environ['SIDEQUEST_PROJECT'] = arg.split('=', 1)[1]
            del argv[index]
            return
