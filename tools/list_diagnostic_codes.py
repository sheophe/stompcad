"""Every diagnostic code the two tools raise, and which the driver can reach.

Spec decision 11: completeness is a test, not a promise. A code is read from
a literal, or from a code enum's ``.value`` on a parameter typed as that
enum, in any call that raises or builds a ``Diagnostic``. Any other call is
reported, since a scan that quietly knew less would pass by shrinking.
Reachability is a name graph per class or function: a guard with controls,
not a proof, so a new unreachable code is confirmed by reading the driver.
"""

from __future__ import annotations

import argparse
import ast
from collections import deque
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "UNREACHABLE",
    "Site",
    "Unit",
    "Unreadable",
    "codes_in",
    "reached",
    "unreadable_in",
]

_RAISERS = frozenset({"error", "warning", "info"})

#: The enums whose members are diagnostic codes, by name. Matching on ``Enum``
#: would report ``FrameStyle``, a drawing style, as a code with no family.
_CODE_ENUMS = frozenset({"Rejection"})

#: The packages whose calls raise the codes a run can report. The orchestrator
#: is one of them: a model it could not obtain is a failure of the run rather
#: than of either tool, so nothing below it is in a position to say so.
_TOOLS = ("stompdrill", "stompcollider", "stompcad")

#: A code no unit the driver reaches can raise, and why. Recorded rather than
#: omitted, so the family table states what the workbench cannot show.
UNREACHABLE: dict[str, str] = {
    # TODO(stompcollider): raise this from the composition layer both callers
    # share, so a library caller sees it; then delete this entry.
    "degenerate-geometry": (
        "raised only in stompcollider.cli._degenerate, wrapping a kernel failure; "
        "stompcad calls the library phases, so it arrives as a StompError instead"
    ),
    # TODO(stompcad): compose CheckReferenceSize into the drill half with a
    # workbench row for its expected size, or drop both of its family rows.
    "no-reference-outline": (
        "raised only in stompdrill's CheckReferenceSize, a library stage the "
        "driver never composes"
    ),
    "reference-size-mismatch": (
        "raised only in stompdrill's CheckReferenceSize, a library stage the "
        "driver never composes, and no workbench row holds the size it checks"
    ),
}

#: A class, function or assignment at a module's top level: (module, name).
Unit = tuple[str, str]


@dataclass(frozen=True, slots=True)
class Site:
    """Where one code is raised: the file, and the unit that raises it."""

    path: Path
    unit: Unit


@dataclass(frozen=True, slots=True)
class Unreadable:
    """A diagnostic call whose code this tool could not determine."""

    path: Path
    line: int
    text: str


@dataclass(frozen=True, slots=True)
class _Module:
    name: str
    path: Path
    tree: ast.Module


def _modules(roots: Iterable[Path]) -> dict[str, _Module]:
    """Every module under these ``src`` roots, by dotted name.

    A root that does not exist is an error rather than an empty scan: a
    completeness test run from the wrong directory would otherwise pass by
    reading nothing.
    """
    found: dict[str, _Module] = {}
    for root in roots:
        if not root.is_dir():
            raise FileNotFoundError(f"no source root at {root}")
        for path in sorted(root.rglob("*.py")):
            parts = list(path.relative_to(root).with_suffix("").parts)
            if parts[-1] == "__init__":
                parts.pop()
            name = ".".join(parts)
            found[name] = _Module(name, path, ast.parse(path.read_text(encoding="utf-8")))
    return found


def _top_units(tree: ast.Module) -> Iterator[tuple[str, ast.stmt]]:
    """Each top-level unit's name and the statement that defines it."""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield node.name, node
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for leaf in ast.walk(target):
                    if isinstance(leaf, ast.Name):
                        yield leaf.id, node


def _absolute(module: _Module, level: int, target: str | None) -> str:
    """A relative import's absolute module name."""
    if level == 0:
        return target or ""
    parts = module.name.split(".")
    if module.path.name != "__init__.py":
        parts = parts[:-1]
    parts = parts[: len(parts) - (level - 1)]
    return ".".join([*parts, *([target] if target else [])])


def _values(node: ast.AST) -> Iterator[ast.AST]:
    """Every node under this one, skipping annotations.

    An annotation names a type rather than using it, so following one would
    mark a class reached -- every method with it -- that nothing calls.
    """
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        for name, value in ast.iter_fields(current):
            if name in ("annotation", "returns"):
                continue
            if isinstance(value, ast.AST):
                stack.append(value)
            elif isinstance(value, list):
                stack.extend(item for item in value if isinstance(item, ast.AST))


