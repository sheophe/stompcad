"""The one statement of which packages this workspace contains.

Every structural gate that must scan "every workspace member" derives its
target list from :func:`member_package_dirs` rather than restating one, and
proves its reach with :func:`member_area_roots` — so no gate is the kind of
instrument ``CLAUDE.md``'s Testing rules reject, one that "can pass by
finding nothing". Any directory under ``packages/`` shipping its own ``src``
is included the moment it exists, with no edit to this module or to any gate
that calls it. ADR-0008 states both halves of that rule.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["REPO", "member_area_roots", "member_package_dirs"]

#: The repository root, two levels above this file (``tools/`` sits at the top).
REPO = Path(__file__).resolve().parent.parent


def member_package_dirs() -> tuple[Path, ...]:
    """Every workspace member's own directory under ``packages/``, sorted.

    A member is any child of ``packages/`` that ships a ``src`` directory —
    the shape every current member has, and the one a future member (a
    ``stompcollider``, say) would arrive with too.
    """
    packages_dir = REPO / "packages"
    return tuple(
        sorted(
            child
            for child in packages_dir.iterdir()
            if child.is_dir() and (child / "src").is_dir()
        )
    )


def member_area_roots(area: str) -> frozenset[Path]:
    """Ground truth for a gate's reach control, independent of
    :func:`member_package_dirs`'s own control flow.

    Every ``<area>`` directory under a workspace member, found by a second
    walk of ``packages/`` that never calls ``member_package_dirs``. It
    applies that function's own "ships a src" predicate again on purpose:
    the independence a reach control needs is a call site immune to a
    narrowed *return*, not a rival definition of membership -- a change to
    the predicate itself still needs both sites edited.
    """
    packages_dir = REPO / "packages"
    return frozenset(
        child / area
        for child in packages_dir.iterdir()
        if child.is_dir() and (child / "src").is_dir() and (child / area).is_dir()
    )
