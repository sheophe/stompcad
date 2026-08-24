"""The one statement of which packages this workspace contains.

Every structural gate that must scan "every workspace member" derives its
target list from :func:`member_package_dirs` rather than restating one. A
package added under ``packages/`` — any directory shipping its own ``src`` —
is included the moment it exists, with no edit to this module or to any gate
that calls it. See ADR-0008, and ``CLAUDE.md``'s Testing rules on ownership
gates.
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
    :func:`member_package_dirs`.

    Every ``<area>`` directory (``"src"``, ``"tests"``) under a workspace
    member, found by a walk of ``packages/`` that never calls
    ``member_package_dirs``. Comparing a scan to that function called a
    second time proves nothing about under-reaching, only self-agreement;
    this is computed a second, independent way so the two can disagree.
    """
    packages_dir = REPO / "packages"
    return frozenset(
        child / area
        for child in packages_dir.iterdir()
        if child.is_dir() and (child / "src").is_dir() and (child / area).is_dir()
    )
