"""Two fixed outputs: the dock report and the assembly model. No registry.

``stompdrill``'s registry earns its keep across six formats where a seventh
is expected; here it would be ceremony around a two-element set. A caller
imports each emitter from its own module; both are re-exported here for
convenience, mirroring the workspace's other package roots.
"""

from __future__ import annotations

from .assembly import AssemblyEmitter
from .report import ReportEmitter

__all__ = ["AssemblyEmitter", "ReportEmitter"]
