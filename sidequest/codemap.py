"""Read-only code map: modules, calls, file writes, config reads and programs, from the AST only."""
import ast
from pathlib import Path

from sidequest.codemap_view import render  # noqa: F401  (public: codemap.render)

FOLDERS = ('bin', 'sidequest', 'ticket-tui')
LAYERS = {
    'config': {'config', 'credentials', 'projects', 'project_flag'},
    'storage': {'snapshots', 'questions'},
    'services': {'access', 'collector', 'environments', 'github', 'gitutil', 'jira', 'repository', 'review_apps',
                 'reviews', 'services'},
    'workspace': {'application', 'cleanup', 'herdr', 'herdr_session', 'start', 'sync', 'terminal', 'terminal_mode',
                  'tmux', 'updates', 'workspace', 'workspaces', 'worktrees'},
}
LAYER_ORDER = ['entry', 'ui', 'workspace', 'core', 'services', 'storage', 'config', 'tests']
WRITES = {'write_text', 'write_bytes', 'mkdir', 'unlink', 'rmdir', 'touch', 'rename', 'replace', 'symlink_to'}
MODULE_WRITES = {('os', 'replace'), ('os', 'rename'), ('os', 'remove'), ('os', 'unlink'), ('os', 'makedirs'),
                 ('os', 'mkdir'), ('shutil', 'copyfile'), ('shutil', 'copy'), ('shutil', 'copy2'),
                 ('shutil', 'copytree'), ('shutil', 'move'), ('shutil', 'rmtree')}
RUNNERS = {'run', 'Popen', 'check_output', 'check_call', 'call', 'run_tool', 'RUN', 'execvp', 'execv'}


def _python_files(root, tests):
    found = []
    for folder in FOLDERS + (('tests',) if tests else ()):
        for path in sorted((root / folder).glob('*')):
            if not path.is_file():
                continue
            name = path.name
            if not tests and name.startswith('test_'):
                continue
            if path.suffix == '.py' or (folder == 'bin' and not path.suffix and _is_python_script(path)):
                found.append(path)
    return found


def _is_python_script(path):
    try:
        with path.open(encoding='utf-8') as handle:
            return 'python' in handle.readline()
    except (OSError, UnicodeError):
        return False


def _layer(rel):
    folder, stem = rel.split('/', 1)[0], Path(rel).stem
    if folder == 'bin':
        return 'entry'
    if folder == 'tests' or stem.startswith('test_'):
        return 'tests'
    if folder == 'ticket-tui':
        return 'ui'
    return next((name for name, stems in LAYERS.items() if stem in stems), 'core')


class _Module:
    def __init__(self, root, path):
        self.path = path
        self.rel = path.relative_to(root).as_posix()
        self.folder = self.rel.split('/', 1)[0]
        self.tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        self.aliases = {}   # local name -> module rel path
        self.symbols = {}   # local name -> (module rel path, attribute)


def _resolve_module(dotted, importer, paths):
    path = dotted.replace('.', '/')
    for candidate in (path + '.py', path + '/__init__.py'):
        if candidate in paths:
            return candidate
    sibling = importer.folder + '/' + dotted + '.py'
    return sibling if '.' not in dotted and sibling in paths else None


