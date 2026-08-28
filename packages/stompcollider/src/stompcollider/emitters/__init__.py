"""Two fixed outputs: the dock report and the assembly model. No registry.

``stompdrill``'s registry earns its keep across six formats where a seventh
is expected; here it would be ceremony around a two-element set -- see
``docs/specs/stompcollider-technical.md``'s "Emitters". A caller imports
each emitter from its own module; ``ReportEmitter`` is re-exported here for
convenience, mirroring the workspace's other package roots.
"""

from __future__ import annotations

from .report import ReportEmitter

__all__ = ["ReportEmitter"]
