"""The values every stomp package exchanges.

Pure Python by construction: no kernel, no parser, no I/O beyond
serialisation. What lives here either crosses a package boundary with no
owner, or is a contract both tools implement identically. See ADR-0009.
"""

from __future__ import annotations

#: Deliberately empty. Every value here is imported from the module that
#: defines it — one name, one home, and no second import path to drift.
__all__: list[str] = []