class _Graph:
    """Top-level units, and what each names once imports are followed."""

    def __init__(self, modules: dict[str, _Module]) -> None:
        self.modules = modules
        self.units: dict[Unit, ast.stmt] = {
            (module.name, name): node
            for module in modules.values()
            for name, node in _top_units(module.tree)
        }
        self._names: dict[str, dict[str, Unit]] = {}
        self._aliases: dict[str, dict[str, str]] = {}
        for module in modules.values():
            names: dict[str, Unit] = {}
            aliases: dict[str, str] = {}
            for node in ast.walk(module.tree):
                if isinstance(node, ast.ImportFrom):
                    source = _absolute(module, node.level, node.module)
                    for alias in node.names:
                        local = alias.asname or alias.name
                        if f"{source}.{alias.name}" in modules:
                            aliases[local] = f"{source}.{alias.name}"
                        else:
                            names[local] = (source, alias.name)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.asname:
                            aliases[alias.asname] = alias.name
                        else:
                            head = alias.name.split(".")[0]
                            aliases[head] = head
            self._names[module.name] = names
            self._aliases[module.name] = aliases

    def resolve(self, module: str, name: str) -> Unit | None:
        """The unit this name means in this module, through any re-exports."""
        seen: set[Unit] = set()
        while (module, name) not in seen and module in self.modules:
            seen.add((module, name))
            if (module, name) in self.units:
                return (module, name)
            target = self._names[module].get(name)
            if target is None:
                return None
            module, name = target
        return None

    def named(self, unit: Unit) -> set[Unit]:
        """Every unit this one's definition names."""
        module = unit[0]
        found: set[Unit] = set()
        for node in _values(self.units[unit]):
            target: Unit | None = None
            if isinstance(node, ast.Name):
                target = self.resolve(module, node.id)
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                alias = self._aliases[module].get(node.value.id)
                if alias is not None:
                    target = self.resolve(alias, node.attr)
            if target is not None:
                found.add(target)
        return found


def reached(roots: Iterable[Path], entry: str) -> frozenset[Unit]:
    """Every unit reachable from ``entry``'s own units, by what each names.

    Naming a class reaches all of it, since a stage is built by name and run
    through a protocol. That errs loud where dispatch it cannot follow, or a
    loose module statement whose diagnostic nothing keeps, is called
    unreachable and fails the test for somebody to read; it errs quiet
    where a dead method inside a reached class counts as live, because the
    whole class was reached and the graph does not look inside it.
    """
    graph = _Graph(_modules(roots))
    start = [unit for unit in graph.units if unit[0] == entry]
    seen, queue = set(start), deque(start)
    while queue:
        for unit in graph.named(queue.popleft()):
            if unit not in seen:
                seen.add(unit)
                queue.append(unit)
    return frozenset(seen)


def _enum_values(modules: dict[str, _Module]) -> frozenset[str]:
    """The member values of every code enum, which must each be defined once.

    Matched by name, so two classes sharing one would pool their values; that
    is refused rather than guessed at, and the tool must be taught which. An
    annotated member (``NAME: str = 'x'``) counts the same as a plain one.
    """
    found: set[str] = set()
    defined: set[str] = set()
    for module in modules.values():
        for node in module.tree.body:
            if not isinstance(node, ast.ClassDef) or node.name not in _CODE_ENUMS:
                continue
            if node.name in defined:
                raise ValueError(f"{node.name} is defined more than once in the scanned roots")
            defined.add(node.name)
            for statement in node.body:
                if isinstance(statement, (ast.Assign, ast.AnnAssign)) and isinstance(
                    statement.value, ast.Constant
                ) and isinstance(statement.value.value, str):
                    found.add(statement.value.value)
    return frozenset(found)


