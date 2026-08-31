"""The workspace's kernel layer.

The operations that need OpenCASCADE: reading a STEP assembly, writing one
deterministically, partitioning a solid's faces into the planes they lie in,
and building an assembly from placed, named, coloured solids. No enclosure
vocabulary crosses this boundary. See ADR-0008 and ADR-0009.
"""

from __future__ import annotations

#: Deliberately empty. Every value here is imported from the module that
#: defines it -- one name, one home, and no second import path to drift.
__all__: list[str] = []