def _read_imports(module, paths):
    imports = set()
    for node in ast.walk(module.tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                target = _resolve_module(alias.name, module, paths)
                if target:
                    imports.add(target)
                    if alias.asname or '.' not in alias.name:
                        module.aliases[alias.asname or alias.name] = target
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            base = _resolve_module(node.module, module, paths)
            for alias in node.names:
                local = alias.asname or alias.name
                sub = _resolve_module(node.module + '.' + alias.name, module, paths)
                if sub:
                    imports.add(sub)
                    module.aliases[local] = sub
                elif base:
                    imports.add(base)
                    module.symbols[local] = (base, alias.name)
    imports.discard(module.rel)
    return imports


def _string(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


class _Function:
    def __init__(self, module, name, node, owner=None):
        self.module, self.name, self.owner = module, name, owner
        self.id = module.rel + ':' + name
        self.line = getattr(node, 'lineno', 1)
        self.doc = (ast.get_docstring(node) or '').split('\n', 1)[0] if not isinstance(node, ast.Module) else ''
        self.body = node.body if isinstance(node, ast.Module) else [node]
        self.raw_calls, self.writes, self.config, self.env, self.programs, self.runs = [], [], [], [], [], []


def _functions(module):
    found = [_Function(module, '<module>', module.tree)]
    top = []
    for node in module.tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found.append(_Function(module, node.name, node))
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    found.append(_Function(module, node.name + '.' + item.name, item, owner=node.name))
        else:
            top.append(node)
    found[0].body = top
    return found


def _walk(nodes):
    found, stack = [], list(nodes)
    while stack:
        node = stack.pop()
        found.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return sorted(found, key=lambda node: (getattr(node, 'lineno', 0), getattr(node, 'col_offset', 0)))


def _is_config(expr, module):
    if isinstance(expr, ast.Name):
        target = module.aliases.get(expr.id)
        return bool(target) and target.endswith('/config.py')
    if isinstance(expr, ast.Attribute):
        return expr.attr == 'config'
    return False


def _is_config_get(func, module):
    if isinstance(func, ast.Name):
        return (func.id == 'get' and module.rel.endswith('/config.py')) or \
            (module.symbols.get(func.id, ('', ''))[0].endswith('/config.py') and module.symbols[func.id][1] == 'get')
    return isinstance(func, ast.Attribute) and func.attr == 'get' and _is_config(func.value, module)


def _is_settings(expr, module):
    if _is_config(expr, module):
        return True
    name = expr.id if isinstance(expr, ast.Name) else expr.attr if isinstance(expr, ast.Attribute) else ''
    return 'setting' in name.lower() or 'config' in name.lower() or (name == 'data' and module.rel.endswith('/config.py'))


def _section_of(value, module, sections):
    """The settings section an expression holds, e.g. config.get('workspace') or settings['workspace']."""
    if isinstance(value, ast.Subscript) and _string(_slice(value)) in sections and _is_settings(value.value, module):
        return _string(_slice(value))
    if isinstance(value, ast.Call) and value.args and _string(value.args[0]) in sections:
        second = value.args[1] if len(value.args) > 1 else None
        if second is None or not _string(second):
            func = value.func
            if _is_config_get(func, module) or (isinstance(func, ast.Attribute) and func.attr == 'get' and _is_settings(func.value, module)):
                return _string(value.args[0])
    if isinstance(value, ast.BoolOp):
        return next((s for s in (_section_of(v, module, sections) for v in value.values) if s), None)
    return None


def _examine(function, scripts, sections):
    module, held = function.module, {}
    for node in _walk(function.body):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            section = _section_of(node.value, module, sections)
            if section:
                held[node.targets[0].id] = section
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                function.raw_calls.append(('name', func.id))
                if func.id == 'open':
                    _note_open(function, node, 1)
                if _is_config_get(func, module):
                    _add_config(function, node.args)
            elif isinstance(func, ast.Attribute):
                value = func.value
                if isinstance(value, ast.Name):
                    function.raw_calls.append(('attr', value.id, func.attr))
                _note_write(function, node, func)
                _note_config(function, node, func, module, sections, held)
                _note_env(function, node, func)
            _note_program(function, node, func)
        elif isinstance(node, ast.Subscript):
            _note_env_subscript(function, node)
            if isinstance(node.value, ast.Name) and node.value.id in held and _string(_slice(node)):
                _add_config(function, [ast.Constant(held[node.value.id]), _slice(node)])
        text = _string(node)
        if text:
            name = text.rsplit('/', 1)[-1]
            if name in scripts and scripts[name] != module.rel and scripts[name] not in function.runs:
                function.runs.append(scripts[name])


def _note_write(function, node, func):
    value = func.value
    if isinstance(value, ast.Name) and (value.id, func.attr) in MODULE_WRITES:
        function.writes.append({'op': value.id + '.' + func.attr, 'line': node.lineno})
    elif func.attr in WRITES and not (isinstance(value, ast.Name) and value.id in ('os', 'shutil', 'json', 'str')):
        if func.attr == 'replace' and not (node.args and not _string(node.args[0])):
            return  # str.replace('a', 'b') is not a file move
        function.writes.append({'op': func.attr, 'line': node.lineno})
    elif func.attr == 'open':
        _note_open(function, node, 0 if node.args and _string(node.args[0]) else 1)


def _note_open(function, node, index):
    mode = node.args[index] if len(node.args) > index else next((k.value for k in node.keywords if k.arg == 'mode'), None)
    text = _string(mode) if mode is not None else None
    if text and any(flag in text for flag in 'wax+'):
        function.writes.append({'op': 'open(' + text + ')', 'line': node.lineno})


def _add_config(function, args):
    pair = [_string(args[0]), _string(args[1])] if len(args) > 1 else [None, None]
    if all(pair) and pair not in function.config:
        function.config.append(pair)


def _note_config(function, node, func, module, sections, held):
    if func.attr != 'get' or not node.args or not _string(node.args[0]):
        return
    first = _string(node.args[0])
    if len(node.args) > 1 and _string(node.args[1]) and first in sections and _is_settings(func.value, module):
        _add_config(function, node.args)
        return
    value = func.value
    section = held.get(value.id) if isinstance(value, ast.Name) else _section_of(value, module, sections)
    if section:
        _add_config(function, [ast.Constant(section), node.args[0]])


def _slice(node):
    return node.slice


def _note_env(function, node, func):
    value = func.value
    if func.attr == 'get' and node.args and isinstance(value, ast.Attribute) and value.attr == 'environ':
        _add_env(function, _string(node.args[0]))
    elif func.attr == 'get' and node.args and isinstance(value, ast.Name) and value.id in ('environ', 'env', 'environment'):
        _add_env(function, _string(node.args[0]))
    elif func.attr == 'getenv' and node.args:
        _add_env(function, _string(node.args[0]))


def _note_env_subscript(function, node):
    value = node.value
    if (isinstance(value, ast.Attribute) and value.attr == 'environ') or (isinstance(value, ast.Name) and value.id == 'environ'):
        _add_env(function, _string(_slice(node)))


def _add_env(function, name):
    if name and name.isupper() and name not in function.env:
        function.env.append(name)


def _note_program(function, node, func):
    name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ''
    if name not in RUNNERS or not node.args:
        return
    first = node.args[0]
    if isinstance(first, (ast.List, ast.Tuple)) and first.elts:
        program = _string(first.elts[0])
        if program and ' ' not in program and program not in function.programs:
            function.programs.append(program.rsplit('/', 1)[-1])


def _resolve_calls(function, known):
    module, resolved = function.module, []
    for raw in function.raw_calls:
        target = None
        if raw[0] == 'name':
            name = raw[1]
            if name in module.symbols:
                base, attr = module.symbols[name]
                target = _callable(base, attr, known)
            else:
                target = _callable(module.rel, name, known)
        elif raw[1] in ('self', 'cls') and function.owner:
            target = _callable(module.rel, function.owner + '.' + raw[2], known)
        elif raw[1] in module.aliases:
            target = _callable(module.aliases[raw[1]], raw[2], known)
        if target and target != function.id and target not in resolved:
            resolved.append(target)
    return resolved


def _callable(rel, name, known):
    for candidate in (rel + ':' + name, rel + ':' + name + '.__init__'):
        if candidate in known:
            return candidate
    return None


def _declared_keys(modules):
    config = next((m for m in modules if m.rel == 'sidequest/config.py'), None)
    if not config:
        return {}
    for node in config.tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'KEYS' for t in node.targets):
            try:
                value = ast.literal_eval(node.value)
            except ValueError:
                return {}
            return {section: list(keys) for section, keys in value.items()}
    return {}


def scan(root, tests=False):
    """Map the checkout at `root`. Reads files only; never imports or runs them."""
    root = Path(root).resolve()
    modules = [_Module(root, path) for path in _python_files(root, tests)]
    paths = {module.rel for module in modules}
    scripts = {Path(rel).name: rel for rel in paths if rel.startswith('bin/')}
    imports = sorted([module.rel, target] for module in modules for target in _read_imports(module, paths))
    declared = _declared_keys(modules)
    functions = [function for module in modules for function in _functions(module)]
    known = {function.id for function in functions}
    for function in functions:
        _examine(function, scripts, set(declared))
    read = set()
    rows = []
    for function in functions:
        read.update(tuple(pair) for pair in function.config)
        rows.append({'id': function.id, 'module': function.module.rel, 'name': function.name, 'line': function.line,
                     'doc': function.doc, 'calls': _resolve_calls(function, known), 'writes': function.writes,
                     'config': function.config, 'env': function.env, 'programs': function.programs, 'runs': function.runs})
    declared_pairs = [[section, key] for section, keys in declared.items() for key in keys]
    return {
        'modules': [{'id': m.rel, 'layer': _layer(m.rel), 'doc': (ast.get_docstring(m.tree) or '').split('\n', 1)[0],
                     'lines': len(m.path.read_text(encoding='utf-8').splitlines())} for m in modules],
        'functions': rows,
        'imports': imports,
        'layers': LAYER_ORDER,
        'config': {
            'declared': declared_pairs,
            'unused': [pair for pair in declared_pairs if tuple(pair) not in read],
            'unknown': sorted([list(pair) for pair in read if declared and pair[0] in declared and pair[1] not in declared[pair[0]]]),
        },
    }
