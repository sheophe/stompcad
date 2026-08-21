"""What the branch ships, exercised the way a user reaches it.

Every assertion here reads the *installed* distribution rather than the
source tree: a source-tree glob would pass with ``[project.scripts]`` or
``[tool.setuptools.package-data]`` deleted, which is the whole failure this
file exists to notice.
"""

from __future__ import annotations

import importlib.metadata
import importlib.resources
import json
import subprocess
import sys
from pathlib import Path

import pytest

__all__: list[str] = []

FIXTURE = Path(__file__).parent / "fixtures" / "tar.ai"

#: Resolved beside the interpreter running the suite, not through PATH, so the
#: test does not depend on an activated virtualenv.
SCRIPT = Path(sys.executable).parent / "stompdrill"


@pytest.mark.skipif(not SCRIPT.exists(), reason="stompdrill is not installed as a script")
def test_the_console_script_drills_a_panel(tmp_path):
    """The one end-to-end assertion: the name a user types, the file it writes."""
    document = tmp_path / "panel.json"

    completed = subprocess.run(
        [str(SCRIPT), str(FIXTURE), "--case", "1590B", "--emit", f"json={document}"],
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1, completed.stderr.decode()
    assert len(json.loads(document.read_text(encoding="utf-8"))["holes"]) == 7


def test_the_entry_point_names_the_callable_the_script_runs():
    """A script that exists but points somewhere else is a different defect
    from a script that is missing, so it gets its own assertion."""
    scripts = {
        entry.name: entry.value
        for entry in importlib.metadata.entry_points(group="console_scripts")
    }

    assert scripts.get("stompdrill") == "stompdrill.cli:main"


@pytest.mark.parametrize("distribution", ["stompdrill", "stompmodel"])
def test_the_installed_package_carries_its_typing_marker(distribution):
    """PEP 561: without this marker a downstream type checker discards every
    annotation in the distribution. Read from the installed package, because
    that is where ``package-data`` either worked or did not."""
    assert importlib.resources.files(distribution).joinpath("py.typed").is_file()