def _diagnostic_names(tree: ast.Module) -> frozenset[str]:
    """Every name this module uses for ``Diagnostic``, aliases included."""
    names = {"Diagnostic"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(a.asname for a in node.names if a.name == "Diagnostic" and a.asname)
    return frozenset(names)


def _refers_to_diagnostic(expr: ast.expr, names: frozenset[str]) -> bool:
    """Whether this expression names the ``Diagnostic`` class, however qualified.

    ``pkg.Diagnostic`` reads the same as a bare or aliased import; dropping
    the qualified form would let a module-qualified raise pass unseen.
    """
    return (isinstance(expr, ast.Name) and expr.id in names) or (
        isinstance(expr, ast.Attribute) and expr.attr == "Diagnostic"
    )


def _is_replace_with_code(node: ast.Call) -> bool:
    """Whether this is a ``replace(...)`` call carrying a ``code=`` keyword.

    Covers ``dataclasses.replace`` and a bare import alike: either can set a
    diagnostic's code without going through a recognised raiser.
    """
    func = node.func
    named = (isinstance(func, ast.Name) and func.id == "replace") or (
        isinstance(func, ast.Attribute) and func.attr == "replace"
    )
    return named and any(keyword.arg == "code" for keyword in node.keywords)


def _code_argument(node: ast.Call, names: frozenset[str]) -> tuple[bool, ast.expr | None]:
    """Whether this call raises or builds a ``Diagnostic``, and the code it
    passes. ``Diagnostic.warning(code, ...)`` passes it first and
    ``Diagnostic(severity, code, ...)`` second; either may name it ``code=``
    or reach ``Diagnostic`` through a qualified name such as ``sd.Diagnostic``.
    """
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr in _RAISERS and _refers_to_diagnostic(
        func.value, names
    ):
        position = 0
    elif _refers_to_diagnostic(func, names):
        position = 1
    else:
        return False, None
    keyword = next((k.value for k in node.keywords if k.arg == "code"), None)
    return True, keyword if keyword is not None else (
        node.args[position] if len(node.args) > position else None
    )


def _unit_at(tree: ast.Module, line: int) -> str:
    """The top-level unit a line belongs to, or ``""`` for loose statements."""
    for name, node in _top_units(tree):
        if node.lineno <= line <= (node.end_lineno or node.lineno):
            return name
    return ""


def _annotated_as_code(tree: ast.Module, line: int, name: str) -> bool:
    """Whether ``name`` is a parameter of the enclosing function typed as a code enum."""
    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.lineno <= line <= (node.end_lineno or node.lineno)
    ]
    if not functions:
        return False
    innermost = max(functions, key=lambda node: node.lineno)
    arguments = [*innermost.args.posonlyargs, *innermost.args.args, *innermost.args.kwonlyargs]
    for argument in arguments:
        annotation = argument.annotation
        if argument.arg == name and (
            (isinstance(annotation, ast.Name) and annotation.id in _CODE_ENUMS)
            or (isinstance(annotation, ast.Constant) and annotation.value in _CODE_ENUMS)
        ):
            return True
    return False


def _scan(
    roots: Iterable[Path], tools: tuple[str, ...]
) -> tuple[dict[str, set[Site]], list[Unreadable]]:
    """Every raise site in these tools' modules, and every call not understood."""
    modules = _modules(roots)
    values = _enum_values(modules)
    sites: dict[str, set[Site]] = {}
    unreadable: list[Unreadable] = []
    for module in modules.values():
        if module.name.split(".")[0] not in tools:
            continue
        names = _diagnostic_names(module.tree)
        consumed: set[int] = set()
        for node in ast.walk(module.tree):
            if isinstance(node, ast.Call):
                raises, first = _code_argument(node, names)
                if raises:
                    if isinstance(node.func, ast.Attribute):
                        consumed.add(id(node.func))
                    codes: frozenset[str]
                    if isinstance(first, ast.Constant) and isinstance(first.value, str):
                        codes = frozenset({first.value})
                    elif (
                        isinstance(first, ast.Attribute)
                        and first.attr == "value"
                        and isinstance(first.value, ast.Name)
                        and _annotated_as_code(module.tree, node.lineno, first.value.id)
                        and values
                    ):
                        codes = values
                    else:
                        shown = ast.unparse(first) if first is not None else "no positional code"
                        unreadable.append(Unreadable(module.path, node.lineno, shown))
                        continue
                    unit = (module.name, _unit_at(module.tree, node.lineno))
                    for code in codes:
                        sites.setdefault(code, set()).add(Site(module.path, unit))
                elif _is_replace_with_code(node):
                    unreadable.append(Unreadable(module.path, node.lineno, ast.unparse(node)))
            elif (
                isinstance(node, ast.Attribute)
                and node.attr in _RAISERS
                and _refers_to_diagnostic(node.value, names)
                and id(node) not in consumed
            ):
                unreadable.append(Unreadable(module.path, node.lineno, ast.unparse(node)))
    return sites, unreadable


def codes_in(
    roots: Iterable[Path], tools: tuple[str, ...] = _TOOLS
) -> dict[str, frozenset[Site]]:
    """Every code these tools raise, and each place that raises it."""
    sites, _ = _scan(roots, tools)
    return {code: frozenset(found) for code, found in sites.items()}


def unreadable_in(
    roots: Iterable[Path], tools: tuple[str, ...] = _TOOLS
) -> tuple[Unreadable, ...]:
    """Every diagnostic call these tools make whose code could not be read."""
    return tuple(_scan(roots, tools)[1])


def main() -> int:
    """List each code, marking those the entry point cannot reach."""
    parser = argparse.ArgumentParser(description="List every diagnostic code.")
    parser.add_argument("roots", nargs="+", type=Path, help="source roots, each a src/")
    parser.add_argument("--entry", default="stompcad.drive", help="the driver's module")
    arguments = parser.parse_args()
    unreadable = unreadable_in(arguments.roots)
    for site in unreadable:
        print(f"{site.path}:{site.line}: unreadable: {site.text}")
    live = reached(arguments.roots, arguments.entry)
    for code, sites in sorted(codes_in(arguments.roots).items()):
        mark = "" if any(site.unit in live for site in sites) else "  (unreachable)"
        print(f"{code}{mark}")
    return 1 if unreadable else 0


if __name__ == "__main__":
    raise SystemExit(main())
