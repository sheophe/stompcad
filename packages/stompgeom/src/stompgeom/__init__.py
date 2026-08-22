"""The workspace's kernel layer.

The format side of geometry: reading a STEP assembly, writing one
deterministically, and refusing to start without the kernel. No enclosure
vocabulary crosses this boundary. See ADR-0008 and ADR-0009.
"""

from __future__ import annotations

#: Deliberately empty. Every value here is imported from the module that
#: defines it -- one name, one home, and no second import path to drift.
__all__: list[str] = []
