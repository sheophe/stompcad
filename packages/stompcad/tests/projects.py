"""A project a run is one keypress away from, and a wait for one to finish.

Every test that starts a run needs settings a run can actually be built
from: ``DEFAULTS`` has no panel, and ``RunOptions.of`` refuses a project
without one. Shared rather than copied, because two answers to "nothing
outstanding" drift the first time a place gained a value.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from textual.pilot import Pilot

from stompcad import manifest
from stompcad.cli import Resolution
from stompcad.readiness import readiness
from stompcad.settings import DEFAULTS, Origin, Provenance, Resolved, Settings
from stompcad.workbench.app import Workbench
from stompcad.workbench.session import Phase, Session

__all__ = ["PANEL", "runnable", "session", "settle"]

PANEL = Path("/project/tar.ai")


def session(
    ready: bool = True,
    validator: Callable[[Settings, str], None] | None = None,
    settings: Settings | None = None,
) -> Session:
    """A session whose edits are checked by the real consuming tool, as a run's are.

    ``settings`` replaces the whole project where a test needs one of its
    own -- real files for the viewer, say -- rather than a patched copy.
    """
    if settings is None:
        settings = runnable() if ready else replace(runnable(), boards=DEFAULTS.boards)
    return Session(
        Resolution(
            settings=settings,
            notes=(),
            blockers=readiness(settings),
            project=manifest.Manifest(),
        ),
        validator=validator,
    )


def runnable() -> Settings:
    """A project with nothing outstanding, so a run is one keypress away."""
    base = Settings.of_defaults(PANEL)
    return replace(
        base,
        enclosure=replace(
            base.enclosure,
            case=Resolved("1590B", Provenance(Origin.PROJECT)),
        ),
        boards=replace(
            base.boards,
            boards=Resolved((Path("/project/tar-pcb.stp"),), Provenance(Origin.PROJECT)),
            panel_reference=Resolved("RV*", Provenance(Origin.PROJECT)),
        ),
        output=replace(
            base.output,
            targets=Resolved(
                (("excellon", Path("/project/tar-case.drl")),), Provenance(Origin.PROJECT)
            ),
        ),
    )


async def settle(pilot: Pilot[int], app: Workbench, patience: int = 400) -> None:
    """Pause until the run is no longer working, however many frames that takes.

    A read of the artwork is waited out first. A run may not start under one,
    and an autostarted run starts as it lands, so looking only at the phase
    would return before the run being waited for had begun.
    """
    for _ in range(patience):
        if not app.session.fit_pending:
            break
        await pilot.pause()
    else:
        raise AssertionError("the artwork was still being read")
    for _ in range(patience):
        if app.session.phase is not Phase.RUNNING:
            return
        await pilot.pause()
        await asyncio.sleep(0.01)
    raise AssertionError(f"the run never settled; the phase is {app.session.phase}")
