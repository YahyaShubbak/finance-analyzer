"""How the app's modules may depend on each other — read from the imports
in the source, wherever they stand.

These rules hold; a change that breaks one usually put a helper into the
wrong module. The way out is to move the helper to a module both sides may
use (app.iban, app.services.rule_patterns, app.services.import_reading are
such modules), not to hide the import inside a function.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"

# Imports that stay inside a function on purpose: (module, imported module, name).
READ_WHEN_CALLED = {
    # the engine in use at that moment — a restored backup and the tests replace it
    ("app.services.reset_service", "app.db.session", "engine"),
}
# These never import anything that stands above them.
FOUNDATIONS = ("app.db", "app.importers", "app.normalization")
ABOVE_FOUNDATIONS = ("app.services", "app.reconciliation", "app.schemas", "app.api", "app.main")


def _modules() -> dict[str, Path]:
    found = {}
    for path in APP.rglob("*.py"):
        if "migrations" in path.parts:
            continue  # run by Alembic, not imported by the app
        parts = ("app", *path.relative_to(APP).with_suffix("").parts)
        found[".".join(parts[:-1] if parts[-1] == "__init__" else parts)] = path
    return found


MODULES = _modules()


class _Import:
    def __init__(self, module: str, line: int, target: str, name: str | None, at_top: bool):
        self.module, self.line, self.target, self.name, self.at_top = module, line, target, name, at_top

    def __repr__(self) -> str:
        what = f"{self.target}.{self.name}" if self.name else self.target
        return f"{self.module}:{self.line} imports {what}"


def _imports() -> list[_Import]:
    """Every import of one of the app's modules: who, where, what."""
    found = []
    for module, path in MODULES.items():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        # (an import under a module-level `if` or `try` still runs when the module is imported)
        top = {id(n) for node in tree.body for n in (ast.walk(node) if isinstance(node, (ast.If, ast.Try)) else [node])}
        for node in ast.walk(tree):
            at_top = id(node) in top
            if isinstance(node, ast.Import):
                found += [_Import(module, node.lineno, a.name, None, at_top) for a in node.names if a.name in MODULES]
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0, f"{module}:{node.lineno}: relative import — the checks here read absolute ones"
                if node.module not in MODULES:
                    continue
                for alias in node.names:
                    submodule = f"{node.module}.{alias.name}"
                    if submodule in MODULES:  # from app.services import review_service
                        found.append(_Import(module, node.lineno, submodule, None, at_top))
                    else:
                        found.append(_Import(module, node.lineno, node.module, alias.name, at_top))
    return found


IMPORTS = _imports()


def _graph() -> dict[str, set[str]]:
    graph = defaultdict(set)
    for imp in IMPORTS:
        graph[imp.module].add(imp.target)
        # importing a.b.c runs the packages a and a.b first — unless the importer is part of them
        parent = imp.target.rsplit(".", 1)[0]
        while "." in parent:
            if parent in MODULES and not imp.module.startswith(parent + ".") and imp.module != parent:
                graph[imp.module].add(parent)
            parent = parent.rsplit(".", 1)[0]
    return graph


def _reachable(start: str, graph: dict[str, set[str]]) -> set[str]:
    seen, todo = set(), list(graph.get(start, ()))
    while todo:
        module = todo.pop()
        if module not in seen:
            seen.add(module)
            todo.extend(graph.get(module, ()))
    return seen


def test_the_checks_see_the_app():
    assert len(MODULES) > 60 and len(IMPORTS) > 300
    assert any(i.module == "app.main" and i.target.startswith("app.api.routes") for i in IMPORTS)


def test_no_module_needs_a_module_that_needs_it():
    """Also not through an import inside a function: that only hides the
    circle — the two modules still can't be understood, tested or changed
    one without the other."""
    graph = _graph()
    in_a_circle = sorted(module for module in MODULES if module in _reachable(module, graph))
    assert in_a_circle == []


def test_imports_stand_at_the_top_of_their_module():
    """Nothing needs another place any more (no circles, see above), and at
    the top a missing or misspelled name shows when the app starts, not
    when its function first runs."""
    inside = [imp for imp in IMPORTS if not imp.at_top and (imp.module, imp.target, imp.name) not in READ_WHEN_CALLED]
    assert inside == []
    # ... and the exceptions listed above still exist
    listed = {(imp.module, imp.target, imp.name) for imp in IMPORTS if not imp.at_top}
    assert READ_WHEN_CALLED <= listed


def test_private_names_stay_in_their_module():
    """A name another module imports is part of what its module offers:
    it has no leading underscore, or it lives in the wrong module."""
    borrowed = [imp for imp in IMPORTS if imp.name and imp.name.startswith("_")]
    assert borrowed == []


def test_the_foundations_do_not_reach_up():
    reaching_up = [
        imp for imp in IMPORTS
        if imp.module.startswith(FOUNDATIONS) and imp.target.startswith(ABOVE_FOUNDATIONS)
    ]
    assert reaching_up == []


def test_only_the_api_knows_the_api():
    """Services build what a route returns; they never ask a route for it.
    And a route takes what it shares with another route from a module of
    its own (app.api.params, app.api.transaction_listing)."""
    from_below = [
        imp for imp in IMPORTS
        if imp.target.startswith("app.api") and not imp.module.startswith("app.api") and imp.module != "app.main"
    ]
    assert from_below == []
    route_to_route = [
        imp for imp in IMPORTS
        if imp.module.startswith("app.api.routes.") and imp.target.startswith("app.api.routes.")
    ]
    assert route_to_route == []
